"""리더 진입(실전) — 스캐너가 넣은 강세 리더를 실제 매수한다. 두 모드(momentum.entry_mode).

**pullback(E6 강세근접VWAP, 기본)** — 2026-09-18 backtest 발굴 필승패턴(상승장 76%승·EV+0.63%).
  강세(시가대비>0) 리더가 **VWAP 눌림 구간[floor,ceiling]** 으로 얕게 눌릴 때만 매수(추격 아님).
  **상승장(risk_on/surge) 전용** — 보합/하락은 현행 눌림전략 담당(불변). 09-18 규명: 상승장 손실 뿌리는
  ①추격(momentum breakout=꼭지매수) ②laggard 매수. pullback은 둘 다 회피(강세필터+VWAP지지).

**breakout(구 ORB 추격, 롤백용)** — 시가~OR_END 고가를 첫 상향돌파+VWAP위+시가대비≥rs_min. 상승장서
  꼭지추격으로 매 세션 순손실이라 기본 비활성(momentum.entry_mode=breakout로만 복귀).

공통: 유니버스 스캔→`_emit_signal(momentum=True)`(mean-reversion 게이트 우회, 안전게이트·preflight 통과).
종목당 하루 1회. 보유/당일매수/기록 종목 스킵. 청산은 rule_resolver 하이브리드 트레일(상승+2/1.5·폭등+3/2).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting

logger = logging.getLogger("MomentumEntry")
KST = ZoneInfo("Asia/Seoul")


def _f(getter: Callable, key: str, default: float) -> float:
    try:
        return float(getter(key, default) or default)
    except (TypeError, ValueError):
        return default


def _detect_breakout(bars: list, or_end: str, exec_start: str, rs_min: float):
    """첫 모멘텀 돌파 → (entry_ts, breakout_price, vwap, change_from_open) 또는 None (백테스트 동일)."""
    if not bars:
        return None
    day_open = (bars[0]["open"] or bars[0]["close"] or 0)
    if day_open <= 0:
        return None
    or_highs = [b["high"] or 0 for b in bars if b["bar_ts"] < or_end]
    or_high = max(or_highs) if or_highs else 0
    if or_high <= 0:
        return None
    pv = vv = 0.0
    for b in bars:
        c = b["close"] or 0
        v = b["volume"] or 0
        pv += c * v
        vv += v
        vwap = pv / vv if vv > 0 else c
        if b["bar_ts"] >= exec_start and (b["high"] or 0) > or_high and c > vwap:
            cfo = (c / day_open - 1) * 100
            if cfo >= rs_min:
                return b["bar_ts"], round(or_high, 2), round(vwap, 2), round(cfo, 2)
    return None


def _detect_leader_pullback(bars: list, floor_pct: float, ceiling_pct: float, strength_min: float = 0.0):
    """E6 강세근접VWAP(2026-09-18 backtest 76%승·EV+0.63%) — 강세 리더가 VWAP 눌림 구간에 있으면 진입.

    추격(_detect_breakout)의 정반대: 시가대비 오른 강한 종목(cfo>strength_min)이 **VWAP 지지 근처**
    (floor_pct ≤ vwap_dist% ≤ ceiling_pct)로 얕게 눌릴 때만 산다. laggard(cfo≤0)·추격(vwap_dist>ceiling)
    은 제외. 스크리너가 강세 리더를 유니버스에 넣으면 이 검출이 눌림 순간을 잡아 매수한다.
    반환: (entry_ts, ref_price, vwap, cfo) 또는 None.
    """
    if not bars:
        return None
    day_open = (bars[0]["open"] or bars[0]["close"] or 0)
    if day_open <= 0:
        return None
    pv = vv = 0.0
    for b in bars:
        c = b["close"] or 0
        v = b["volume"] or 0
        pv += c * v
        vv += v
    vwap = pv / vv if vv > 0 else (bars[-1]["close"] or 0)
    last = bars[-1]["close"] or 0
    if last <= 0 or vwap <= 0:
        return None
    cfo = (last / day_open - 1) * 100
    vwap_dist = (last / vwap - 1) * 100
    if cfo > strength_min and floor_pct <= vwap_dist <= ceiling_pct:
        return bars[-1]["bar_ts"], round(last, 2), round(vwap, 2), round(cfo, 2)
    return None


def _late_chase_pct(or_high: float, last_close: float) -> float:
    """돌파레벨(OR 고가) 대비 현재가가 얼마나 위인가(%). 뒷북(이미 달린 돌파) 진입 방지 판정용.

    백테스트는 '돌파레벨 진입'을 가정하는데, 2분 스캔 지연 동안 가격이 돌파가보다 크게 위로 가면
    (뒷북) 남은 업사이드↓·리스크↑라 엣지가 재현 안 된다. 이 값이 임계 초과면 진입 보류(재검토 대기).
    """
    if or_high <= 0 or last_close <= 0:
        return 0.0
    return (last_close / or_high - 1.0) * 100.0


def _ensure_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS momentum_signals ("
        " id INTEGER PRIMARY KEY, trade_date TEXT NOT NULL, symbol TEXT NOT NULL,"
        " detected_at TEXT NOT NULL, entry_ts TEXT, price REAL, last_close REAL, vwap REAL,"
        " change_from_open REAL, bought INTEGER NOT NULL DEFAULT 0,"
        " attempts INTEGER NOT NULL DEFAULT 0, reason TEXT,"
        " UNIQUE(trade_date, symbol))"
    )
    try:  # 기존 테이블(09-08 생성) 마이그레이션 — attempts 컬럼 추가
        conn.execute("ALTER TABLE momentum_signals ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # 이미 존재


def _name_of(conn, symbol: str) -> str:
    for tbl, col in (("trading_signals", "name"), ("trading_orders", "name")):
        try:
            r = conn.execute(f"SELECT {col} FROM {tbl} WHERE symbol=? AND {col} IS NOT NULL AND {col}!='' "
                             "ORDER BY created_at DESC LIMIT 1", (symbol,)).fetchone()
            if r and r[0]:
                return str(r[0])
        except Exception:
            continue
    return ""


async def run_momentum_entries(trade_date: str | None = None, *, getter: Callable = get_setting) -> dict[str, Any]:
    """유니버스 모멘텀 리더 감지 → 실제 매수(_emit_signal momentum=True). 반환: {enabled, scanned, entered}.

    momentum.enabled=false면 no-op. 안전: 이미 보유/당일 매수/기록 종목 스킵, 매수는 preflight
    (배포캡·포지션한도·긴급정지·손실한도)와 _emit_signal 안전게이트(레버리지/ETN·손실스트릭 등)를 통과해야 함.
    """
    try:
        if str(getter("momentum.enabled", True)).lower() in ("false", "0", "no"):
            return {"enabled": False, "scanned": 0, "entered": 0}
    except Exception:
        pass
    td = trade_date or datetime.now(KST).strftime("%Y-%m-%d")
    # 진입 방식 — pullback(E6 강세근접VWAP, 기본) | breakout(구 ORB 추격, 롤백용).
    #   pullback은 09-18 발굴 필승패턴: 스캐너가 넣은 강세 리더를 VWAP 눌림에서만 매수(추격 아님).
    #   추격(breakout)은 상승장서 꼭지매수로 매 세션 순손실(09-18 규명)이라 기본 비활성.
    entry_mode = str(getter("momentum.entry_mode", "pullback") or "pullback").strip().lower()
    if entry_mode not in ("pullback", "breakout"):
        entry_mode = "pullback"
    # pullback(E6)은 상승장(risk_on/surge) 전용 — 보합/하락은 현행 눌림전략이 담당(불변). 레짐 게이트.
    if entry_mode == "pullback":
        try:
            from .decision_engine import _current_regime_label
            _regime = _current_regime_label()
        except Exception:
            _regime = ""
        if _regime not in ("risk_on", "up", "surge"):
            return {"enabled": True, "scanned": 0, "entered": 0, "reason": f"not_up_regime({_regime})"}
    # E6 밴드 — 진입 게이트와 동일 설정 재사용(설정화면에서 함께 조정). strength: cfo>0(강세).
    e6_floor = _f(getter, "engine.entry_vwap_floor_riskon", -3.0)
    e6_ceiling = _f(getter, "engine.entry_vwap_ceiling_riskon", 1.0)
    # exec_start 이전이면 스킵(장 초반 OR 형성 전)
    now_hm = datetime.now(KST).strftime("%H%M%S")
    exec_start = str(getter("momentum.exec_start", "093000") or "093000")
    if now_hm < exec_start:
        return {"enabled": True, "scanned": 0, "entered": 0, "reason": "before_exec_start"}
    rs_min = _f(getter, "momentum.rs_min", 4.0)
    or_end = str(getter("momentum.or_end", "093000") or "093000")
    min_vol = _f(getter, "momentum.min_vol", 300000)
    min_bars = int(_f(getter, "momentum.min_bars", 50))
    premium = _f(getter, "momentum.entry_premium_pct", 1.5) / 100.0  # 체결력: 돌파가 위 지정가(빠른 리더 추격) — order_style=limit 전용
    # 주문방식(설정화면에서 수정) — market=시장가(감지 즉시 체결 보장) / limit=지정가+프리미엄(기존, 체결 미보장).
    # 09-18 고질병: 상승장 리더를 감지해도 지정가 체결 실패로 참여 못 함 → 기본 시장가로 체결 보장.
    order_style = str(getter("momentum.order_style", "market") or "market").strip().lower()
    if order_style not in ("market", "limit"):
        order_style = "market"
    spacing = _f(getter, "momentum.buy_spacing_sec", 1.5)            # 매수 간격(KIS 초당한도 EGW00215 회피)
    max_attempts = int(_f(getter, "momentum.max_attempts", 3))       # #1: 일시적 실패(rate-limit 등) 재시도 상한
    max_late = _f(getter, "momentum.max_late_chase_pct", 2.0)        # #2: 돌파가 대비 현재가 이 %↑면 뒷북=보류
    now_iso = datetime.now(KST).isoformat()

    from .position_manager import position_manager
    held = {str(p.get("symbol") or "").strip() for p in position_manager.get_positions()}
    scanned = entered = 0
    candidates: list[tuple[str, float, float, float, str]] = []  # (sym, price, vwap, cfo, entry_ts)
    try:
        with get_connection() as conn:
            _ensure_table(conn)
            # #1 중복/재시도: 재시도 소진(attempts>=max)만 제외 — 실패는 재시도 허용(이전엔 감지 1회로 영구 스킵).
            done = {r["symbol"] for r in conn.execute(
                "SELECT symbol FROM momentum_signals WHERE trade_date=? AND attempts>=?", (td, max_attempts))}
            # 이미 접수된 매수(momentum·눌림 무관)만 성공으로 간주해 제외 — failed는 제외 안 함(재시도 대상).
            try:
                bought_ok = {r["symbol"] for r in conn.execute(
                    "SELECT DISTINCT symbol FROM trading_orders WHERE trade_date=? AND side='buy'"
                    " AND status IN ('filled','partial','submitted')", (td,))}
            except Exception:
                bought_ok = set()  # 테이블 부재 등 — 성공 dedup 스킵(스캔은 계속)
            uni = conn.execute(
                "SELECT symbol FROM intraday_bars WHERE trade_date=? GROUP BY symbol"
                " HAVING SUM(volume)>=? AND COUNT(*)>=?", (td, min_vol, min_bars)).fetchall()
            for row in uni:
                sym = row["symbol"]
                scanned += 1
                if sym in done or sym in held or sym in bought_ok:
                    continue
                bars = conn.execute(
                    "SELECT bar_ts, open, high, low, close, volume FROM intraday_bars"
                    " WHERE trade_date=? AND symbol=? ORDER BY bar_ts", (td, sym)).fetchall()
                if entry_mode == "pullback":
                    # E6: 강세(cfo>0) 리더가 VWAP 눌림 구간[e6_floor, e6_ceiling]일 때만. 추격/뒷북 판정 불필요.
                    sig = _detect_leader_pullback([dict(b) for b in bars], e6_floor, e6_ceiling, 0.0)
                    if not sig:
                        continue
                    entry_ts, or_high, vwap, cfo = sig  # or_high=현재가(ref) — pullback은 돌파레벨 개념 없음
                    last_close = float(bars[-1]["close"] or or_high)
                else:  # breakout(구 추격, 롤백용)
                    sig = _detect_breakout([dict(b) for b in bars], or_end, exec_start, rs_min)
                    if not sig:
                        continue
                    entry_ts, or_high, vwap, cfo = sig
                    last_close = float(bars[-1]["close"] or or_high)
                    # #2 뒷북 방지: 돌파가 대비 현재가가 너무 위(스캔 지연 동안 달림)면 보류.
                    late = _late_chase_pct(or_high, last_close)
                    if late > max_late:
                        logger.info("INFO: [MomentumEntry] 뒷북 보류 symbol=%s 돌파대비 +%.1f%% > %.1f%%(가격 정상화시 재진입)",
                                    sym, late, max_late)
                        continue
                # 시장가는 사이징 기준가만 필요(프리미엄 무의미) → 현재가. 지정가는 체결력 위해 소폭 프리미엄.
                # 단 pullback(E6)은 VWAP 지지 근처 매수라 프리미엄 추격이 무의미 → 지정가여도 현재가.
                if order_style == "market" or entry_mode == "pullback":
                    price = round(last_close, 2)
                else:
                    price = round(max(or_high, last_close) * (1 + premium), 2)
                conn.execute(
                    "INSERT INTO momentum_signals"
                    " (trade_date, symbol, detected_at, entry_ts, price, last_close, vwap, change_from_open)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(trade_date, symbol) DO UPDATE SET"
                    " detected_at=excluded.detected_at, price=excluded.price, last_close=excluded.last_close",
                    (td, sym, now_iso, entry_ts, price, last_close, vwap, cfo))
                candidates.append((sym, price, vwap, cfo, entry_ts))
            conn.commit()
    except Exception as exc:
        logger.warning("WARN: [MomentumEntry] 스캔 실패(fail-open) — %s", exc)
        return {"enabled": True, "scanned": scanned, "entered": 0}

    # 매수 실행 — _emit_signal(momentum=True): 눌림게이트 우회, 안전게이트·preflight 통과
    from .decision_engine import decision_engine
    for _idx, (sym, price, vwap, cfo, entry_ts) in enumerate(candidates):
        if _idx > 0 and spacing > 0:
            await asyncio.sleep(spacing)  # 버스트 방지(KIS 초당 거래건수 한도)
        try:
            with get_connection() as conn:
                # 시도 횟수 증가(성공/실패 무관) — 재시도 상한 관리. 성공 여부는 다음 스캔의 bought_ok
                # (trading_orders 접수상태)가 판정하므로 여기서 bought=1을 단정하지 않는다(_emit_signal이
                # 접수 성공여부를 반환하지 않아 09-08처럼 실패인데 성공기록되던 문제 방지).
                conn.execute("UPDATE momentum_signals SET attempts=attempts+1 WHERE trade_date=? AND symbol=?",
                             (td, sym))
                conn.commit()
                name = _name_of(conn, sym)
            logger.warning(
                "LEADER-BUY: 리더 매수 시도 mode=%s symbol=%s name=%s 방식=%s 기준가=%.0f 시가대비=%+.2f%% vwap=%.0f",
                entry_mode, sym, name, order_style, price, cfo, vwap)
            await decision_engine._emit_signal(
                sym, {"name": name, "confidence": 0.7}, price,
                {"momentum": True, "order_style": order_style})
            entered += 1
        except Exception as exc:
            logger.warning("WARN: [MomentumEntry] 매수 실패 symbol=%s — %s", sym, exc)
            try:
                with get_connection() as conn:
                    conn.execute("UPDATE momentum_signals SET reason=? WHERE trade_date=? AND symbol=?",
                                 (str(exc)[:80], td, sym))
                    conn.commit()
            except Exception:
                pass
    if candidates:
        logger.info("SUCCESS: [MomentumEntry] td=%s scanned=%d 신규리더=%d 매수시도=%d", td, scanned, len(candidates), entered)
    return {"enabled": True, "scanned": scanned, "entered": entered}
