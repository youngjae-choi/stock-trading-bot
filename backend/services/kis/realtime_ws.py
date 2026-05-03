"""KIS realtime websocket manager with in-memory execution cache."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable

import httpx
import websockets

from ...config import settings
from .common.client import kis_client

logger = logging.getLogger("KISRealtimeWS")


class RealtimeWSManager:
    """Singleton-style manager for KIS realtime websocket sessions."""

    def __init__(self):
        self._cache: deque[dict[str, Any]] = deque(maxlen=200)
        self._symbols: list[str] = []
        self._runner_task: asyncio.Task | None = None
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._stop_event = asyncio.Event()
        self._tick_callbacks: list[Callable[[dict[str, Any]], Awaitable[None]]] = []
        self.is_connected: bool = False

    async def start(self, symbols: list[str]) -> None:
        safe_symbols = [str(s).strip() for s in symbols if str(s).strip()]
        if not safe_symbols:
            raise ValueError("symbols is required")

        unique_symbols = list(dict.fromkeys(safe_symbols))
        if self._runner_task and not self._runner_task.done():
            await self.stop()

        self._symbols = unique_symbols
        self._stop_event = asyncio.Event()
        self._runner_task = asyncio.create_task(self._run(), name="kis-realtime-ws")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._runner_task and not self._runner_task.done():
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        self.is_connected = False

    def get_latest(self, n: int = 50) -> list[dict[str, Any]]:
        if n <= 0:
            n = 1
        n = min(n, 200)
        return list(self._cache)[-n:]

    def register_tick_callback(self, cb: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Register an async callback that receives parsed tick payloads.

        Args:
            cb: Async callable invoked for every parsed symbol tick.
        """
        if cb not in self._tick_callbacks:
            self._tick_callbacks.append(cb)
            logger.info("SUCCESS: realtime tick callback registered count=%d", len(self._tick_callbacks))

    def unregister_tick_callback(self, cb: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Unregister a previously registered async tick callback.

        Args:
            cb: Async callable to remove.
        """
        before = len(self._tick_callbacks)
        self._tick_callbacks = [callback for callback in self._tick_callbacks if callback != cb]
        if len(self._tick_callbacks) != before:
            logger.info("SUCCESS: realtime tick callback unregistered count=%d", len(self._tick_callbacks))

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                approval_key = await self._issue_approval_key()
                ws_url = self._resolve_ws_url()
                logger.info("START: KIS realtime WS connect url=%s symbols=%s", ws_url, len(self._symbols))
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self._ws = ws
                    self.is_connected = True
                    for symbol in self._symbols:
                        subscribe_message = self._build_subscribe_message(approval_key=approval_key, symbol=symbol)
                        await ws.send(json.dumps(subscribe_message))
                        logger.info("SUCCESS: realtime subscribe sent tr_id=H0STCNT0 symbol=%s", symbol)

                    async for message in ws:
                        if self._stop_event.is_set():
                            break
                        await self._ingest_message(message)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.is_connected = False
                logger.error("FAIL: realtime websocket loop - %s", str(exc))
                if self._stop_event.is_set():
                    break
                await asyncio.sleep(2.0)
            finally:
                self.is_connected = False
                self._ws = None

    async def _ingest_message(self, message: Any) -> None:
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="ignore")
        raw = str(message)
        entry: dict[str, Any] = {
            "received_at": time.time(),
            "raw": raw,
        }

        if raw.startswith("{"):
            try:
                entry["json"] = json.loads(raw)
                header = entry["json"].get("header") if isinstance(entry["json"], dict) else None
                tr_id = ""
                if isinstance(header, dict):
                    tr_id = str(header.get("tr_id") or "")
                if tr_id == "PINGPONG" and self._ws is not None:
                    # KIS app-level ping 메시지는 동일 payload로 응답해야 연결이 유지된다.
                    await self._ws.send(raw)
                    entry["event"] = "PINGPONG"
                    entry["pong_sent"] = True
                    logger.info("SUCCESS: realtime PINGPONG handled")
                elif tr_id:
                    entry["tr_id"] = tr_id
                    logger.info("INFO: realtime control message tr_id=%s", tr_id)
            except Exception:
                pass
        elif "|" in raw:
            parts = raw.split("|", 3)
            if len(parts) >= 4:
                entry["tr_id"] = parts[1]
                entry["count"] = parts[2]
                body = parts[3]
                fields = body.split("^") if body else []
                if fields:
                    entry["symbol"] = fields[0]
                    if len(fields) > 2:
                        entry["price"] = fields[2]
                    if len(fields) > 12:
                        entry["trade_time"] = fields[1]
                        entry["trade_volume"] = fields[12]
                entry["fields"] = fields

        self._cache.append(entry)
        if entry.get("symbol") and self._tick_callbacks:
            tick = {
                "symbol": entry.get("symbol"),
                "price": entry.get("price"),
                "volume": entry.get("trade_volume"),
                "time": entry.get("trade_time"),
                "fields": entry.get("fields", []),
            }
            for cb in list(self._tick_callbacks):
                try:
                    await cb(tick)
                except Exception as exc:
                    logger.error("FAIL: tick callback error — %s", exc)

    async def _issue_approval_key(self) -> str:
        url = f"{kis_client.base_url}/oauth2/Approval"
        body = {
            "grant_type": "client_credentials",
            "appkey": settings.KIS_APP_KEY,
            "secretkey": settings.KIS_APP_SECRET,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body)

        if response.status_code != 200:
            raise Exception(f"KIS approval key error: {response.status_code} {response.text}")

        payload = response.json()
        approval_key = payload.get("approval_key")
        if not approval_key:
            raise Exception("KIS approval key missing")
        return str(approval_key)

    def _resolve_ws_url(self) -> str:
        is_demo = "openapivts" in kis_client.base_url.lower()
        if is_demo:
            return "ws://ops.koreainvestment.com:31000"
        return "ws://ops.koreainvestment.com:21000"

    def _build_subscribe_message(self, *, approval_key: str, symbol: str) -> dict[str, Any]:
        return {
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": "1",
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": "H0STCNT0",
                    "tr_key": symbol,
                }
            },
        }


realtime_ws_manager = RealtimeWSManager()
