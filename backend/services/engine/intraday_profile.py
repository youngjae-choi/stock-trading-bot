"""장중 유입 종목 Risk Profile 휴리스틱 배정 + 장중 선별 이력(intraday_plan_events).

배경: 아침 S5 Daily Plan은 종목별 Risk Profile을 LLM이 배정하지만, 장중 유입 종목
(모멘텀 스캐너·장중 재선별)은 plan 배정이 없어 전부 기본 MID_VOL로 박혔다.
이 모듈은 결정적 휴리스틱(LLM 금지 — 토큰/지연)으로 프로파일을 배정하고,
재선별·스캔 유입의 시점/레짐/배정 결과를 intraday_plan_events에 이력으로 남긴다.

프로파일 사이징(profile-v1.0): LOW_VOL 15% / MID_VOL 12% / HIGH_VOL 8% / THEME_SPIKE 5%.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("IntradayProfile")

# 파생형 ETF/ETN — 변동성 큼 → HIGH_VOL(8%)
_DERIVATIVE_KEYWORDS = ("레버리지", "인버스", "2X", "2x")
# 안정형 상품 키워드 → LOW_VOL(15%)
_STABLE_KEYWORDS = ("채권", "혼합", "배당", "단기채")

# 급등/테마 과열 임계 — risk_off 레짐에서는 보수화(THEME_SPIKE 5%가 가장 작은 사이징)
_SPIKE_CHANGE_RATE_PCT = 12.0
_SPIKE_CHANGE_RATE_PCT_RISK_OFF = 8.0
_SPIKE_VOLUME_SURGE = 500.0


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def classify_profile(candidate: dict[str, Any], regime: str | None) -> tuple[str, str]:
    """장중 유입 종목의 Risk Profile 휴리스틱 배정. returns (profile, reason).

    결정적 규칙(LLM 호출 없음):
      a) 종목명에 레버리지/인버스/2X → HIGH_VOL (파생형 ETF/ETN)
      b) change_rate ≥ 12% 또는 volume_surge ≥ 500 → THEME_SPIKE (급등/테마 과열)
         단 regime == risk_off 이면 임계 완화(≥8%) — 보수화 방향(사이징 5%)만
      c) 종목명에 안정 키워드(채권/혼합/배당/단기채) → LOW_VOL
      d) 기본 → MID_VOL
    reason 문자열에 레짐 반영 여부를 명시한다.

    Args:
        candidate: 후보 dict (name, change_rate, volume_surge 사용 — 없으면 0 처리).
        regime: 현재 레짐 (risk_on/neutral/risk_off/volatile 등, None 허용).
    """
    name = str(candidate.get("name") or "")
    change_rate = _to_float(candidate.get("change_rate"))
    volume_surge = _to_float(candidate.get("volume_surge"))
    regime_norm = str(regime or "").strip().lower()

    spike_threshold = _SPIKE_CHANGE_RATE_PCT
    regime_note = f"regime={regime_norm or 'unknown'}"
    if regime_norm == "risk_off":
        spike_threshold = _SPIKE_CHANGE_RATE_PCT_RISK_OFF
        regime_note += f", risk_off 보수화(급등 임계 {_SPIKE_CHANGE_RATE_PCT:.0f}%→{spike_threshold:.0f}%)"

    if any(k in name for k in _DERIVATIVE_KEYWORDS):
        return "HIGH_VOL", f"파생형 ETF/ETN ({regime_note})"
    if change_rate >= spike_threshold or volume_surge >= _SPIKE_VOLUME_SURGE:
        return (
            "THEME_SPIKE",
            f"급등/테마 과열 change={change_rate:.1f}% surge={volume_surge:.0f} ({regime_note})",
        )
    if any(k in name for k in _STABLE_KEYWORDS):
        return "LOW_VOL", f"안정형 상품 키워드 ({regime_note})"
    return "MID_VOL", f"기본 분류 ({regime_note})"


# ---------------------------------------------------------------------------
# intraday_plan_events — 장중 선별 이력 (review/P4 화면용)
# ---------------------------------------------------------------------------

def _ensure_table() -> None:
    """intraday_plan_events 테이블과 인덱스를 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS intraday_plan_events (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date         TEXT NOT NULL,
                event_time         TEXT NOT NULL,
                "trigger"          TEXT NOT NULL,
                regime             TEXT,
                market_tone        TEXT,
                symbols_added_json TEXT NOT NULL,
                created_at         TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_intraday_plan_events_date"
            " ON intraday_plan_events(trade_date)"
        )


def record_intraday_event(
    *,
    trigger: str,
    regime: str | None,
    market_tone: str | None,
    symbols_added: list[dict[str, Any]],
    trade_date: str | None = None,
) -> bool:
    """장중 신규 편입 이벤트 1행 기록 (best-effort — 실패해도 예외 전파 없음).

    Args:
        trigger: 'momentum_scan' | 'intraday_refresh'.
        regime: 이벤트 시점 레짐 (None 허용).
        market_tone: 이벤트 시점 시장톤 (None 허용).
        symbols_added: [{symbol, name, profile, reason}] 신규 편입 목록.
        trade_date: YYYY-MM-DD (생략 시 오늘 KST).

    Returns:
        기록 성공 여부. symbols_added가 비면 기록하지 않고 False.
    """
    if not symbols_added:
        return False
    try:
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        date = trade_date or now.strftime("%Y-%m-%d")
        now_iso = now.isoformat()
        _ensure_table()
        with get_connection() as conn:
            conn.execute(
                'INSERT INTO intraday_plan_events'
                ' (trade_date, event_time, "trigger", regime, market_tone, symbols_added_json, created_at)'
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    date,
                    now_iso,
                    str(trigger),
                    regime,
                    market_tone,
                    json.dumps(symbols_added, ensure_ascii=False),
                    now_iso,
                ),
            )
        logger.info(
            "SUCCESS: [IntradayProfile] event recorded trigger=%s regime=%s added=%d",
            trigger, regime, len(symbols_added),
        )
        return True
    except Exception as exc:
        logger.warning("WARN: [IntradayProfile] event 기록 실패(best-effort) — %s", exc)
        return False


def fetch_intraday_events(trade_date: str) -> list[dict[str, Any]]:
    """특정 거래일의 장중 선별 이력 조회 (P4 화면/API용 — 시간순).

    Args:
        trade_date: YYYY-MM-DD.

    Returns:
        [{id, trade_date, event_time, trigger, regime, market_tone, symbols_added, created_at}]
        symbols_added는 JSON 파싱된 list.
    """
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM intraday_plan_events WHERE trade_date = ?"
            " ORDER BY event_time ASC, id ASC",
            (trade_date,),
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        try:
            d["symbols_added"] = json.loads(d.pop("symbols_added_json") or "[]")
        except Exception:
            d["symbols_added"] = []
            d.pop("symbols_added_json", None)
        events.append(d)
    return events
