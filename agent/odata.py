"""OData client for billing-validator-srv.

Handles XSUAA client_credentials auth and all HTTP calls to CAP OData actions.
Credentials are read from VCAP_SERVICES on BTP CF, or from env vars for local dev.
"""

import asyncio
import base64
import logging
import os
from typing import Any
from urllib.parse import quote

import httpx
from cfenv import AppEnv

logger = logging.getLogger(__name__)


class ODataClient:
    """Async OData client with XSUAA token caching."""

    _token_cache: dict[str, Any] = {}

    def __init__(self) -> None:
        self.srv_url = os.getenv("SRV_URL", "").rstrip("/")
        creds = self._read_xsuaa_creds()
        self.token_url    = creds.get("url", "").rstrip("/") + "/oauth/token"
        self.client_id    = creds.get("clientid", "")
        self.client_secret = creds.get("clientsecret", "")

    @staticmethod
    def _read_xsuaa_creds() -> dict[str, Any]:
        if os.getenv("VCAP_SERVICES"):
            try:
                env = AppEnv()
                svc = env.get_service(label="xsuaa") or env.get_service(name="Coach_mini_Poc_xsuaa")
                if svc:
                    return svc.credentials
            except Exception:
                logger.warning("Failed to read xsuaa from VCAP_SERVICES; falling back to env vars")
        return {
            "url":          os.getenv("XSUAA_URL", ""),
            "clientid":     os.getenv("XSUAA_CLIENT_ID", ""),
            "clientsecret": os.getenv("XSUAA_CLIENT_SECRET", ""),
        }

    async def _get_token(self) -> str:
        cached = self._token_cache.get("token")
        expiry = self._token_cache.get("expiry", 0)
        now = asyncio.get_event_loop().time()
        if cached and now < expiry - 60:
            return cached
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self.token_url,
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()
        token = payload["access_token"]
        self._token_cache["token"] = token
        self._token_cache["expiry"] = now + int(payload.get("expires_in", 3600))
        return token

    def _url(self, path: str) -> str:
        if not self.srv_url:
            raise RuntimeError("SRV_URL is not configured")
        return f"{self.srv_url}{path}"

    async def _headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        url = self._url(path)
        if params:
            parts = [quote(k, safe="$") + "=" + quote(v, safe="',") for k, v in params.items()]
            url += "?" + "&".join(parts)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=await self._headers())
            resp.raise_for_status()
            return resp.json()

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = await self._headers()
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self._url(path), json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # ── Read operations ────────────────────────────────────────────────────────

    async def fetch_billing_uploads(self, top: int = 20) -> list[dict[str, Any]]:
        data = await self.get(
            "/odata/v4/billing/BillingUpload",
            params={
                "$top": str(top),
                "$orderby": "createdAt desc",
                "$expand": "header($expand=lineItems),validationResult($expand=findings)",
            },
        )
        return data.get("value", [])

    async def fetch_validation_results(self, top: int = 20) -> list[dict[str, Any]]:
        data = await self.get(
            "/odata/v4/billing/ValidationResult",
            params={
                "$top": str(top),
                "$orderby": "createdAt desc",
                "$expand": "findings",
            },
        )
        return data.get("value", [])

    async def fetch_rate_cards(self, top: int = 20) -> list[dict[str, Any]]:
        data = await self.get(
            "/odata/v4/billing/RateCard",
            params={
                "$top": str(top),
                "$filter": "status eq 'active'",
                "$expand": "items",
            },
        )
        return data.get("value", [])

    async def get_extraction_status(self, upload_id: str) -> dict[str, Any]:
        data = await self.get(f"/odata/v4/billing/getExtractionStatus(uploadId={upload_id})")
        return data

    # ── Write operations ───────────────────────────────────────────────────────

    async def upload_rate_card(
        self,
        name: str,
        csv_content: str,      # base64-encoded CSV
        valid_from: str | None = None,
        valid_to: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        return await self.post(
            "/odata/v4/billing/uploadRateCard",
            {
                "name": name,
                "csvContent": csv_content,
                "validFrom": valid_from,
                "validTo": valid_to,
                "description": description,
            },
        )

    async def upload_billing_pdf(
        self,
        file_name: str,
        file_content: str,     # base64-encoded PDF
        rate_card_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.post(
            "/odata/v4/billing/uploadBillingPDF",
            {
                "fileName": file_name,
                "fileContent": file_content,
                "rateCardId": rate_card_id,
            },
        )

    async def validate_billing(self, upload_id: str) -> dict[str, Any]:
        return await self.post(
            "/odata/v4/billing/validateBilling",
            {"uploadId": upload_id},
        )

    async def submit_for_approval(
        self,
        upload_ids: list[str],
        approver_email: str,
    ) -> dict[str, Any]:
        return await self.post(
            "/odata/v4/billing/submitForApproval",
            {"uploadIds": upload_ids, "approverEmail": approver_email},
        )

    async def confirm_billing(
        self,
        upload_id: str,
        overrides: str = "{}",
    ) -> dict[str, Any]:
        return await self.post(
            "/odata/v4/billing/confirmBilling",
            {"uploadId": upload_id, "overrides": overrides},
        )
