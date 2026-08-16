"""MCP Server entry point for aliyun-billing-validator-mcp.

Thin proxy: exposes the same 7 MCP tools QwenWork already knows, but holds ZERO
business logic. Every tool forwards over HTTP to aliyun-billing-validator-agent
(the brain: LangGraph + SAP AI Core + OData + staged files), then returns the
agent's answer verbatim.

    QwenWork ──MCP(streamable-http /mcp)──> THIS proxy ──httpx+Bearer──> agent REST

Inbound auth : static API key via MCP_API_KEY (QwenWork sends Authorization: Bearer <MCP_API_KEY>).
Outbound auth: static API key via AGENT_API_KEY (this proxy sends Authorization: Bearer <AGENT_API_KEY>).
Agent base   : AGENT_BASE_URL (full https route of the agent app).
"""

import logging
import os
import sys
import uuid

import httpx
from cfenv import AppEnv
from dotenv import load_dotenv

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

# ── Config ──────────────────────────────────────────────────────────────────��─
AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "http://localhost:5001").rstrip("/")
AGENT_API_KEY  = os.getenv("AGENT_API_KEY", "")
MCP_API_KEY    = os.getenv("MCP_API_KEY", "")
HTTP_TIMEOUT   = float(os.getenv("AGENT_HTTP_TIMEOUT", "180"))

# ── MCP Server ────────────────────────────────────────────────────────────────
import hmac

from fastmcp import FastMCP
from pydantic import BaseModel

mcp = FastMCP(
    name="billing-validator",
    instructions=(
        "SAP 3PL Billing Validator Agent. "
        "Upload rate cards (CSV) and billing invoices (PDF), run AI-powered "
        "cross-validation, query historical results, and submit for approval."
    ),
)


class BearerAuthMiddleware:
    """Pure-ASGI Bearer check for the /mcp endpoint (SSE-safe: never buffers the body).

    key falsy (unset) → open access (dev mode). Otherwise constant-time compare;
    401 on mismatch. Guards the QwenWork-direct MCP endpoint with a static MCP_API_KEY.
    """

    def __init__(self, app, key: str) -> None:
        self._app, self._key = app, key

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not self._key:
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode("latin-1")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(
            auth[7:].encode(), self._key.encode()
        ):
            body = b'{"error": "unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body, "more_body": False})
            return
        await self._app(scope, receive, send)


def _agent_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if AGENT_API_KEY:
        headers["Authorization"] = f"Bearer {AGENT_API_KEY}"
    return headers


async def _forward(method: str, endpoint: str, payload: dict | None = None) -> str:
    """Forward a call to the agent and return its `result` string verbatim."""
    url = f"{AGENT_BASE_URL}{endpoint}"
    logger.info("proxy %s %s", method, endpoint)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            if method == "GET":
                resp = await client.get(url, headers=_agent_headers())
            else:
                resp = await client.post(url, headers=_agent_headers(), json=payload or {})
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("agent %s %s -> HTTP %s: %s", method, endpoint, e.response.status_code, e.response.text[:500])
        return f"Agent error ({e.response.status_code}): {e.response.text[:500]}"
    except httpx.HTTPError as e:
        logger.error("agent %s %s -> transport error: %s", method, endpoint, e)
        return f"Failed to reach billing agent: {e}"

    try:
        data = resp.json()
    except ValueError:
        return resp.text
    return data.get("result", resp.text) if isinstance(data, dict) else str(data)


# ── SAP Agent Hub unified entry ─────────────────────────────────────────────────
#
# The hub (and QwenWork via the hub) speaks a single `chat` tool per the hub
# integration contract: chat(user_input, session_id|null) -> {session_id, answer}.
# It proxies to the agent's /ask, exactly like ask_billing_agent, but wraps the
# result in the hub's structured envelope. The 7 granular tools below remain for
# QwenWork-direct (non-hub) usage — this is purely additive.


class ChatOutput(BaseModel):
    session_id: str
    answer: str


@mcp.tool()
async def chat(user_input: str, session_id: str | None = None) -> ChatOutput:
    """SAP 3PL 物流账单校验智能体。校验第三方物流(3PL)账单发票与合同费率卡的一致性:
    OCR 提取发票行项、逐项比对合同单价、识别超收/价格错配/漏项差异并算出差异金额,
    对问题发票生成驳回意见与供应商整改邮件草稿,支持费率卡上传与账单历史查询。

    Args:
        user_input: 用户的自然语言问题(必需)。
        session_id: 传 null 开启新会话,传上轮返回的 session_id 续接多轮对话。
    """
    sid = session_id or str(uuid.uuid4())
    answer = await _forward("POST", "/ask", {"query": user_input, "session_id": sid})
    return ChatOutput(session_id=sid, answer=answer)


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
    return await _forward("POST", "/ask", {"query": query, "session_id": session_id})


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
    return await _forward("POST", "/billing/upload-pdf", {
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
    return await _forward("POST", "/ratecard/upload", {
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
    return await _forward("GET", "/staged/files")


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
    return await _forward("POST", "/staged/validate-pdf", {
        "file_name":    file_name,
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
    return await _forward("POST", "/staged/upload-ratecard", {
        "file_name":   file_name,
        "name":        name,
        "valid_from":  valid_from,
        "valid_to":    valid_to,
        "description": description,
    })


@mcp.tool()
async def reject_invoice_and_draft_email(
    invoice_number: str,
    discrepancy_description: str,
    supplier_contact_email: str = "billing@huadong-logistics.com",
) -> str:
    """Submit a rejection for a billing invoice and generate a supplier notification email draft.

    Use this tool when the user confirms they want to reject an invoice that failed
    validation and notify the supplier to re-issue it at the correct contractual rate.

    The email is generated as a DRAFT ONLY — it will NOT be sent automatically.
    Present the draft to the user for review and confirmation before any sending.

    Args:
        invoice_number: Invoice number to reject (e.g. "HDLS-INV-202610-003").
        discrepancy_description: Brief description of the discrepancy (service item,
            contract rate, billed rate, overcharge amount).
        supplier_contact_email: Supplier billing contact email (default provided).
    """
    return await _forward("POST", "/billing/reject", {
        "invoice_number":         invoice_number,
        "discrepancy_description": discrepancy_description,
        "supplier_contact_email":  supplier_contact_email,
    })


def main():
    import uvicorn
    from starlette.middleware import Middleware

    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info("=== Billing Validator MCP proxy starting on %s:%d ===", host, port)
    logger.info("Forwarding to agent: %s", AGENT_BASE_URL)
    logger.info("MCP endpoint auth: %s", "ENABLED" if MCP_API_KEY else "OPEN (no key)")

    # Streamable-HTTP + SSE-safe Bearer auth on /mcp.
    # stateless_http=True per the SAP Agent Hub contract (hub calls /mcp without an
    # MCP initialize handshake / session id). Also broadens compatibility for
    # QwenWork-direct — no session id required.
    app = mcp.http_app(
        transport="streamable-http",
        stateless_http=True,
        middleware=[Middleware(BearerAuthMiddleware, key=MCP_API_KEY)],
    )

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
