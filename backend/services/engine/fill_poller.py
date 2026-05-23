"""S7.5 Fill Poller for confirming KIS order fills."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..kis.domestic.service import get_daily_order_inquiry

logger = logging.getLogger("FillPoller")

_POLL_INTERVAL = 60
_MAX_AGE_HOURS = 8


def _now_kst() -> datetime:
    """현재 Asia/Seoul 기준 시간을 반환한다."""
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _to_int(value: Any) -> int:
    """KIS 숫자 문자열을 정수로 변환한다.

    Args:
        value: 쉼표가 포함될 수 있는 KIS 수량 필드.
    """
    try:
        return int(float(str(value).replace(",", "").strip() or "0"))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    """KIS 숫자 문자열을 실수로 변환한다.

    Args:
        value: 쉼표가 포함될 수 있는 KIS 금액 필드.
    """
    try:
        return float(str(value).replace(",", "").strip() or "0")
    except (TypeError, ValueError):
        return 0.0


def _kis_value(data: dict[str, Any], *keys: str) -> Any:
    """대소문자가 섞인 KIS 응답에서 첫 번째 유효 값을 읽는다.

    Args:
        data: KIS 주문/체결 응답 행.
        keys: 조회할 필드명 후보.
    """
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
        lower_value = data.get(key.lower())
        if lower_value not in (None, ""):
            return lower_value
        upper_value = data.get(key.upper())
        if upper_value not in (None, ""):
            return upper_value
    return ""


def _ensure_fills_table() -> None:
    """FillPoller가 사용하는 fills 테이블을 새 DB에서도 보장한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_runs (
                id TEXT PRIMARY KEY,
                strategy_id TEXT,
                started_at TEXT,
                finished_at TEXT,
                status TEXT,
                metrics_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                strategy_run_id TEXT REFERENCES strategy_runs(id) ON DELETE SET NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                signal_type TEXT NOT NULL DEFAULT 'entry',
                confidence REAL,
                price REAL,
                reason_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                strategy_run_id TEXT REFERENCES strategy_runs(id) ON DELETE SET NULL,
                signal_id TEXT REFERENCES signals(id) ON DELETE SET NULL,
                broker_order_id TEXT NOT NULL DEFAULT '',
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL DEFAULT 'market',
                quantity REAL NOT NULL,
                limit_price REAL,
                status TEXT NOT NULL DEFAULT 'created',
                requested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                response_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
                id TEXT PRIMARY KEY,
                order_id TEXT REFERENCES orders(id) ON DELETE SET NULL,
                broker_fill_id TEXT NOT NULL DEFAULT '',
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL NOT NULL DEFAULT 0,
                tax REAL NOT NULL DEFAULT 0,
                filled_at TEXT NOT NULL,
                raw_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )


def _ensure_poll_tables() -> None:
    """체결 폴링에 필요한 로컬 주문/체결 테이블을 준비한다."""
    from .order_executor import _ensure_orders_table

    _ensure_orders_table()
    _ensure_fills_table()


def _get_submitted_orders(trade_date: str) -> list[dict[str, Any]]:
    """오늘 submitted 상태 주문 중 KIS 주문번호가 있는 주문만 반환한다.

    Args:
        trade_date: YYYY-MM-DD 형식의 거래일.
    """
    _ensure_poll_tables()
    cutoff = (_now_kst() - timedelta(hours=_MAX_AGE_HOURS)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM trading_orders
            WHERE trade_date = ?
              AND status = 'submitted'
              AND created_at >= ?
            """,
            (trade_date, cutoff),
        ).fetchall()
    return [dict(row) for row in rows]


def _is_already_filled(order_id: str) -> bool:
    """fills 테이블에 같은 order_id의 체결 기록이 있는지 확인한다.

    Args:
        order_id: trading_orders.id 값.
    """
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM fills WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
    return row is not None


def _mark_order_filled(order: dict[str, Any], kis_fill_data: dict[str, Any]) -> None:
    """trading_orders 상태를 filled로 바꾸고 fills 레코드를 추가한다.

    Args:
        order: 로컬 trading_orders 행.
        kis_fill_data: KIS 일별 주문체결 조회의 체결 행.
    """
    now = _now_kst().isoformat()
    order_id = str(order.get("id") or "")
    symbol = str(_kis_value(kis_fill_data, "pdno") or order.get("symbol") or "")
    qty = _to_int(_kis_value(kis_fill_data, "tot_ccld_qty", "ccld_qty") or order.get("qty"))
    order_qty = _to_int(order.get("qty"))
    if order_qty > 0 and qty > order_qty:
        logger.warning(
            "WARN: [FillPoller] fill quantity capped order_id=%s symbol=%s raw_qty=%d order_qty=%d source=%s",
            order_id,
            symbol,
            qty,
            order_qty,
            kis_fill_data.get("_source") or "kis",
        )
        qty = order_qty
    price = _to_float(_kis_value(kis_fill_data, "avg_prvs", "avg_prc", "ord_unpr") or order.get("price"))
    side_code = str(_kis_value(kis_fill_data, "sll_buy_dvsn_cd") or "")
    side = "buy" if side_code == "02" else "sell" if side_code == "01" else str(order.get("side") or "")
    broker_fill_id = str(_kis_value(kis_fill_data, "odno") or order.get("kis_order_no") or "")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO orders
                (id, broker_order_id, symbol, side, order_type, quantity, limit_price,
                 status, requested_at, updated_at, request_json, response_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'filled', ?, ?, '{}', ?)
            """,
            (
                order_id,
                broker_fill_id,
                symbol,
                side,
                str(order.get("order_type") or "limit"),
                qty,
                price,
                str(order.get("created_at") or now),
                now,
                json.dumps(kis_fill_data, ensure_ascii=False),
            ),
        )
        conn.execute(
            "UPDATE trading_orders SET status = 'filled', price = ? WHERE id = ?",
            (price, order_id),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO fills
                (id, order_id, broker_fill_id, symbol, side, quantity, price,
                 fee, tax, filled_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                order_id,
                broker_fill_id,
                symbol,
                side,
                qty,
                price,
                now,
                json.dumps(kis_fill_data, ensure_ascii=False),
            ),
        )


async def _fetch_symbol_output2(symbol: str, date_str: str, order_no: str) -> dict[str, Any]:
    """종목+날짜+주문번호 지정 KIS output2 조회 (모의투자 output1 미지원 환경 대응).

    Args:
        symbol: 종목코드 (PDNO).
        date_str: YYYYMMDD 형식 날짜.
        order_no: KIS 주문번호 (ODNO).
    Returns:
        KIS output2 dict (tot_ccld_qty, tot_ccld_amt, pchs_avg_pric 등).
    """
    from ..kis.common.client import kis_client
    from ...config import settings

    resp = await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
        tr_id="VTTC8001R" if "openapivts" in kis_client.base_url.lower() else "TTTC8001R",
        params={
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "INQR_STRT_DT": date_str,
            "INQR_END_DT": date_str,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": symbol,
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": order_no,
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        },
    )
    output2 = resp.get("output2") or {}
    if isinstance(output2, list):
        for item in output2:
            if isinstance(item, dict) and str(_kis_value(item, "odno")).strip() == order_no:
                return item
        return {}
    if isinstance(output2, dict):
        output_order_no = str(_kis_value(output2, "odno")).strip()
        if output_order_no and output_order_no != order_no:
            return {}
        return output2
    return {}


def _make_output2_fill_data(order: dict[str, Any], out2: dict[str, Any]) -> dict[str, Any]:
    """output2 결과를 _mark_order_filled 호환 형식으로 변환한다.

    buy limit 주문: DB 주문가(order.price) 사용.
    sell/market 주문: output2.pchs_avg_pric 또는 tot_ccld_amt/tot_ccld_qty 사용.
    """
    fill_qty = _to_int(out2.get("tot_ccld_qty") or order.get("qty"))
    order_qty = _to_int(order.get("qty"))
    if order_qty > 0:
        fill_qty = min(fill_qty, order_qty)
    side = str(order.get("side") or "")
    order_price = _to_float(order.get("price") or "0")

    if side == "buy" and order_price > 0:
        fill_price = order_price
    else:
        fill_price = _to_float(out2.get("pchs_avg_pric") or "0")
        if fill_price <= 0:
            ccld_amt = _to_float(out2.get("tot_ccld_amt") or "0")
            fill_price = ccld_amt / fill_qty if fill_qty > 0 else 0.0

    # _mark_order_filled 가 읽는 output1 필드명으로 매핑
    sll_buy_dvsn_cd = "02" if side == "buy" else "01" if side == "sell" else ""
    return {
        "odno": str(order.get("kis_order_no") or ""),
        "pdno": str(order.get("symbol") or ""),
        "tot_ccld_qty": str(fill_qty),
        "ccld_qty": str(fill_qty),
        "avg_prvs": str(fill_price),
        "sll_buy_dvsn_cd": sll_buy_dvsn_cd,
        "_source": "output2_fallback",
    }


def _notify_buy_fill(order: dict[str, Any], kis_data: dict[str, Any], ccld_qty: int) -> None:
    """매수 체결 성공을 텔레그램으로 비동기 알림 예약한다.

    Args:
        order: 로컬 trading_orders 행.
        kis_data: KIS 체결 데이터 또는 output2 호환 변환 데이터.
        ccld_qty: 확정 체결 수량.
    """
    if str(order.get("side", "")) != "buy":
        return
    try:
        from ..alert_service import send_telegram_alert

        symbol = str(_kis_value(kis_data, "pdno") or order.get("symbol") or "")
        price = _to_float(_kis_value(kis_data, "avg_prvs", "avg_prc") or order.get("price"))
        total = round(price * ccld_qty)
        fill_date = _now_kst().strftime("%Y-%m-%d %H:%M")
        asyncio.create_task(
            send_telegram_alert(
                "[매매봇] 매수 체결 ✅",
                f"종목: {symbol}\n"
                f"수량: {ccld_qty:,}주\n"
                f"체결가: {price:,.0f}원\n"
                f"체결금액: {total:,}원\n"
                f"날짜: {fill_date}",
            )
        )
        logger.info(
            "INFO: [FillPoller] buy fill telegram alert scheduled symbol=%s qty=%d price=%.2f",
            symbol,
            ccld_qty,
            price,
        )
    except Exception as exc:
        logger.warning("WARN: [FillPoller] 매수 텔레그램 알림 실패 reason=%s", exc)


async def poll_once(trade_date: str) -> dict[str, Any]:
    """KIS 체결 내역을 1회 조회해 submitted 주문 상태를 갱신한다.

    1단계: output1 기반 조회 (실거래 환경 — 개별 주문 행 포함).
    2단계: output1이 비어있으면 종목별 output2 폴백 (모의투자 환경 대응).

    Args:
        trade_date: YYYY-MM-DD 형식의 거래일.
    """
    logger.info("START: [FillPoller] poll_once trade_date=%s", trade_date)
    submitted = _get_submitted_orders(trade_date)
    if not submitted:
        logger.info("SUCCESS: [FillPoller] submitted 주문 없음")
        return {"filled": 0, "unchanged": 0}

    date_str = trade_date.replace("-", "")

    # ── 1단계: output1 조회 ────────────────────────────────────────────
    try:
        response = await get_daily_order_inquiry(date_str, side="all")
    except Exception as exc:
        logger.warning("WARN: [FillPoller] KIS 체결 조회 실패 error=%s", exc)
        return {"filled": 0, "unchanged": len(submitted), "error": str(exc)}

    kis_orders = response.get("output1", [])
    if isinstance(kis_orders, dict):
        kis_orders = [kis_orders]
    if not isinstance(kis_orders, list):
        kis_orders = []

    kis_map: dict[str, dict[str, Any]] = {}
    for item in kis_orders:
        if not isinstance(item, dict):
            continue
        odno = str(_kis_value(item, "odno")).strip()
        if odno:
            kis_map[odno] = item

    filled_count = 0
    unmatched: list[dict[str, Any]] = []

    for order in submitted:
        order_id = str(order.get("id") or "")
        kis_order_no = str(order.get("kis_order_no") or "").strip()
        if not order_id:
            continue

        kis_data = kis_map.get(kis_order_no)
        if not kis_data:
            unmatched.append(order)
            continue

        ccld_qty = _to_int(_kis_value(kis_data, "tot_ccld_qty", "ccld_qty"))
        ord_qty = _to_int(_kis_value(kis_data, "ord_qty") or order.get("qty"))
        rmn_qty = _to_int(_kis_value(kis_data, "rmn_qty"))
        is_fully_filled = ccld_qty > 0 and (ccld_qty >= ord_qty or rmn_qty == 0)
        if not is_fully_filled or _is_already_filled(order_id):
            continue

        _mark_order_filled(order, kis_data)
        _notify_buy_fill(order, kis_data, ccld_qty)
        filled_count += 1
        logger.info(
            "SUCCESS: [FillPoller] output1 filled order_id=%s symbol=%s qty=%d price=%.2f",
            order_id,
            _kis_value(kis_data, "pdno") or order.get("symbol"),
            ccld_qty,
            _to_float(_kis_value(kis_data, "avg_prvs", "avg_prc") or order.get("price")),
        )

    # ── 2단계: output2 폴백 (모의투자 — output1 항상 비어있음) ────────────
    if unmatched:
        logger.info(
            "INFO: [FillPoller] output1 미매칭 %d건 → output2 폴백 시도",
            len(unmatched),
        )
        for order in unmatched:
            order_id = str(order.get("id") or "")
            symbol = str(order.get("symbol") or "")
            kis_order_no = str(order.get("kis_order_no") or "").strip()
            if not order_id or not symbol or _is_already_filled(order_id):
                continue
            if not kis_order_no:
                logger.warning(
                    "WARN: [FillPoller] output2 폴백 건너뜀 symbol=%s order_id=%s reason=missing_kis_order_no",
                    symbol,
                    order_id,
                )
                continue
            try:
                await asyncio.sleep(0.12)  # KIS rate limit 여유
                out2 = await _fetch_symbol_output2(symbol, date_str, kis_order_no)
                ccld_qty = _to_int(out2.get("tot_ccld_qty") or "0")
                if ccld_qty == 0:
                    logger.info(
                        "INFO: [FillPoller] output2 미체결 symbol=%s order_no=%s tot_ccld_qty=0",
                        symbol,
                        kis_order_no,
                    )
                    continue

                kis_data = _make_output2_fill_data(order, out2)
                _mark_order_filled(order, kis_data)
                _notify_buy_fill(order, kis_data, _to_int(kis_data.get("tot_ccld_qty") or "0"))
                filled_count += 1
                logger.info(
                    "SUCCESS: [FillPoller] output2 filled order_id=%s symbol=%s qty=%d price=%.2f",
                    order_id,
                    symbol,
                    _to_int(kis_data.get("tot_ccld_qty") or "0"),
                    _to_float(kis_data.get("avg_prvs") or "0"),
                )
            except Exception as exc:
                logger.warning(
                    "WARN: [FillPoller] output2 폴백 실패 symbol=%s error=%s",
                    symbol,
                    exc,
                )

    unchanged = len(submitted) - filled_count
    logger.info(
        "SUCCESS: [FillPoller] poll_once 완료 filled=%d unchanged=%d (output2_fallback=%s)",
        filled_count,
        unchanged,
        bool(unmatched),
    )
    return {"filled": filled_count, "unchanged": unchanged, "output2_fallback": bool(unmatched)}


class FillPoller:
    """주기적으로 KIS 체결 조회를 실행하는 백그라운드 서비스."""

    def __init__(self) -> None:
        """백그라운드 태스크 상태를 초기화한다."""
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self, trade_date: str) -> None:
        """폴링 루프를 백그라운드 태스크로 시작한다.

        Args:
            trade_date: YYYY-MM-DD 형식의 거래일.
        """
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(trade_date))
        logger.info("START: [FillPoller] 시작 trade_date=%s interval=%ds", trade_date, _POLL_INTERVAL)

    def stop(self) -> None:
        """폴링 루프를 정지하고 실행 중인 태스크를 취소한다."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.info("SUCCESS: [FillPoller] 정지")

    async def _loop(self, trade_date: str) -> None:
        """정지 요청 전까지 일정 주기로 poll_once를 반복한다.

        Args:
            trade_date: YYYY-MM-DD 형식의 거래일.
        """
        while self._running:
            try:
                await poll_once(trade_date)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("FAIL: [FillPoller] poll_once 오류 error=%s", exc)
            await asyncio.sleep(_POLL_INTERVAL)


fill_poller = FillPoller()
