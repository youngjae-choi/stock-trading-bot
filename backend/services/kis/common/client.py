"""Shared KIS client with token caching and resilient request wrappers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Literal, Optional

import httpx

from ....config import mask_secret, settings
from ....utils import kis_rate_limiter, retry_on_kis_error

logger = logging.getLogger("KISClient")


class KISClient:
    def __init__(self):
        self.base_url = settings.KIS_URL
        self.app_key = settings.KIS_APP_KEY
        self.app_secret = settings.KIS_APP_SECRET
        self.token: Optional[str] = None
        self.token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._token_retry_waits = [0.6, 1.2, 2.4]

    def _is_virtual_trading(self) -> bool:
        return "openapivts" in self.base_url.lower()

    def _order_env(self) -> Literal["demo", "real"]:
        return "demo" if self._is_virtual_trading() else "real"

    def _token_is_valid(self, leeway_seconds: int = 180) -> bool:
        return bool(self.token) and self.token_expires_at > time.time() + leeway_seconds

    def _build_kis_error_message(self, response: httpx.Response, context: str) -> str:
        raw_text = response.text.strip()
        msg_cd = ""
        msg1 = ""
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            msg_cd = str(payload.get("msg_cd") or "").strip()
            msg1 = str(payload.get("msg1") or "").strip()

        details = " ".join(part for part in [msg_cd, msg1] if part).strip() or raw_text
        if not details:
            details = f"HTTP {response.status_code} from KIS API"
        return f"{context}: {details}"

    async def _issue_token_once(self) -> str:
        logger.info("START: KIS OAuth Token Issuance")
        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body)
        if response.status_code != 200:
            raise Exception(self._build_kis_error_message(response, "KIS Token Error"))

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise Exception("KIS Token Error: access_token missing in response")

        expires_in = int(payload.get("expires_in", 86400))
        self.token = token
        self.token_expires_at = time.time() + max(60, expires_in)
        logger.info(
            "SUCCESS: KIS OAuth Token Issued (Masked: %s, expires_in=%ss)",
            mask_secret(self.token),
            expires_in,
        )
        return token

    async def get_token(self) -> str:
        if self._token_is_valid():
            return str(self.token)

        async with self._token_lock:
            if self._token_is_valid():
                return str(self.token)

            last_error: Exception | None = None
            for idx, wait_seconds in enumerate(self._token_retry_waits, start=1):
                try:
                    return await self._issue_token_once()
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "RETRY: token issuance failed (%s/%s) reason=%s",
                        idx,
                        len(self._token_retry_waits),
                        str(exc),
                    )
                    if idx < len(self._token_retry_waits):
                        await asyncio.sleep(wait_seconds)

            raise Exception(
                "KIS 토큰 발급 실패: 잠시 후 다시 시도하거나 API 키/시크릿, 호출 빈도 제한을 확인하세요. "
                f"원인={last_error}"
            )

    @retry_on_kis_error()
    async def request(
        self,
        *,
        method: Literal["GET", "POST"],
        path: str,
        tr_id: str,
        params: Dict[str, Any] | None = None,
        body: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        await kis_rate_limiter.wait()
        token = await self.get_token()

        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient(timeout=12.0) as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            else:
                response = await client.post(url, headers=headers, json=body)

        if response.status_code == 401:
            # token mismatch/expiration case: one forced refresh + single retry
            logger.warning("WARN: token unauthorized. reissuing token and retrying once.")
            async with self._token_lock:
                self.token = None
                self.token_expires_at = 0
            token = await self.get_token()
            headers["authorization"] = f"Bearer {token}"
            async with httpx.AsyncClient(timeout=12.0) as client:
                if method == "GET":
                    response = await client.get(url, headers=headers, params=params)
                else:
                    response = await client.post(url, headers=headers, json=body)

        if response.status_code != 200:
            raise Exception(self._build_kis_error_message(response, f"KIS API Error ({path})"))

        return response.json()


kis_client = KISClient()
