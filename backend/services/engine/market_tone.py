"""시장 톤 분석 서비스 (S2 — 08:00 KST).

index-board 브리핑 텍스트를 결정론적 휴리스틱(classify_regime_heuristic)으로
분석해 오늘의 시장 분위기(긍정/중립/부정)와 regime을 판정하고 결과를
DB의 market_tone_results 테이블에 저장한다. LLM은 사용하지 않는다.

주의:
- regime 판정은 "참고용 분석 보조"다. 매매 실행 판단은 Python 룰 엔진이 한다.
- 브리핑이 아예 없으면 기본값(neutral)을 반환하고 시스템은 계속 실행된다.
  (과거 LLM 백업이 index-board 장애 중 허구 KOSPI를 생성한 사례가 있어,
   추측 대신 결정론적 중립 폴백을 명시적으로 선호한다.)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from .pipeline_audit import finish_pipeline_run, normalize_trigger_source, start_pipeline_run

logger = logging.getLogger("MarketToneService")


def _ensure_table() -> None:
    """market_tone_results와 morning_context 테이블이 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_tone_results (
                id          TEXT PRIMARY KEY,
                trade_date  TEXT NOT NULL,
                tone        TEXT NOT NULL DEFAULT 'neutral',
                confidence  REAL NOT NULL DEFAULT 0.0,
                summary     TEXT NOT NULL DEFAULT '',
                key_factors TEXT NOT NULL DEFAULT '[]',
                risk_factors TEXT NOT NULL DEFAULT '[]',
                raw_response TEXT NOT NULL DEFAULT '',
                provider    TEXT NOT NULL DEFAULT 'none',
                created_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_tone_trade_date ON market_tone_results(trade_date)"
        )
        # Phase 2: index-board에서 파싱한 객관 수치(JSON)를 저장하는 컬럼. 기존 DB는 가드 ALTER로 추가.
        try:
            conn.execute(
                "ALTER TABLE market_tone_results ADD COLUMN parsed_numbers TEXT NOT NULL DEFAULT '{}'"
            )
        except Exception:
            pass  # 이미 컬럼이 있으면(중복 ALTER) 무시 — 다른 마이그레이션 패턴과 동일
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS morning_context (
                id              TEXT PRIMARY KEY,
                trade_date      TEXT NOT NULL UNIQUE,
                market_data     TEXT NOT NULL DEFAULT '{}',
                regime          TEXT NOT NULL DEFAULT 'neutral',
                risk_level      TEXT NOT NULL DEFAULT 'normal',
                stock_character TEXT NOT NULL DEFAULT '',
                rulepack_hint   TEXT NOT NULL DEFAULT '',
                key_factors     TEXT NOT NULL DEFAULT '[]',
                risk_factors    TEXT NOT NULL DEFAULT '[]',
                raw_response    TEXT NOT NULL DEFAULT '',
                provider        TEXT NOT NULL DEFAULT 'none',
                created_at      TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_morning_context_trade_date ON morning_context(trade_date)"
        )


def classify_regime_heuristic(
    text: str, market_data: dict | None = None, numbers: dict | None = None
) -> dict:
    """index-board 브리핑 텍스트를 regime으로 휴리스틱 분류. 애매하면 neutral(보수적).

    Args:
        text: 브리핑 원문.
        market_data: KIS/야간 수집 데이터(백업 입력용). numbers가 없을 때 vix 폴백에만 사용.
        numbers: parse_briefing_numbers() 결과. 있으면 객관 수치를 1차 신호로 쓰고
                 키워드(net)는 보조로 결합한다. None이면 기존 키워드-only 동작과 동일.

    반환 dict 키(기존 parsed 구조와 호환):
      tone, confidence, summary, key_factors, risk_factors,
      regime, risk_level, stock_character, rulepack_hint, data_note
    추가 키: numbers (입력 numbers를 그대로 반환, 없으면 빈 dict)
    """
    t = text or ""
    RISK_ON = ["위험선호", "강세", "회복", "반등", "상승 출발", "강세 출발", "급등", "우호적", "갭상승", "갭 상승"]
    RISK_OFF = ["위험회피", "약세", "하락", "급락", "부진", "경계", "위축", "불안", "하락 출발"]
    VOLATILE = ["변동성", "혼조", "불확실", "출렁", "급변", "엇갈"]
    on = sum(t.count(k) for k in RISK_ON)
    off = sum(t.count(k) for k in RISK_OFF)
    vol = sum(t.count(k) for k in VOLATILE)
    net = on - off
    THRESHOLD = 2  # |net|이 이 미만이면 neutral (보수적)

    nums = numbers if isinstance(numbers, dict) else None

    # ── 1차 신호: 객관 수치 (numbers) ──
    # fear_greed 극단 / 코스피200 선물 강한 방향성에서 bias를 잡고, 키워드 net과 결합한다.
    num_lean = 0  # +면 risk_on, -면 risk_off 쪽으로 객관 수치가 끌어당김
    num_signal_strong = False  # 객관 수치가 강한 방향성 신호를 줬는가(컨피던스 가산용)
    if nums:
        fg = nums.get("fear_greed")
        fut = nums.get("kospi200_futures_pct")
        try:
            if fg is not None:
                fg = float(fg)
                if fg <= 25:  # extreme fear
                    num_lean -= 1
                    num_signal_strong = True
                elif fg >= 75:  # extreme greed
                    num_lean += 1
                    num_signal_strong = True
        except (TypeError, ValueError):
            pass
        try:
            if fut is not None:
                fut = float(fut)
                if fut <= -1.0:  # 강한 하락 선물
                    num_lean -= 1
                    num_signal_strong = True
                elif fut >= 1.0:  # 강한 상승 선물
                    num_lean += 1
                    num_signal_strong = True
        except (TypeError, ValueError):
            pass

    # ── regime 결정: 키워드 net + 객관 lean 결합 ──
    if nums and num_signal_strong:
        # 객관 수치를 점수화해 키워드와 합산(객관 1점 = 키워드 THRESHOLD 가중치).
        combined = net + num_lean * THRESHOLD
        if vol >= 2 and abs(combined) < THRESHOLD:
            regime = "volatile"
        elif combined >= THRESHOLD:
            regime = "risk_on"
        elif combined <= -THRESHOLD:
            regime = "risk_off"
        else:
            regime = "neutral"
    else:
        # numbers 없음 또는 약한 신호 → 기존 키워드-only 로직(완전 하위호환)
        if vol >= 2 and abs(net) < THRESHOLD:
            regime = "volatile"
        elif net >= THRESHOLD:
            regime = "risk_on"
        elif net <= -THRESHOLD:
            regime = "risk_off"
        else:
            regime = "neutral"

    tone = {"risk_on": "positive", "risk_off": "negative"}.get(regime, "neutral")

    # ── risk_level: numbers vix 우선 → market_data vix 폴백 → normal ──
    risk_level = "normal"
    vix_source = None
    vix_val = None
    if nums and nums.get("vix") is not None:
        try:
            vix_val = float(nums["vix"])
            vix_source = "numbers"
        except (TypeError, ValueError):
            vix_val = None
    if vix_val is None:
        try:
            vix = (market_data or {}).get("vix")
            mv = vix.get("price") if isinstance(vix, dict) else None
            if mv is not None:
                vix_val = float(mv)
                vix_source = "market_data"
        except Exception:
            vix_val = None
    if vix_val is not None:
        risk_level = "low" if vix_val < 20 else ("high" if vix_val > 30 else "normal")

    # ── confidence: 키워드 net 기반 → 객관 수치 corroborate/conflict 보정 ──
    confidence = min(abs(net) / (THRESHOLD * 2), 1.0)
    if nums and num_signal_strong:
        keyword_dir = (net > 0) - (net < 0)  # +1/0/-1
        num_dir = (num_lean > 0) - (num_lean < 0)
        if keyword_dir == 0:
            # 키워드가 중립이면 객관 수치가 컨피던스를 끌어올린다
            confidence = max(confidence, 0.6)
        elif keyword_dir == num_dir:
            confidence = min(confidence + 0.25, 1.0)  # corroborate → 가산
        else:
            confidence = max(confidence - 0.25, 0.0)  # conflict → 감산

    data_note = "index-board 휴리스틱 분류 (on=%d off=%d vol=%d net=%d)" % (on, off, vol, net)
    if nums:
        data_note += " | numbers(vix=%s,fg=%s,fut=%s,lean=%d,vix_src=%s)" % (
            nums.get("vix"), nums.get("fear_greed"), nums.get("kospi200_futures_pct"),
            num_lean, vix_source,
        )

    return {
        "tone": tone,
        "confidence": round(confidence, 2),
        "summary": t,  # 브리핑 원문을 요약으로 사용
        "key_factors": [],
        "risk_factors": [],
        "data_note": data_note,
        "regime": regime,
        "risk_level": risk_level,
        "stock_character": "",
        "rulepack_hint": "",
        "numbers": nums or {},
    }


def _format_intraday_for_prompt(snapshot: dict[str, Any]) -> str:
    """fetch_intraday_kr_market_snapshot() 결과를 LLM 프롬프트용 텍스트로 변환."""
    lines: list[str] = []

    kospi = snapshot.get("kospi") or {}
    kosdaq = snapshot.get("kosdaq") or {}
    k_rate = kospi.get("change_rate")
    q_rate = kosdaq.get("change_rate")
    if k_rate is not None or q_rate is not None:
        k_str = f"{k_rate:+.2f}%" if k_rate is not None else "N/A"
        q_str = f"{q_rate:+.2f}%" if q_rate is not None else "N/A"
        lines.append(f"[현재 지수]\n  KOSPI: {k_str} / KOSDAQ: {q_str}")

    top10 = snapshot.get("top10") or []
    if top10:
        rows = "\n".join(
            f"  {it['name']}({it['symbol']}): {it['change_rate']:+.2f}%"
            for it in top10
            if it.get("change_rate") is not None
        )
        lines.append(f"[거래대금 상위 종목 동향]\n{rows}")

    avg = snapshot.get("vol30_avg_change")
    if avg is not None:
        lines.append(f"[거래량 상위 30종목 평균 등락률]: {avg:+.2f}%")

    sectors = snapshot.get("sectors") or []
    if sectors:
        up = [s for s in sectors if (s.get("change_rate") or 0) > 0]
        down = [s for s in sectors if (s.get("change_rate") or 0) < 0]
        up_str = ", ".join(f"{s['name']} {s['change_rate']:+.2f}%" for s in sorted(up, key=lambda x: -x["change_rate"]))
        down_str = ", ".join(f"{s['name']} {s['change_rate']:+.2f}%" for s in sorted(down, key=lambda x: x["change_rate"]))
        if up_str:
            lines.append(f"[강세 섹터]: {up_str}")
        if down_str:
            lines.append(f"[약세 섹터]: {down_str}")

    if not lines:
        return "[장중 시장 현황]\n  데이터 없음"
    return "\n\n".join(lines)


def _should_attach_open_snapshot(now: datetime) -> bool:
    """아침 분기에서 KIS 실시간 국내 스냅샷을 보강할지 판단.

    거래일 09:00(개장) 이후에만 유효 — 그 전엔 KIS 지수가 전일 데이터라 무의미.
    """
    from .trading_calendar import is_trading_day

    if not is_trading_day(now):
        return False
    return (now.hour, now.minute) >= (9, 0)


def _is_briefing_fresh(briefing: dict | None, is_intraday: bool) -> bool:
    """index-board 브리핑이 '신선'한지 판정 — stale면 LLM 백업으로 폴백시키기 위함.

    - 아침(장전): generated_at이 최근 ~18h 이내면 fresh
      (장전 브리핑은 보통 새벽~장 시작 전 산출 → 08:00 실행 시점까지 커버).
    - 장중(regular): generated_at이 briefing.intraday_stale_minutes(기본 120) 이내면 fresh.
    generated_at은 UTC ISO('...Z')로 파싱한다. 파싱 실패/없음이면 stale로 본다(보수적).
    """
    if not briefing:
        return False
    raw = briefing.get("generated_at")
    if not raw:
        return False
    try:
        s = str(raw).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        gen = datetime.fromisoformat(s)
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    now = datetime.now(timezone.utc)
    age_sec = (now - gen).total_seconds()
    if age_sec < 0:
        # 미래 timestamp(시계 오차 등) — 최근 1h 이내면 허용, 그 이상이면 stale
        return age_sec > -3600
    if is_intraday:
        try:
            from ..settings_store import get_setting

            stale_min = float(get_setting("briefing.intraday_stale_minutes", 120) or 120)
        except Exception:
            stale_min = 120.0
        return age_sec <= stale_min * 60.0
    # 아침: 18h
    return age_sec <= 18 * 3600.0


async def run_market_tone_analysis(
    trigger_source: str = "api_manual",
    intraday_snapshot: "dict[str, Any] | None" = None,
) -> dict[str, Any]:
    """시장 톤 분석을 실행하고 결과를 DB에 저장한 뒤 반환한다.

    Args:
        trigger_source: Actual execution source for audit, e.g. auto_scheduler or console_manual.
        intraday_snapshot: 이미 수집된 장중 스냅샷. 전달 시 API 재호출 없이 재사용.

    Returns:
        {
            "ok": bool,
            "trade_date": str,
            "tone": str,
            "confidence": float,
            "summary": str,
            "provider": str,
            "id": str,
        }
    """
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    safe_source = normalize_trigger_source(trigger_source)
    run_audit_id = start_pipeline_run(
        trade_date=today,
        step="S2",
        trigger_source=safe_source,
        display_source="manual-like-console" if safe_source == "console_manual" else safe_source,
    )
    logger.info("START: MarketToneService.run trade_date=%s source=%s", today, safe_source)

    try:
        _ensure_table()
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            message=f"ensure_table_failed: {exc}",
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: MarketToneService ensure table failed trade_date=%s reason=%s", today, exc)
        raise

    # 장중 판별은 원본 trigger_source 기준 — normalize는 intraday_refresh를 api_manual로
    # 접어버리므로(audit 화이트리스트 밖) safe_source로 판별하면 항상 False가 된다.
    # intraday_snapshot이 전달된 경우도 장중 호출로 간주한다(이중 안전).
    raw_source = str(trigger_source or "").strip().lower()
    is_intraday = raw_source == "intraday_refresh" or bool(intraday_snapshot)
    market_data: dict[str, Any] = {}
    briefing_scraped = False
    briefing: dict[str, Any] | None = None

    if is_intraday:
        # 장중 분기: 사전 수집된 스냅샷 재사용 or 신규 호출
        slot = datetime.now(__import__("zoneinfo").ZoneInfo("Asia/Seoul")).strftime("%H:%M")
        try:
            if intraday_snapshot and intraday_snapshot.get("ok"):
                market_data = intraday_snapshot
            else:
                from ..kis.domestic.universe_service import fetch_intraday_kr_market_snapshot
                market_data = await fetch_intraday_kr_market_snapshot()
            market_data_text = _format_intraday_for_prompt(market_data)
        except Exception as exc:
            logger.warning("WARN: MarketToneService 장중 스냅샷 수집 실패 — %s", exc)
            market_data_text = "[장중 시장 현황]\n  데이터 수집 실패 — 가용한 정보만 기준으로 판단"
    else:
        # 아침 분기: 해외 야간 데이터 수집
        slot = "08:00"
        try:
            from .market_data_fetcher import fetch_overnight_market_summary, format_for_prompt

            market_data = await fetch_overnight_market_summary()
            # 코스피200 야간선물(KIS) 보강 — 다음날 코스피 갭 방향 선행지표
            try:
                from ..kis.domestic.service import get_kospi_night_futures

                nf = await get_kospi_night_futures()
                if nf:
                    market_data["kospi_night_futures"] = nf
            except Exception as _nf_exc:
                logger.warning("WARN: 야간선물 보강 실패 (비치명) — %s", _nf_exc)
            market_data_text = format_for_prompt(market_data)
            # 장 개시 후(09:00~) 실행 시 KIS 실시간 국내 스냅샷 보강 — S2가 09:01로 이동(2026-06-10).
            # KR 지수는 반드시 KIS 사용(Yahoo는 프리마켓 stale로 6/9 사고 원인 — 부활 금지).
            try:
                now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
                if _should_attach_open_snapshot(now_kst):
                    from ..kis.domestic.universe_service import fetch_intraday_kr_market_snapshot

                    kr_snap = await fetch_intraday_kr_market_snapshot()
                    if kr_snap and kr_snap.get("ok"):
                        market_data["kr_open_snapshot"] = kr_snap
                        market_data_text += (
                            "\n\n[장 개시 직후 국내 현황 (KIS 실시간) — 개장 직후 수치로 장중 변동 가능]\n"
                            + _format_intraday_for_prompt(kr_snap)
                        )
            except Exception as _kr_exc:
                logger.warning("WARN: 장개시 KIS 스냅샷 보강 실패 (비치명) — %s", _kr_exc)
        except Exception as exc:
            logger.warning("WARN: MarketToneService 해외 시장 데이터 실시간 수집 실패 — %s", exc)
            # S11 overnight snapshot fallback.
            try:
                from .us_market_watch import get_latest_snapshot
                from .market_data_fetcher import format_for_prompt as _fmt

                snapshot = get_latest_snapshot()
                if snapshot and snapshot.get("raw_data") and isinstance(snapshot["raw_data"], dict):
                    market_data = snapshot["raw_data"]
                    market_data_text = _fmt(snapshot["raw_data"])
                    market_data_text += (
                        f"\n[참고: S11 스냅샷 기준 {snapshot['snapshot_date']} "
                        f"{snapshot['snapshot_time']} KST]"
                    )
                    logger.info(
                        "INFO: MarketToneService S11 스냅샷 폴백 적용 date=%s time=%s",
                        snapshot["snapshot_date"], snapshot["snapshot_time"],
                    )
                else:
                    market_data_text = "[전날 밤 해외 시장 현황]\n  데이터 수집 실패 — 가용한 정보만 기준으로 판단"
            except Exception as snap_exc:
                logger.warning("WARN: MarketToneService S11 스냅샷 폴백도 실패 — %s", snap_exc)
                market_data_text = "[전날 밤 해외 시장 현황]\n  데이터 수집 실패 — 가용한 정보만 기준으로 판단"

    # index-board 브리핑 스크래핑 — Phase 2: 아침/장중 모두에서 시황 단일출처.
    # 아침은 scrape_morning(pre/kospi), 장중은 scrape_intraday(regular). 둘 다 briefing.scrape_enabled 가드.
    # 신선(fresh)한 브리핑이 있으면 그것이 regime 주력(단일출처)이고, Opus는 휴면 백업으로만 작동한다.
    briefing_fresh = False
    briefing_text = ""
    try:
        from ..settings_store import get_setting

        scrape_enabled = bool(get_setting("briefing.scrape_enabled", True))
    except Exception:
        scrape_enabled = False
    if scrape_enabled:
        try:
            from . import index_board_scraper

            if is_intraday:
                briefing = await index_board_scraper.scrape_intraday()
                briefing_label = "장중 정제(regular)"
            else:
                briefing = await index_board_scraper.scrape_morning()
                briefing_label = "장전 정제"
            if briefing and briefing.get("text"):
                briefing_scraped = True
                briefing_text = str(briefing["text"])
                briefing_fresh = _is_briefing_fresh(briefing, is_intraday)
                market_data_text += (
                    f"\n\n[외부 AI 시황 브리핑 (index-board, {briefing_label})]\n"
                    + briefing_text
                )
                logger.info(
                    "INFO: MarketToneService 브리핑 스크랩 적용 intraday=%s generated_at=%s fresh=%s",
                    is_intraday, briefing.get("generated_at"), briefing_fresh,
                )
            else:
                logger.info("INFO: MarketToneService 브리핑 없음 intraday=%s — 중립 폴백", is_intraday)
        except Exception as scrape_exc:
            logger.warning(
                "WARN: MarketToneService 브리핑 스크랩 실패 (중립 폴백) — %s",
                scrape_exc,
            )

    # regime 판정은 전적으로 결정론적 휴리스틱(classify_regime_heuristic)으로 한다. LLM은 사용하지 않는다.
    # - fresh 브리핑: index-board 객관 수치 + 키워드로 판정 (provider='index-board').
    # - stale 브리핑(텍스트는 있으나 오래됨): 같은 휴리스틱으로 판정하되 provider='heuristic-stale'로 태깅
    #   + index-board 부재/노후 운영 알림 1회.
    # - 브리핑 텍스트 자체가 없음(스크랩 실패/비활성): 추측 대신 결정론적 중립 폴백(provider='none').
    #   (과거 LLM 백업이 index-board 장애 중 허구 KOSPI를 생성한 사례가 있어 중립 폴백을 명시적으로 선호.)
    # briefing_scraped는 briefing 텍스트가 있을 때만 True이므로 briefing_text가 비어있지 않음을 보장한다.
    if briefing_scraped and bool(briefing_text):
        from . import index_board_scraper as _ibs

        parsed_numbers = _ibs.parse_briefing_numbers(briefing_text)
        parsed = classify_regime_heuristic(briefing_text, market_data, numbers=parsed_numbers)
        if briefing_fresh:
            provider_tag = "index-board"
            llm_result = {"ok": True, "raw": briefing_text, "provider": provider_tag}
            logger.info(
                "INFO: MarketToneService index-board 주력 regime=%s risk_level=%s note=%s",
                parsed["regime"], parsed["risk_level"], parsed["data_note"],
            )
        else:
            # stale 브리핑 — 휴리스틱은 그대로 쓰되 index-board 노후를 운영 알림으로 남긴다.
            provider_tag = "heuristic-stale"
            llm_result = {"ok": True, "raw": briefing_text, "provider": provider_tag}
            try:
                from .alert_center import create_alert

                create_alert(
                    alert_type="ops_watch",
                    title="⚠️ index-board 시황 노후 — 휴리스틱(stale) regime 사용",
                    severity="WARNING",
                    detail=f"intraday={is_intraday} reason=stale trade_date={today}",
                    trade_date=today,
                )
            except Exception as _alert_exc:
                logger.warning("WARN: MarketToneService stale 알림 발생 실패 (비치명) — %s", _alert_exc)
            logger.info(
                "INFO: MarketToneService index-board stale — 휴리스틱 regime=%s risk_level=%s note=%s",
                parsed["regime"], parsed["risk_level"], parsed["data_note"],
            )
    else:
        # ── 브리핑 텍스트 없음 ──
        # [레짐 드리프트 방지 2026-08-06] 데이터 부재를 "시장 평온(중립)"으로 오해하지 않는다.
        # 오늘 이미 산출된 레짐이 있으면 덮어쓰지 않고 직전 레짐을 유지한다(방어 레짐이 풀리는 것 방지).
        # (실사례: 8/6 아침 negative(-4.9% 폭락일)가 장중 index-board 부재로 neutral로 드리프트).
        # 장 첫 산출부터 데이터가 없을 때만(부트스트랩) 결정론적 중립을 쓴다.
        prior_exists = False
        try:
            with get_connection() as conn:
                prior_exists = conn.execute(
                    "SELECT 1 FROM market_tone_results WHERE trade_date=? LIMIT 1", (today,),
                ).fetchone() is not None
        except Exception as _pe:
            logger.warning("WARN: MarketToneService 직전 레짐 조회 실패 — %s", _pe)
            prior_exists = False

        if prior_exists:
            try:
                from .alert_center import create_alert

                create_alert(
                    alert_type="ops_watch",
                    title="⚠️ index-board 미수신 — 직전 레짐 유지(덮어쓰기 생략)",
                    severity="WARNING",
                    detail=f"intraday={is_intraday} reason=missing_keep_prev trade_date={today}",
                    trade_date=today,
                )
            except Exception as _alert_exc:
                logger.warning("WARN: MarketToneService 미수신 알림 발생 실패 (비치명) — %s", _alert_exc)
            logger.info(
                "INFO: MarketToneService 브리핑 미수신 — 직전 레짐 유지, 덮어쓰기 생략 intraday=%s trade_date=%s",
                is_intraday, today,
            )
            return {
                "ok": True, "skipped": True, "reason": "briefing_missing_keep_prev",
                "provider": "carry-forward", "trade_date": today,
            }

        # 직전 산출 없음(장 첫 산출부터 데이터 부재) → 결정론적 중립 부트스트랩. 운영 알림 1회.
        try:
            from .alert_center import create_alert

            create_alert(
                alert_type="ops_watch",
                title="⚠️ index-board 시황 미수신 — 중립 부트스트랩 regime 사용",
                severity="WARNING",
                detail=f"intraday={is_intraday} reason=missing_bootstrap trade_date={today}",
                trade_date=today,
            )
        except Exception as _alert_exc:
            logger.warning("WARN: MarketToneService 중립 폴백 알림 발생 실패 (비치명) — %s", _alert_exc)
        parsed = {
            "tone": "neutral",
            "confidence": 0.0,
            "summary": "index-board 브리핑 미수신 — 기본값(중립) 적용",
            "key_factors": [],
            "risk_factors": ["index-board 미수신"],
            "data_note": "briefing missing — deterministic neutral fallback",
            "regime": "neutral",
            "risk_level": "normal",
            "stock_character": "",
            "rulepack_hint": "",
        }
        llm_result = {"ok": True, "raw": "", "provider": "none"}
        logger.info(
            "INFO: MarketToneService 브리핑 미수신 — 중립 폴백 regime=neutral risk_level=normal intraday=%s",
            is_intraday,
        )

    # index-board 경로의 객관 수치 저장용 — 중립 폴백 경로는 빈 dict.
    parsed_numbers_json = json.dumps(parsed.get("numbers", {}) or {}, ensure_ascii=False)

    # DB 저장
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_tone_results
                    (id, trade_date, tone, confidence, summary,
                     key_factors, risk_factors, raw_response, provider, created_at,
                     parsed_numbers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    today,
                    parsed["tone"],
                    parsed["confidence"],
                    parsed["summary"],
                    json.dumps(parsed["key_factors"], ensure_ascii=False),
                    json.dumps(parsed["risk_factors"], ensure_ascii=False),
                    llm_result.get("raw", ""),
                    llm_result.get("provider", "none"),
                    now,
                    parsed_numbers_json,
                ),
            )
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            result_ref_id=record_id,
            message=f"save_failed: {exc}",
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: MarketToneService save failed trade_date=%s reason=%s", today, exc)
        raise

    # morning_context 저장 (비치명적 — 실패해도 기존 흐름 유지)
    morning_id = str(uuid.uuid4())
    raw_numbers = {
        k: v for k, v in market_data.items()
        if k not in ("fetched_at", "errors") and isinstance(v, dict)
    }
    # [장전 스냅샷 보존 2026-08-06] "장전 시장 지표" 그리드는 아침(장전) 해외지표 스냅샷이어야 한다.
    # 장중 재평가(is_intraday)는 regime/tone만 갱신하고, market_data(장전 지표)는 아침값을 유지한다
    # (과거: 장중 실행이 국내 장중 kospi/kosdaq로 덮어 해외지표(NASDAQ/S&P500/VIX)가 사라지고
    #  '장전' 라벨과도 어긋났다). 아침 스냅샷이 아직 없으면(첫 실행이 장중) 현재값으로 부트스트랩.
    if is_intraday:
        try:
            with get_connection() as conn:
                _row = conn.execute(
                    "SELECT market_data FROM morning_context WHERE trade_date=? ORDER BY created_at DESC LIMIT 1",
                    (today,),
                ).fetchone()
            if _row and _row[0]:
                _prev_md = json.loads(_row[0])
                if isinstance(_prev_md, dict) and _prev_md:
                    raw_numbers = _prev_md  # 아침 스냅샷 보존
        except Exception as _md_exc:
            logger.warning("WARN: morning_context 장전 스냅샷 보존 조회 실패 (현재값 사용) — %s", _md_exc)
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO morning_context
                    (id, trade_date, market_data, regime, risk_level,
                     stock_character, rulepack_hint, key_factors, risk_factors,
                     raw_response, provider, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    morning_id,
                    today,
                    json.dumps(raw_numbers, ensure_ascii=False),
                    parsed.get("regime", "neutral"),
                    parsed.get("risk_level", "normal"),
                    parsed.get("stock_character", ""),
                    parsed.get("rulepack_hint", ""),
                    json.dumps(parsed["key_factors"], ensure_ascii=False),
                    json.dumps(parsed["risk_factors"], ensure_ascii=False),
                    llm_result.get("raw", ""),
                    llm_result.get("provider", "none"),
                    now,
                ),
            )
    except Exception as mc_exc:
        logger.warning("WARN: morning_context 저장 실패 (비치명) — %s", mc_exc)

    result = {
        "ok": True,
        "trade_date": today,
        "tone": parsed["tone"],
        "confidence": parsed["confidence"],
        "summary": parsed["summary"],
        "key_factors": parsed["key_factors"],
        "risk_factors": parsed["risk_factors"],
        "provider": llm_result.get("provider", "none"),
        "id": record_id,
        "regime": parsed.get("regime", "neutral"),
        "risk_level": parsed.get("risk_level", "normal"),
        "stock_character": parsed.get("stock_character", ""),
        "rulepack_hint": parsed.get("rulepack_hint", ""),
    }
    logger.info(
        "SUCCESS: MarketToneService trade_date=%s tone=%s provider=%s briefing_scraped=%s",
        today, parsed["tone"], llm_result.get("provider", "none"), briefing_scraped,
    )
    finish_pipeline_run(
        run_id=run_audit_id,
        status="success",
        result_ref_id=record_id,
        message=f"tone={parsed['tone']} provider={llm_result.get('provider', 'none')}",
        metadata={"provider": llm_result.get("provider", "none"), "trigger_source": safe_source},
    )
    return result


def get_today_market_tone(trade_date: str) -> dict[str, Any] | None:
    """DB에서 특정 날짜의 시장 톤 결과를 조회한다."""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM market_tone_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for field in ("key_factors", "risk_factors"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = []
    return d


def get_today_tone_slots(trade_date: str) -> list[dict[str, Any]]:
    """당일 시장 톤 슬롯 추이(장중 변화 표시용) — 시각 오름차순.

    market_tone_results는 장중 슬롯마다 1행씩 쌓인다. 톤이 장중 어떻게 바뀌었는지
    (예: positive→mixed)를 화면에서 보여주기 위해 슬롯 목록을 그대로 반환한다(순수 읽기).

    Args:
        trade_date: YYYY-MM-DD 대상 거래일.
    """
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT created_at, tone, confidence FROM market_tone_results "
            "WHERE trade_date = ? ORDER BY created_at ASC",
            (trade_date,),
        ).fetchall()
    return [
        {"created_at": r["created_at"], "tone": r["tone"], "confidence": r["confidence"]}
        for r in rows
    ]


def get_today_morning_context(trade_date: str) -> dict[str, Any] | None:
    """DB에서 특정 날짜의 morning_context를 조회한다."""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM morning_context WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for field in ("market_data", "key_factors", "risk_factors"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = {} if field == "market_data" else []
    return d


def get_latest_morning_context() -> dict[str, Any] | None:
    """날짜 무관, DB에서 가장 최근 morning_context를 조회한다."""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM morning_context ORDER BY trade_date DESC, created_at DESC LIMIT 1",
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for field in ("market_data", "key_factors", "risk_factors"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = {} if field == "market_data" else []
    return d
