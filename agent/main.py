"""HTTP entry point for aliyun-billing-validator-agent.

Exposes the BillingValidatorAgent (LangGraph + SAP AI Core) over TWO transports
that both funnel into the same graph — the two integrations are independent:

  1. REST  — consumed by aliyun-billing-validator-mcp (the thin MCP proxy):
       POST /ask                    — natural language query
       POST /billing/upload-pdf     — upload + validate a billing PDF
       POST /ratecard/upload        — upload a rate card CSV
       GET  /staged/files           — list pre-staged demo files
       POST /staged/validate-pdf    — validate a pre-staged PDF
       POST /staged/upload-ratecard — upload a pre-staged rate card
       POST /billing/reject         — reject an invoice + draft supplier email
       GET  /health                 — liveness probe

  2. A2A   — consumed by an agent hub / Joule:
       GET  /.well-known/agent-card.json  (+ /agent.json) — agent card
       POST /                              — JSON-RPC message/send

Inbound auth (REST + JSON-RPC): optional static Bearer AGENT_API_KEY.
Outbound: agent.py's OData client authenticates to billing-validator-srv via XSUAA.
"""

import base64
import json
import logging
import os
import sys
import uuid
from pathlib import Path

import uvicorn
from cfenv import AppEnv
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# ── Pre-staged files (bundled with the deployment) ─────────────────────────────
STAGED_DIR  = Path(__file__).parent / "staged_files"
CONTRACT_NO = "HZL-2026-003"

# ── Load env ───────────────────────────────────────────────────────────────────
if os.getenv("VCAP_SERVICES"):
    AppEnv()
else:
    load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────��─
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

AGENT_API_KEY = os.getenv("AGENT_API_KEY", "")

# ── Lazy agent init (avoids AI Core calls at import time) ──────────────────────
_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from agent import BillingValidatorAgent
        _agent = BillingValidatorAgent()
        logger.info("BillingValidatorAgent initialised")
    return _agent


def _check_api_key(request: Request) -> JSONResponse | None:
    """Static Bearer check. Returns an error response, or None if authorised."""
    if not AGENT_API_KEY:
        return None  # no key configured — open access (dev mode)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[len("Bearer "):] != AGENT_API_KEY:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None


async def _run_agent(query: str, session_id: str) -> str:
    """Run the LangGraph agent to completion and return the final text answer."""
    if not session_id:
        session_id = str(uuid.uuid4())
    agent = _get_agent()
    final_response = "Unable to process request."
    async for item in agent.astream(query, session_id):
        if item.is_task_complete or item.require_user_input:
            final_response = item.content
            break
    return final_response


# ── REST handlers (consumed by the MCP proxy) ──────────────────────────────────


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "aliyun-billing-validator-agent"})


async def ask(request: Request) -> JSONResponse:
    if (err := _check_api_key(request)):
        return err
    body = await request.json()
    query = body.get("query", "")
    session_id = body.get("session_id", "")
    logger.info("ask session=%s query_len=%d", session_id, len(query))
    answer = await _run_agent(query, session_id)
    return JSONResponse({"result": answer})


async def billing_upload_pdf(request: Request) -> JSONResponse:
    if (err := _check_api_key(request)):
        return err
    from agent import upload_and_validate_billing_pdf
    body = await request.json()
    logger.info("billing_upload_pdf file=%s", body.get("file_name"))
    result = await upload_and_validate_billing_pdf.ainvoke({
        "file_name":    body.get("file_name"),
        "pdf_base64":   body.get("pdf_base64"),
        "rate_card_id": body.get("rate_card_id"),
    })
    return JSONResponse({"result": result})


async def ratecard_upload(request: Request) -> JSONResponse:
    if (err := _check_api_key(request)):
        return err
    from agent import upload_rate_card
    body = await request.json()
    logger.info("ratecard_upload name=%s", body.get("name"))
    result = await upload_rate_card.ainvoke({
        "name":        body.get("name"),
        "csv_base64":  body.get("csv_base64"),
        "valid_from":  body.get("valid_from", ""),
        "valid_to":    body.get("valid_to", ""),
        "description": body.get("description", ""),
    })
    return JSONResponse({"result": result})


async def staged_files(request: Request) -> JSONResponse:
    if (err := _check_api_key(request)):
        return err
    if not STAGED_DIR.exists():
        return JSONResponse({"result": "No staged files directory found."})
    files = [
        {"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
        for f in sorted(STAGED_DIR.iterdir())
        if f.is_file() and not f.name.startswith(".")
    ]
    if not files:
        return JSONResponse({"result": "No staged files available."})
    return JSONResponse({"result": json.dumps({"staged_files": files}, ensure_ascii=False)})


async def staged_validate_pdf(request: Request) -> JSONResponse:
    if (err := _check_api_key(request)):
        return err
    from agent import upload_and_validate_billing_pdf
    body = await request.json()
    file_name = body.get("file_name", "")
    rate_card_id = body.get("rate_card_id", "")
    file_path = STAGED_DIR / file_name
    if not file_path.exists():
        available = [f.name for f in STAGED_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
        return JSONResponse({"result": f"File '{file_name}' not found. Available files: {available}"})
    pdf_base64 = base64.b64encode(file_path.read_bytes()).decode()
    logger.info("staged_validate_pdf file=%s rate_card_id=%s", file_name, rate_card_id)
    result = await upload_and_validate_billing_pdf.ainvoke({
        "file_name":    file_name,
        "pdf_base64":   pdf_base64,
        "rate_card_id": rate_card_id,
    })
    return JSONResponse({"result": result})


async def staged_upload_ratecard(request: Request) -> JSONResponse:
    if (err := _check_api_key(request)):
        return err
    from agent import upload_rate_card
    body = await request.json()
    file_name = body.get("file_name", "")
    file_path = STAGED_DIR / file_name
    if not file_path.exists():
        available = [f.name for f in STAGED_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
        return JSONResponse({"result": f"File '{file_name}' not found. Available files: {available}"})
    csv_base64 = base64.b64encode(file_path.read_bytes()).decode()
    logger.info("staged_upload_ratecard file=%s name=%s", file_name, body.get("name"))
    result = await upload_rate_card.ainvoke({
        "name":        body.get("name"),
        "csv_base64":  csv_base64,
        "valid_from":  body.get("valid_from", ""),
        "valid_to":    body.get("valid_to", ""),
        "description": body.get("description", ""),
    })
    return JSONResponse({"result": result})


def _build_rejection(
    invoice_number: str,
    discrepancy_description: str,
    supplier_contact_email: str = "billing@huadong-logistics.com",
) -> dict:
    """Pure rejection + email-draft builder (moved verbatim from the old MCP server)."""
    approval_flow_no = "PR-20261028-007"
    submitted_at     = "2026-10-28 14:32:05"

    email_subject = (
        f"Invoice Rejection Notice — {invoice_number} | Contract {CONTRACT_NO}"
    )
    email_body = f"""\
Dear Billing Team,

Following our automated billing audit under Contract {CONTRACT_NO}, a discrepancy \
has been identified in Invoice {invoice_number}. We are formally notifying you of \
its rejection and requesting a corrected re-invoice.

REJECTION DETAILS
─────────────────────────────────────────
Invoice No.          : {invoice_number}
Contract No.         : {CONTRACT_NO}
Rejection Reference  : {approval_flow_no}
Submitted            : {submitted_at}

DISCREPANCY IDENTIFIED
─────────────────────────────────────────
{discrepancy_description}

ACTION REQUIRED
─────────────────────────────────────────
Please re-issue the invoice applying the contractual unit rate as specified in \
Contract {CONTRACT_NO}. The corrected invoice should be submitted within \
5 business days of this notice.

For any queries regarding this rejection, please contact our Logistics Finance team.

Best regards,
Huazhong Machinery Group Co., Ltd.
Logistics Finance Department
logistics-finance@huazhong-machinery.com
"""
    return {
        "rejection": {
            "status":            "submitted",
            "invoice_number":    invoice_number,
            "approval_flow_no":  approval_flow_no,
            "submitted_at":      submitted_at,
            "message":           f"Rejection request submitted. Approval flow: {approval_flow_no}",
        },
        "email_draft": {
            "status":   "draft — awaiting user confirmation before sending",
            "to":       supplier_contact_email,
            "subject":  email_subject,
            "body":     email_body,
        },
    }


async def billing_reject(request: Request) -> JSONResponse:
    if (err := _check_api_key(request)):
        return err
    body = await request.json()
    invoice_number = body.get("invoice_number", "")
    discrepancy_description = body.get("discrepancy_description", "")
    supplier_contact_email = body.get("supplier_contact_email", "billing@huadong-logistics.com")
    logger.info("billing_reject invoice=%s", invoice_number)
    result = _build_rejection(invoice_number, discrepancy_description, supplier_contact_email)
    return JSONResponse({"result": json.dumps(result, ensure_ascii=False, indent=2)})


# ── A2A surface (consumed by an agent hub / Joule) ─────────────────────────────


def _agent_url() -> str:
    if os.getenv("VCAP_SERVICES"):
        try:
            uris = AppEnv().app.get("application_uris", [])
            if uris:
                return f"https://{uris[0]}/"
        except Exception:
            logger.warning("Could not read application_uris from VCAP")
    host = os.getenv("HOST", "127.0.0.1")
    port = os.getenv("PORT", "5000")
    return f"http://{host}:{port}/"


def _agent_card() -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": "Billing Validator Agent",
        "description": (
            "SAP 3PL billing validator. Validates logistics invoices against rate "
            "cards, surfaces overcharges and discrepancies, and drafts supplier "
            "rejection notices. Backed by SAP AI Core, Document Intelligence and HANA."
        ),
        "url": _agent_url(),
        "version": "1.0.0",
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "capabilities": {"streaming": False, "pushNotifications": False},
        "skills": [
            {
                "id": "billing_validate",
                "name": "Billing Invoice Validation",
                "description": (
                    "Validate a billing invoice against its rate card and report "
                    "overcharges, price mismatches and other findings."
                ),
                "tags": ["billing", "3pl", "validation", "logistics", "rate-card"],
            },
            {
                "id": "rate_card",
                "name": "Rate Card Management",
                "description": "Upload and query 3PL rate cards.",
                "tags": ["rate-card", "pricing"],
            },
            {
                "id": "invoice_reject",
                "name": "Invoice Rejection & Notification",
                "description": (
                    "Reject a discrepant invoice and draft a supplier notification email."
                ),
                "tags": ["rejection", "email", "approval"],
            },
        ],
    }


async def agent_card(request: Request) -> JSONResponse:
    return JSONResponse(_agent_card())


def _extract_text(message: dict) -> str:
    parts = message.get("parts", []) if isinstance(message, dict) else []
    texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("kind") == "text"]
    return "\n".join(t for t in texts if t).strip()


async def jsonrpc(request: Request) -> JSONResponse:
    """Minimal A2A JSON-RPC endpoint — supports message/send synchronously."""
    if (err := _check_api_key(request)):
        return err
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        )

    rpc_id = payload.get("id")
    method = payload.get("method")

    if method != "message/send":
        return JSONResponse({
            "jsonrpc": "2.0", "id": rpc_id,
            "error": {"code": -32601, "message": f"Method not supported: {method}"},
        })

    params = payload.get("params", {}) or {}
    message = params.get("message", {}) or {}
    query = _extract_text(message)
    session_id = message.get("contextId") or message.get("taskId") or str(uuid.uuid4())

    logger.info("jsonrpc message/send session=%s query_len=%d", session_id, len(query))
    answer = await _run_agent(query, session_id)

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": answer}],
        },
    })


# ── App ─────────────────────────────────────────────────────────────────────────

routes = [
    Route("/health", health, methods=["GET"]),
    # A2A
    Route("/.well-known/agent-card.json", agent_card, methods=["GET"]),
    Route("/.well-known/agent.json", agent_card, methods=["GET"]),
    Route("/", jsonrpc, methods=["POST"]),
    # REST (for the MCP proxy)
    Route("/ask", ask, methods=["POST"]),
    Route("/billing/upload-pdf", billing_upload_pdf, methods=["POST"]),
    Route("/ratecard/upload", ratecard_upload, methods=["POST"]),
    Route("/staged/files", staged_files, methods=["GET"]),
    Route("/staged/validate-pdf", staged_validate_pdf, methods=["POST"]),
    Route("/staged/upload-ratecard", staged_upload_ratecard, methods=["POST"]),
    Route("/billing/reject", billing_reject, methods=["POST"]),
]

app = Starlette(routes=routes)


def main():
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info("=== aliyun-billing-validator-agent starting on %s:%d ===", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
