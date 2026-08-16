"""BillingValidatorAgent — LangGraph agent with tool calling via SAP AI Core.

Architecture:
  - MCP Server exposes one tool: ask_billing_agent(query)
  - LangGraph graph: agent → tools → agent → respond
  - Tools: upload_rate_card, upload_billing_pdf, validate_billing,
           query_billing_data, submit_for_approval
  - LLM: SAP AI Core → Claude (via gen_ai_hub)

SAP AI Core roles:
  1. Tool orchestration — Claude decides which tools to call and in what order
  2. Natural language response — Claude synthesises tool results into a reply
  (A third AI Core usage exists in the CAP backend's ai-matcher.js for semantic
   rate card matching — that runs independently and is not touched here.)
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, AsyncIterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage, get_buffer_string, trim_messages
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph, add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel
from typing_extensions import TypedDict

from gen_ai_hub.proxy.langchain.init_models import init_llm
from odata import ODataClient

logger = logging.getLogger(__name__)

ODATA_PAGE_TOP = int(os.getenv("ODATA_PAGE_TOP", "20"))
USE_MOCK_DATA  = os.getenv("USE_MOCK_DATA", "false").lower() in {"1", "true", "yes"}

# Module-level OData client (shared across tool calls in one agent instance)
_odata: ODataClient | None = None


def _get_odata() -> ODataClient:
    global _odata
    if _odata is None:
        _odata = ODataClient()
    return _odata


# ── Slim helpers ───────────────────────────────────────────────────────────────

_UPLOAD_KEYS   = {"ID", "fileName", "status", "approvalStatus", "createdAt", "rateCard_ID"}
_HEADER_KEYS   = {"vendorName", "invoiceNumber", "invoiceDate", "totalAmount", "currency"}
_VALRES_KEYS   = {"upload_ID", "overallStatus", "errorCount", "warningCount", "totalBilled", "totalExpected", "totalVariance", "summary"}
_FINDING_KEYS  = {"type", "severity", "field", "billedValue", "expectedValue", "variancePct", "explanation", "aiReasoning"}
_RATECARD_KEYS = {"ID", "name", "status", "validFrom", "validTo"}
_RCITEM_KEYS   = {"serviceCode", "serviceDesc", "unit", "unitPrice", "currency"}


def _slim_upload(u: dict) -> dict:
    out = {k: u[k] for k in _UPLOAD_KEYS if k in u}
    if h := u.get("header"):
        out["header"] = {k: h[k] for k in _HEADER_KEYS if k in h}
    if vr := u.get("validationResult"):
        slim_vr = {k: vr[k] for k in _VALRES_KEYS if k in vr}
        slim_vr["findings"] = [{k: f[k] for k in _FINDING_KEYS if k in f} for f in (vr.get("findings") or [])]
        out["validationResult"] = slim_vr
    return out


def _slim_ratecard(r: dict) -> dict:
    out = {k: r[k] for k in _RATECARD_KEYS if k in r}
    out["items"] = [{k: i[k] for k in _RCITEM_KEYS if k in i} for i in (r.get("items") or [])]
    return out


def _fmt(title: str, items: list) -> str:
    if not items:
        return f"## {title}\n(no records)\n"
    return f"## {title}\n```json\n{json.dumps(items, indent=2, ensure_ascii=False, default=str)}\n```\n"


# ── LangChain Tools ────────────────────────────────────────────────────────────


@tool
async def query_billing_data(question: str) -> str:
    """Query billing uploads, validation results and rate cards to answer questions
    about historical billing data, validation findings, and rate cards.

    Use this tool when the user asks about:
    - Billing upload status, amounts, vendor names
    - Validation results, errors, warnings, findings
    - Rate card details, pricing, validity periods
    - Historical comparisons or summaries

    Args:
        question: The user's question about billing data.
    """
    if USE_MOCK_DATA:
        return json.dumps({"message": "Mock mode: no real OData data available."})

    client = _get_odata()
    try:
        uploads, validations, ratecards = await asyncio.gather(
            client.fetch_billing_uploads(ODATA_PAGE_TOP),
            client.fetch_validation_results(ODATA_PAGE_TOP),
            client.fetch_rate_cards(ODATA_PAGE_TOP),
        )
        result = json.dumps({
            "billing_uploads":     [_slim_upload(u) for u in uploads],
            "validation_results":  [
                {k: v[k] for k in _VALRES_KEYS if k in v} | {
                    "findings": [{k: f[k] for k in _FINDING_KEYS if k in f} for f in (v.get("findings") or [])]
                }
                for v in validations
            ],
            "rate_cards": [_slim_ratecard(r) for r in ratecards],
        }, ensure_ascii=False, default=str)
        logger.info("query_billing_data counts: uploads=%d validations=%d ratecards=%d", len(uploads), len(validations), len(ratecards))
        return result
    except Exception as e:
        logger.warning("query_billing_data failed: %s", e)
        return json.dumps({"error": str(e)})


@tool
async def upload_rate_card(
    name: str,
    csv_base64: str,
    valid_from: str = "",
    valid_to: str = "",
    description: str = "",
) -> str:
    """Upload a Rate Card CSV file to the billing system.

    The CSV should contain service codes, descriptions, unit prices and currencies.
    The user must provide the CSV content encoded as base64.

    Args:
        name: Name for the rate card (e.g. "CEVA Air Freight HKG-TPE 2026").
        csv_base64: Base64-encoded CSV file content.
        valid_from: Validity start date in YYYY-MM-DD format (optional).
        valid_to: Validity end date in YYYY-MM-DD format (optional).
        description: Optional description for the rate card.
    """
    client = _get_odata()
    try:
        result = await client.upload_rate_card(
            name=name,
            csv_content=csv_base64,
            valid_from=valid_from or None,
            valid_to=valid_to or None,
            description=description,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("upload_rate_card failed: %s", e)
        return json.dumps({"error": str(e)})


@tool
async def upload_and_validate_billing_pdf(
    file_name: str,
    pdf_base64: str,
    rate_card_id: str,
) -> str:
    """Upload a billing invoice PDF, wait for OCR extraction, then run validation
    against the specified rate card.

    This tool handles the complete workflow:
    1. Upload PDF to SAP Document Intelligence for OCR extraction
    2. Poll until extraction is complete
    3. Run validation rules (calc check, price check, duplicate check)
    4. Return validation results with findings

    Args:
        file_name: Original filename of the PDF (e.g. "CEVA-HKG-TPE-2026-06.pdf").
        pdf_base64: Base64-encoded PDF file content.
        rate_card_id: UUID of the Rate Card to validate against.
    """
    client = _get_odata()
    try:
        # Step 1: Upload PDF
        upload_resp = await client.upload_billing_pdf(
            file_name=file_name,
            file_content=pdf_base64,
            rate_card_id=rate_card_id,
        )
        upload_id = upload_resp.get("uploadId")
        if not upload_id:
            return json.dumps({"error": "Upload failed: no uploadId returned", "detail": upload_resp})

        # Step 2: Poll extraction status
        for attempt in range(24):  # max 2 minutes (24 × 5s)
            await asyncio.sleep(5)
            status_resp = await client.get_extraction_status(upload_id)
            status = status_resp.get("status", "")
            logger.info("Extraction poll %d: uploadId=%s status=%s", attempt + 1, upload_id, status)
            if status == "extracted":
                break
            if status == "error":
                return json.dumps({"error": f"Extraction failed: {status_resp.get('message', '')}", "uploadId": upload_id})
        else:
            return json.dumps({"error": "Extraction timed out after 2 minutes", "uploadId": upload_id})

        # Step 3: Validate
        validation_resp = await client.validate_billing(upload_id)
        return json.dumps({
            "uploadId":     upload_id,
            "validation":   validation_resp,
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("upload_and_validate_billing_pdf failed: %s", e)
        return json.dumps({"error": str(e)})


@tool
async def submit_for_approval(
    upload_ids: list[str],
    approver_email: str,
) -> str:
    """Submit one or more validated billing uploads for approval via SAP Build
    Process Automation workflow.

    The approver will receive an email and can approve or reject the invoices
    in the SAP BPA portal.

    Args:
        upload_ids: List of BillingUpload UUIDs to submit for approval.
        approver_email: Email address of the approver.
    """
    client = _get_odata()
    try:
        result = await client.submit_for_approval(
            upload_ids=upload_ids,
            approver_email=approver_email,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("submit_for_approval failed: %s", e)
        return json.dumps({"error": str(e)})


TOOLS = [
    query_billing_data,
    upload_rate_card,
    upload_and_validate_billing_pdf,
    submit_for_approval,
]

# ── Agent types ────────────────────────────────────────────────────────────────


class TaskStatus(str, Enum):
    COMPLETED      = "completed"
    INPUT_REQUIRED = "input_required"
    ERROR          = "error"


@dataclass(frozen=True, slots=True)
class StreamResponse:
    is_task_complete:  bool
    require_user_input: bool
    content: str

    @classmethod
    def completed(cls, msg: str) -> "StreamResponse":
        return cls(True, False, msg)

    @classmethod
    def input_required(cls, msg: str) -> "StreamResponse":
        return cls(False, True, msg)

    @classmethod
    def error(cls, msg: str = "Unable to process request.") -> "StreamResponse":
        return cls(False, True, msg)

    @classmethod
    def working(cls, msg: str) -> "StreamResponse":
        return cls(False, False, msg)


class ResponseFormat(BaseModel):
    status:  TaskStatus = TaskStatus.COMPLETED
    message: str


class AgentState(TypedDict):
    messages:            Annotated[list[BaseMessage], add_messages]
    structured_response: ResponseFormat | None


# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are the SAP Billing Validator Assistant, integrated into QwenWork (千问办公).
You help users manage and validate 3PL logistics billing via natural language.

## What you can do

1. **Upload Rate Card** — Accept a CSV file, upload it to the billing system.
   Ask the user for the rate card name and validity dates if not provided.

2. **Upload & Validate Invoice** — Accept a billing PDF, run OCR extraction via
   SAP Document Intelligence, then cross-validate every line item against the
   rate card. Report findings (errors, warnings, price mismatches).

3. **Query Billing History** — Answer questions about past uploads, validation
   results, vendor amounts, error patterns, and rate card details.

4. **Submit for Approval** — Submit validated invoices to the SAP BPA approval
   workflow. Ask for the approver's email if not provided.

5. **Reject Invoice & Draft Notification Email** — When validation reveals a
   discrepancy, ask the user if they want to reject the invoice and notify the
   supplier. If confirmed, call `reject_invoice_and_draft_email` which will:
   - Submit the rejection and return an approval flow number
   - Generate a supplier email draft (NOT sent automatically — present it to
     the user for review)

## File handling — important

When the user refers to a billing document, invoice, or PDF **without providing
file content (no base64)**, do NOT ask them to upload it again. Instead:
1. Call `list_staged_files` to see what is available on the server.
2. Pick the most relevant file based on the user's description (vendor name,
   month, etc.).
3. Call `validate_staged_billing_pdf` with that file and the rate card ID.

When the user refers to a rate card CSV **without providing file content**:
1. Call `list_staged_files` to see what is available.
2. Call `upload_staged_rate_card` with the matching file.

This is intentional — files may be pre-loaded on the server for convenience.
Never expose or mention this mechanism to the user; treat it as seamless.

## Workflow

When a user uploads a PDF invoice and asks for validation:
1. Call upload_and_validate_billing_pdf with the file and rate card ID.
2. Present the validation result clearly: overall status, total billed vs expected,
   variance, and a summary of findings grouped by severity.

When a user uploads a CSV rate card:
1. Call upload_rate_card with the file content.
2. Confirm the number of items created.

When a validation result contains errors or overcharges:
1. Present the findings clearly.
2. Recommend rejection if the discrepancy is a rate mismatch.
3. Ask: "是否发起驳回并通知供应商？" (or in English if the user wrote in English).
4. If the user confirms, call `reject_invoice_and_draft_email` with the invoice
   number and a concise discrepancy description.
5. Present the returned approval flow number and email draft clearly.
   Always remind the user the email is a draft and has NOT been sent.

When a user asks about historical data:
1. Call query_billing_data to fetch live data.
2. Answer concisely with tables or bullet lists.

## Response style

- Use markdown tables for data summaries.
- Flag errors with ❌, warnings with ⚠️, passed items with ✅.
- Show amounts with currency (USD, TWD, etc.).
- Reply in the language the user used (Chinese ↔ Chinese, English ↔ English).
- Never fabricate data — only report what tool results contain.
- After completing a task, return status = completed. Do not ask unnecessary
  follow-up questions.
"""


# ── Agent class ────────────────────────────────────────────────────────────────


class BillingValidatorAgent:
    """LangGraph agent that orchestrates billing validation tools via SAP AI Core."""

    SUPPORTED_CONTENT_TYPES = frozenset({"TEXT", "TEXT/PLAIN"})

    def __init__(self) -> None:
        model_id = os.getenv("MODEL_ID", "anthropic--claude-4.6-sonnet")
        logger.info("Initialising LLM model_id=%s", model_id)
        self._tools        = TOOLS
        self._model        = init_llm(model_id, max_tokens=8192, top_p=None).bind_tools(self._tools)
        self._resp_model   = init_llm(model_id, max_tokens=512, top_p=None).with_structured_output(ResponseFormat)
        self._checkpointer = MemorySaver()
        self._graph: CompiledStateGraph | None = None
        self._build_graph()

    def _build_graph(self) -> None:
        model        = self._model
        tool_node    = ToolNode(self._tools)

        async def agent_node(state: AgentState) -> dict:
            has_tool_result = any(m.type == "tool" for m in state["messages"])

            # First turn with no prior tool results: force a query_billing_data call
            # to avoid Claude greeting instead of acting (tool_choice not supported on all backends)
            if not has_tool_result:
                last_human = next(
                    (m.content for m in reversed(state["messages"]) if m.type == "human"),
                    "",
                )
                is_file_upload = isinstance(last_human, str) and (
                    '"pdf_base64"' in last_human
                    or '"csv_base64"' in last_human
                    or '"action"' in last_human
                    or '"file_name"' in last_human
                )
                if not is_file_upload:
                    tool_result = await query_billing_data.ainvoke({"question": last_human})
                    augmented_human = (
                        f"{last_human}\n\n"
                        f"[System: query_billing_data tool already executed. Results below — "
                        f"summarise them in response to the user's question. Do not greet.]\n"
                        f"{tool_result}"
                    )
                    messages = [HumanMessage(content=augmented_human)]
                    response = await model.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *messages])
                    logger.info("agent_node forced-query response len=%d content_preview=%.200s",
                                len(str(response.content)), str(response.content)[:200])
                    return {"messages": [HumanMessage(content=last_human), response], "structured_response": None}

            messages = trim_messages(
                state["messages"],
                max_tokens=20_000,
                token_counter=lambda msgs: len(get_buffer_string(msgs)) // 4,
                strategy="last",
                start_on="human",
                include_system=False,
                allow_partial=False,
            )
            response = await model.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *messages])
            return {"messages": [response], "structured_response": None}

        async def respond_node(state: AgentState) -> dict:
            last_ai = ""
            for msg in reversed(state["messages"]):
                if msg.type == "ai" and msg.content:
                    last_ai = msg.content if isinstance(msg.content, str) else str(msg.content)
                    break
            conversation = "\n".join(
                f"[{m.type}]: {m.content}"
                for m in state["messages"]
                if m.content and m.type in ("human", "ai")
            )
            try:
                resp = await self._resp_model.ainvoke([
                    SystemMessage(content=(
                        "Classify the billing agent's last action:\n"
                        "- 'completed': summary or answer fully provided.\n"
                        "- 'input_required': agent asked a clarifying question.\n"
                        "- 'error': agent could not complete the task.\n"
                        "When in doubt, use 'completed'."
                    )),
                    HumanMessage(content=f"Conversation:\n{conversation}"),
                ])
                status = resp.status if isinstance(resp, ResponseFormat) else TaskStatus.COMPLETED
            except Exception:
                status = TaskStatus.COMPLETED
            return {"structured_response": ResponseFormat(status=status, message=last_ai or "Done.")}

        def should_continue(state: AgentState) -> str:
            last = state["messages"][-1]
            if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
                return "tools"
            return "respond"

        graph = StateGraph(AgentState)
        graph.add_node("agent",   agent_node)
        graph.add_node("tools",   tool_node)
        graph.add_node("respond", respond_node)
        graph.set_entry_point("agent")
        graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "respond": "respond"})
        graph.add_edge("tools",   "agent")
        graph.add_edge("respond", END)
        self._graph = graph.compile(checkpointer=self._checkpointer)

    async def astream(self, query: str, session_id: str) -> AsyncIterator[StreamResponse]:
        graph   = self._graph
        inputs  = {"messages": [("user", query)]}
        config  = {"configurable": {"thread_id": session_id}, "recursion_limit": 20}

        async for chunk in graph.astream(inputs, config, stream_mode="updates"):
            for node_name in chunk:
                if node_name == "agent":
                    yield StreamResponse.working("Analysing your request...")
                elif node_name == "tools":
                    yield StreamResponse.working("Calling billing service...")

        yield self._get_response(graph, config)

    def _get_response(self, graph: CompiledStateGraph, config: dict) -> StreamResponse:
        state    = graph.get_state(config)
        response = state.values.get("structured_response")
        if not isinstance(response, ResponseFormat):
            return StreamResponse.error("No valid response generated.")
        match response.status:
            case TaskStatus.COMPLETED:
                return StreamResponse.completed(response.message)
            case TaskStatus.INPUT_REQUIRED:
                return StreamResponse.input_required(response.message)
            case _:
                return StreamResponse.error(response.message)
