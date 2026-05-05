"""APScheduler 기반 하루 사이클 자동매매 스케줄러.

S1 단계: Scheduler 뼈대 + KIS 토큰 선제 갱신 (07:45 KST).
S2~S13 단계에서 placeholder job들이 실 구현으로 교체된다.

전역 싱글턴 `scheduler_instance`을 통해 FastAPI lifespan에서 start/stop한다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .kis.common.client import kis_client

logger = logging.getLogger("Scheduler")

# ---------------------------------------------------------------------------
# Job 함수
# ---------------------------------------------------------------------------


def _today_kst() -> str:
    """Return today's date in Asia/Seoul as YYYY-MM-DD for scheduler decisions."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


async def job_refresh_kis_token() -> None:
    """Job 1 (07:45 KST): KIS 액세스 토큰 선제 갱신.

    장 시작 전에 토큰을 미리 발급해 두어 첫 주문 시 지연을 방지한다.
    get_token()은 내부 캐시를 무시하고 강제 재발급하도록
    token 만료 시각을 0으로 초기화한 뒤 호출한다.
    """
    logger.info("START: [Job1] KIS 토큰 선제 갱신 (07:45 KST)")
    try:
        # 캐시를 무효화해 강제 재발급
        kis_client.token = None
        kis_client.token_expires_at = 0.0
        await kis_client.get_token()
        logger.info("SUCCESS: [Job1] KIS 토큰 선제 갱신 완료")
    except Exception as exc:
        logger.error("FAIL: [Job1] KIS 토큰 갱신 실패 — reason=%s", exc)
        # 서버는 계속 실행 (job 실패가 서버를 종료하지 않음)

    # 오늘 거래일 여부 확인 → system_settings에 플래그 저장
    try:
        from .kis.domestic.service import check_trading_day
        from .settings_store import upsert_setting
        from zoneinfo import ZoneInfo

        today_yyyymmdd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
        is_trading = await check_trading_day(today_yyyymmdd)

        upsert_setting(
            key="schedule_skip_today",
            value=str(not is_trading).lower(),
            value_type="string",
            description="오늘 비거래일 여부 (S1이 매일 갱신)",
            actor="scheduler_s1",
        )
        if not is_trading:
            logger.info("INFO: [Job1] 오늘(%s)은 비거래일 — S2~S5 스킵 플래그 세팅", today_yyyymmdd)
        else:
            logger.info("INFO: [Job1] 오늘(%s)은 거래일 — 정상 진행", today_yyyymmdd)
    except Exception as exc:
        logger.error("FAIL: [Job1] 거래일 확인 실패 — S2~S5는 정상 실행 reason=%s", exc)
        # 실패 시 플래그 세팅 안 함 → 나머지 job은 정상 실행


async def job_market_tone_analysis() -> None:
    """Job 2 (08:00 KST): LLM을 통한 시장 톤 분석 (S2 구현).

    Gemini → Groq → OpenAI GPT 순서로 fallback 호출한다.
    분석 실패 시 neutral 기본값을 저장하고 서버는 계속 실행된다.
    """
    logger.info("START: [Job2] 시장 톤 분석 (08:00 KST)")
    try:
        from .settings_store import get_setting
        if get_setting("schedule_skip_today") == "true":
            logger.info("SKIP: [Job2] 비거래일 — 시장 톤 분석 스킵")
            return
    except Exception:
        pass

    try:
        from .engine.market_tone import run_market_tone_analysis
        result = await run_market_tone_analysis()
        logger.info(
            "SUCCESS: [Job2] 시장 톤 분석 완료 tone=%s provider=%s confidence=%.2f",
            result.get("tone"), result.get("provider"), result.get("confidence", 0.0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job2] 시장 톤 분석 실패 — reason=%s", exc)


async def job_universe_filter() -> None:
    """Job 3 (08:15 KST): 유니버스 필터 (S3 구현).

    KIS 거래량/거래대금 순위를 병렬 호출해 오늘의 유니버스를 구성하고 DB에 저장한다.
    """
    today = _today_kst()
    logger.info("START: [Job3] 유니버스 필터 (%s KST)", today)
    try:
        from .settings_store import get_setting
        if get_setting("schedule_skip_today") == "true":
            logger.info("SKIP: [Job3] 비거래일 — 유니버스 필터 스킵")
            return
    except Exception:
        pass

    try:
        from .engine.universe_filter import run_universe_filter
        result = await run_universe_filter()
        logger.info(
            "SUCCESS: [Job3] 유니버스 필터 완료 raw=%d filtered=%d top_n=%d",
            result.get("raw_count", 0),
            result.get("filtered_count", 0),
            result.get("result_count", 0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job3] 유니버스 필터 실패 — reason=%s", exc)


async def job_hybrid_screening() -> None:
    """Job 4 (08:30 KST): 하이브리드 스크리닝 (S4 구현).

    LLM이 S3 유니버스 필터 결과를 정성 평가해 suitability_score를 부여한다.
    """
    today = _today_kst()
    logger.info("START: [Job4] 하이브리드 스크리닝 (%s KST)", today)
    try:
        from .settings_store import get_setting
        if get_setting("schedule_skip_today") == "true":
            logger.info("SKIP: [Job4] 비거래일 — 하이브리드 스크리닝 스킵")
            return
    except Exception:
        pass

    try:
        from .engine.hybrid_screening import run_hybrid_screening
        result = await run_hybrid_screening()
        logger.info(
            "SUCCESS: [Job4] 하이브리드 스크리닝 완료 output=%d provider=%s confidence=%.2f",
            result.get("output_count", 0),
            result.get("provider", ""),
            result.get("overall_confidence", 0.0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job4] 하이브리드 스크리닝 실패 — reason=%s", exc)


async def job_daily_plan() -> None:
    """Job 5 (08:45 KST): Daily Plan 자동 생성 (S5 구현).

    S4 스크리닝 결과를 LLM에 넘겨 오늘의 Daily Trading Plan을 생성하고 저장한다.
    """
    today = _today_kst()
    logger.info("START: [Job5] Daily Plan 자동 생성 (%s KST)", today)
    try:
        from .settings_store import get_setting
        if get_setting("schedule_skip_today") == "true":
            logger.info("SKIP: [Job5] 비거래일 — Daily Plan 생성 스킵")
            return
    except Exception:
        pass

    try:
        from .engine.daily_plan import run_daily_plan_generation
        result = await run_daily_plan_generation()
        logger.info("SUCCESS: [Scheduler] S5 Daily Plan result=%s", result)
    except Exception as exc:
        logger.error("FAIL: [Scheduler] S5 Daily Plan error=%s", exc)


async def job_decision_engine_start() -> None:
    """Job 6 (09:00 KST): S6 Decision Engine 활성화 + WS 연결."""
    logger.info("START: [Job6] Decision Engine 활성화 (09:00 KST)")
    try:
        from .settings_store import get_setting
        if get_setting("schedule_skip_today") == "true":
            logger.info("SKIP: [Job6] 비거래일 — Decision Engine 활성화 스킵")
            return
    except Exception:
        pass

    try:
        from .engine.decision_engine import decision_engine
        result = await decision_engine.activate()
        logger.info(
            "SUCCESS: [Job6] Decision Engine active=%s candidates=%s",
            result.get("ok"),
            result.get("candidates", 0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job6] Decision Engine 활성화 실패 — reason=%s", exc)


async def job_decision_engine_stop() -> None:
    """Job 9 (15:20 KST): S6 비활성화 + WS 종료."""
    logger.info("START: [Job9] Decision Engine 비활성화 (15:20 KST)")
    try:
        from .engine.decision_engine import decision_engine
        await decision_engine.deactivate()
        logger.info("SUCCESS: [Job9] Decision Engine 비활성화 완료")
    except Exception as exc:
        logger.error("FAIL: [Job9] 비활성화 실패 — reason=%s", exc)


async def job_eod_liquidation() -> None:
    """Job S9 (15:20 KST): 당일 포지션 전량 청산 후 Decision Engine을 종료한다."""
    logger.info("START: [Job S9] 당일 청산 (15:20 KST)")
    try:
        from .engine.eod_liquidation import run_eod_liquidation

        result = await run_eod_liquidation()
        logger.info("SUCCESS: [Job S9] 청산 완료 liquidated=%d", result.get("liquidated", 0))
    except Exception as exc:
        logger.error("FAIL: [Job S9] 청산 실패 — reason=%s", exc)

    try:
        from .engine.decision_engine import decision_engine

        await decision_engine.deactivate()
        logger.info("SUCCESS: [Job S9] Decision Engine 비활성화 완료")
    except Exception as exc:
        logger.error("FAIL: [Job S9] Decision Engine 비활성화 실패 — reason=%s", exc)


async def job_data_backup() -> None:
    """Job S10 (18:00 KST): 당일 거래 결과 집계 + DB 백업."""
    logger.info("START: [Job S10] 당일 거래 요약 + DB 백업 (18:00 KST)")
    try:
        from .engine.daily_summary import run_daily_summary
        result = await run_daily_summary()
        logger.info(
            "SUCCESS: [Job S10] 완료 orders=%d pnl=%.0f backup=%s",
            result.get("total_orders", 0),
            result.get("realized_pnl", 0),
            result.get("backup", {}).get("ok"),
        )
    except Exception as exc:
        logger.error("FAIL: [Job S10] 실패 — reason=%s", exc)


async def job_review_audit() -> None:
    """Job S10 Review & Audit (16:00 KST): 당일 매매 결과를 분석한다."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: [Job ReviewAudit] S10 Review & Audit (%s KST)", today)
    try:
        from .engine.review_audit import run_review_audit

        result = await run_review_audit(today)
        logger.info(
            "SUCCESS: [Job ReviewAudit] 완료 trades=%d pnl=%.4f",
            result.get("total_trades", 0),
            result.get("total_pnl", 0.0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job ReviewAudit] 실패 — reason=%s", exc)


async def job_learning_memory() -> None:
    """Job S11 Learning Memory Builder (16:30 KST): 리뷰 결과를 학습 메모리로 저장한다."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: [Job LearningMemory] S11 Learning Memory Builder (%s KST)", today)
    try:
        from .engine.learning_memory import run_learning_memory_builder

        result = await run_learning_memory_builder(today)
        logger.info(
            "SUCCESS: [Job LearningMemory] 완료 ok=%s memories=%d",
            result.get("ok"),
            result.get("memory_count", 0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job LearningMemory] 실패 — reason=%s", exc)


async def job_us_market_watch() -> None:
    """Job S11 (22:00 KST): 미국 장중 지표 수집 + DB 저장."""
    logger.info("START: [Job S11] 미국장 관찰 (22:00 KST)")
    try:
        from .engine.us_market_watch import run_us_market_watch
        result = await run_us_market_watch()
        logger.info(
            "SUCCESS: [Job S11] 완료 sp500=%s nasdaq=%s usdkrw=%s",
            result.get("sp500_chg_pct"),
            result.get("nasdaq_chg_pct"),
            result.get("usdkrw_rate"),
        )
    except Exception as exc:
        logger.error("FAIL: [Job S11] 실패 — reason=%s", exc)


# ---------------------------------------------------------------------------
# 스케줄러 싱글턴
# ---------------------------------------------------------------------------


def _build_scheduler() -> AsyncIOScheduler:
    """AsyncIOScheduler를 생성하고 전체 job을 등록해 반환한다.

    timezone은 Asia/Seoul로 고정한다.
    job 실패 시 예외가 외부로 전파되지 않도록 각 job 함수에서 try/except 처리한다.
    """
    schedule_times = {
        "s1": "07:45",
        "s2": "08:00",
        "s3": "08:15",
        "s4": "08:30",
        "s5": "08:40",
        "s6": "09:45",
        "s9": "15:20",
        "s10": "18:00",
        "s11": "22:00",
        "backup": "18:00",
        "us_watch": "22:00",
    }
    try:
        from .settings_store import list_settings

        saved = {
            item["key"]: item["value"]
            for item in list_settings()
            if isinstance(item.get("key"), str) and item["key"].startswith("schedule_")
        }
        for key in schedule_times:
            db_key = f"schedule_{key}_time"
            if isinstance(saved.get(db_key), str):
                schedule_times[key] = saved[db_key]
        logger.info("INFO: Scheduler 시간 로드 times=%s", schedule_times)
    except Exception as exc:
        logger.warning("WARN: Scheduler settings 로드 실패 — 기본값 사용 reason=%s", exc)

    def _parse_time(setting_key: str) -> tuple[int, int]:
        """Parse HH:MM scheduler settings, falling back to the built-in default on invalid values."""
        raw_time = schedule_times[setting_key]
        try:
            hour_text, minute_text = raw_time.split(":", maxsplit=1)
            hour = int(hour_text)
            minute = int(minute_text)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError(f"out of range: {raw_time}")
            return hour, minute
        except Exception as exc:
            logger.warning("WARN: Scheduler invalid time key=%s value=%s reason=%s", setting_key, raw_time, exc)
            fallback = {
                "s1": (7, 45),
                "s2": (8, 0),
                "s3": (8, 15),
                "s4": (8, 30),
                "s5": (8, 40),
                "s6": (9, 45),
                "s9": (15, 20),
                "s10": (18, 0),
                "s11": (22, 0),
                "backup": (18, 0),
                "us_watch": (22, 0),
            }
            return fallback[setting_key]

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    hour, minute = _parse_time("s1")
    scheduler.add_job(
        job_refresh_kis_token,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_refresh_kis_token",
        name="KIS 토큰 선제 갱신",
        replace_existing=True,
    )
    hour, minute = _parse_time("s2")
    scheduler.add_job(
        job_market_tone_analysis,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_market_tone_analysis",
        name="시장 톤 분석",
        replace_existing=True,
    )
    hour, minute = _parse_time("s3")
    scheduler.add_job(
        job_universe_filter,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_universe_filter",
        name="유니버스 필터",
        replace_existing=True,
    )
    hour, minute = _parse_time("s4")
    scheduler.add_job(
        job_hybrid_screening,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_hybrid_screening",
        name="하이브리드 스크리닝",
        replace_existing=True,
    )
    hour, minute = _parse_time("s5")
    scheduler.add_job(
        job_daily_plan,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_daily_plan",
        name="Daily Plan 자동 생성",
        replace_existing=True,
    )
    hour, minute = _parse_time("s6")
    scheduler.add_job(
        job_decision_engine_start,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_decision_engine_start",
        name="Decision Engine 활성화",
        replace_existing=True,
    )
    hour, minute = _parse_time("s9")
    scheduler.add_job(
        job_eod_liquidation,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_eod_liquidation",
        name="당일 청산",
        replace_existing=True,
    )
    hour, minute = _parse_time("backup")
    scheduler.add_job(
        job_data_backup,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_data_backup",
        name="데이터 백업",
        replace_existing=True,
    )
    hour, minute = _parse_time("s10")
    scheduler.add_job(
        job_review_audit,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_review_audit",
        name="S10 Review & Audit",
        replace_existing=True,
    )
    hour, minute = _parse_time("s11")
    scheduler.add_job(
        job_learning_memory,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_learning_memory",
        name="S11 Learning Memory Builder",
        replace_existing=True,
    )
    hour, minute = _parse_time("us_watch")
    scheduler.add_job(
        job_us_market_watch,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_us_market_watch",
        name="야간 미국장 관찰",
        replace_existing=True,
    )

    return scheduler


# 전역 싱글턴 — FastAPI lifespan에서 start/stop 호출
scheduler_instance: AsyncIOScheduler = _build_scheduler()
