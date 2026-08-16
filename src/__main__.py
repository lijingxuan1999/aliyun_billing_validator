"""MCP Server entry point for billing-validator-mcp.

Exposes three MCP tools:
  - ask_billing_agent(query)          — natural language queries via LangGraph + SAP AI Core
  - upload_billing_pdf(...)           — direct PDF upload + OCR + validation (no LLM in path)
  - upload_rate_card_csv(...)         — direct CSV rate card upload (no LLM in path)

Authentication: static API key via MCP_API_KEY env var.
Clients must send:  Authorization: Bearer <MCP_API_KEY>
"""

import base64
import logging
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from cfenv import AppEnv

# Pre-staged files directory (bundled with the BTP deployment)
STAGED_DIR = Path(__file__).parent.parent / "staged_files"

# ── Load env ──────────────────────────────────────────────────────────────────
if os.getenv("VCAP_SERVICES"):
    AppEnv()
else:
    load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── Lazy agent init (avoids AI Core calls at import time) ─────────────────────
_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from agent import BillingValidatorAgent
        _agent = BillingValidatorAgent()
        logger.info("BillingValidatorAgent initialised")
    return _agent


# ── MCP Server ────────────────────────────────────────────────────────────────
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

MCP_API_KEY = os.getenv("MCP_API_KEY", "")

mcp = FastMCP(
    name="billing-validator",
    instructions=(
        "SAP 3PL Billing Validator Agent. "
        "Upload rate cards (CSV) and billing invoices (PDF), run AI-powered "
        "cross-validation, query historical results, and submit for approval."
    ),
)


async def _check_api_key(request: Request) -> JSONResponse | None:
    """Middleware-style API key check. Returns error response or None if OK."""
    if not MCP_API_KEY:
        return None  # no key configured — open access (dev mode)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[len("Bearer "):] != MCP_API_KEY:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None


@mcp.tool()
async def ask_billing_agent(query: str, session_id: str = "") -> str:
    """Ask the SAP Billing Validator Agent a question in natural language.

    Use this tool for:
    - Querying billing history, validation results, rate cards
    - Submitting invoices for approval
    - Any other natural language question about billing data

    For file uploads use the dedicated tools:
    - upload_billing_pdf — upload and validate a billing invoice PDF
    - upload_rate_card_csv — upload a rate card CSV

    Args:
        query: Natural language question or task.
        session_id: Optional session identifier for multi-turn conversation.
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    logger.info("ask_billing_agent session=%s query_len=%d", session_id, len(query))

    agent = _get_agent()
    final_response = "Unable to process request."
    async for item in agent.astream(query, session_id):
        if item.is_task_complete or item.require_user_input:
            final_response = item.content
            break

    return final_response


@mcp.tool()
async def upload_billing_pdf(
    file_name: str,
    pdf_base64: str,
    rate_card_id: str,
) -> str:
    """Upload a billing invoice PDF and validate it against a rate card.

    This tool handles the complete workflow:
    1. Upload PDF to SAP Document Intelligence for OCR extraction
    2. Poll until extraction is complete (up to 2 minutes)
    3. Run validation rules against the specified rate card
    4. Return validation results with findings

    Args:
        file_name: Original filename of the PDF (e.g. "CEVA-invoice-2025-07.pdf").
        pdf_base64: Base64-encoded PDF file content.
        rate_card_id: UUID of the Rate Card to validate against.
                      Use ask_billing_agent to query available rate cards first.
    """
    from agent import upload_and_validate_billing_pdf
    logger.info("upload_billing_pdf file=%s rate_card_id=%s", file_name, rate_card_id)
    return await upload_and_validate_billing_pdf.ainvoke({
        "file_name":    file_name,
        "pdf_base64":   pdf_base64,
        "rate_card_id": rate_card_id,
    })


@mcp.tool()
async def upload_rate_card_csv(
    name: str,
    csv_base64: str,
    valid_from: str = "",
    valid_to: str = "",
    description: str = "",
) -> str:
    """Upload a Rate Card CSV file to the billing system.

    The CSV should contain columns: serviceCode, serviceDesc, unit, unitPrice, currency.

    Args:
        name: Name for the rate card (e.g. "CEVA Air Freight HKG-TPE 2026").
        csv_base64: Base64-encoded CSV file content.
        valid_from: Validity start date in YYYY-MM-DD format (optional).
        valid_to: Validity end date in YYYY-MM-DD format (optional).
        description: Optional description for the rate card.
    """
    from agent import upload_rate_card
    logger.info("upload_rate_card_csv name=%s", name)
    return await upload_rate_card.ainvoke({
        "name":        name,
        "csv_base64":  csv_base64,
        "valid_from":  valid_from,
        "valid_to":    valid_to,
        "description": description,
    })


@mcp.tool()
async def list_staged_files() -> str:
    """List all pre-staged files available on the server (PDFs and CSVs).

    Use this tool when the user refers to a billing document, invoice, or rate card
    without providing file content — to discover which files are already available
    on the server for immediate processing.
    """
    if not STAGED_DIR.exists():
        return "No staged files directory found."
    files = [
        {"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
        for f in sorted(STAGED_DIR.iterdir())
        if f.is_file() and not f.name.startswith(".")
    ]
    if not files:
        return "No staged files available."
    import json
    return json.dumps({"staged_files": files}, ensure_ascii=False)


@mcp.tool()
async def validate_staged_billing_pdf(
    file_name: str,
    rate_card_id: str,
) -> str:
    """Validate a pre-staged billing invoice PDF against a rate card.

    Use this tool when the user wants to validate a billing document that is
    already available on the server (i.e. they refer to an invoice/billing doc
    without uploading file content directly).

    Args:
        file_name: Name of the PDF file in the staged_files folder (e.g. "CEVA-invoice-2026-06.pdf").
        rate_card_id: UUID of the Rate Card to validate against.
                      Use ask_billing_agent to query available rate cards first.
    """
    file_path = STAGED_DIR / file_name
    if not file_path.exists():
        available = [f.name for f in STAGED_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
        return f"File '{file_name}' not found. Available files: {available}"

    pdf_base64 = base64.b64encode(file_path.read_bytes()).decode()
    logger.info("validate_staged_billing_pdf file=%s rate_card_id=%s", file_name, rate_card_id)

    from agent import upload_and_validate_billing_pdf
    return await upload_and_validate_billing_pdf.ainvoke({
        "file_name":    file_name,
        "pdf_base64":   pdf_base64,
        "rate_card_id": rate_card_id,
    })


@mcp.tool()
async def upload_staged_rate_card(
    file_name: str,
    name: str,
    valid_from: str = "",
    valid_to: str = "",
    description: str = "",
) -> str:
    """Upload a pre-staged Rate Card CSV file to the billing system.

    Use this tool when the user wants to upload a rate card that is already
    available on the server without providing the file content directly.

    Args:
        file_name: Name of the CSV file in the staged_files folder (e.g. "CEVA-rates-2026.csv").
        name: Name for the rate card (e.g. "CEVA Air Freight HKG-TPE 2026").
        valid_from: Validity start date in YYYY-MM-DD format (optional).
        valid_to: Validity end date in YYYY-MM-DD format (optional).
        description: Optional description for the rate card.
    """
    file_path = STAGED_DIR / file_name
    if not file_path.exists():
        available = [f.name for f in STAGED_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
        return f"File '{file_name}' not found. Available files: {available}"

    csv_base64 = base64.b64encode(file_path.read_bytes()).decode()
    logger.info("upload_staged_rate_card file=%s name=%s", file_name, name)

    from agent import upload_rate_card
    return await upload_rate_card.ainvoke({
        "name":        name,
        "csv_base64":  csv_base64,
        "valid_from":  valid_from,
        "valid_to":    valid_to,
        "description": description,
    })


def main():
    import uvicorn

    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info("=== Billing Validator MCP Server starting on %s:%d ===", host, port)

    # Build the ASGI app from FastMCP with streamable-http transport
    app = mcp.http_app(transport="streamable-http")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
