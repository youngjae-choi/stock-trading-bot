"""APScheduler 기반 하루 사이클 자동매매 스케줄러.

S1 단계: Scheduler 뼈대 + KIS 토큰 선제 갱신 (07:45 KST).
S2~S13 단계에서 placeholder job들이 실 구현으로 교체된다.

전역 싱글턴 `scheduler_instance`을 통해 FastAPI lifespan에서 start/stop한다.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .kis.common.client import kis_client

logger = logging.getLogger("Scheduler")

# ---------------------------------------------------------------------------
# Job 함수
# ---------------------------------------------------------------------------


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


async def job_market_tone_analysis() -> None:
    """Job 2 (08:00 KST): LLM을 통한 시장 톤 분석 (S2 구현).

    Gemini → Groq → OpenAI GPT 순서로 fallback 호출한다.
    분석 실패 시 neutral 기본값을 저장하고 서버는 계속 실행된다.
    """
    logger.info("START: [Job2] 시장 톤 분석 (08:00 KST)")
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
    logger.info("START: [Job3] 유니버스 필터 (08:15 KST)")
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
    logger.info("START: [Job4] 하이브리드 스크리닝 (08:30 KST)")
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


async def job_rulepack_generation() -> None:
    """Job 5 (08:45 KST): RulePack 자동 생성 (S5 구현).

    S4 스크리닝 결과를 LLM에 넘겨 오늘의 RulePack JSON을 생성하고 자동 활성화한다.
    """
    logger.info("START: [Job5] RulePack 자동 생성 (08:45 KST)")
    try:
        from .engine.rulepack_generation import run_rulepack_generation
        result = await run_rulepack_generation()
        logger.info(
            "SUCCESS: [Job5] RulePack 생성 완료 rulepack_id=%s provider=%s caps=%d",
            result.get("rulepack_id", ""),
            result.get("provider", ""),
            result.get("cap_applied_count", 0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job5] RulePack 생성 실패 — reason=%s", exc)


async def job_intraday_liquidation() -> None:
    """Job 6 (15:20 KST): 당일 청산 placeholder.

    실 구현은 S9 단계에서 추가된다.
    """
    logger.info("START: [Job6] 당일 청산 placeholder (실 구현: S9)")
    logger.info("SUCCESS: [Job6] 당일 청산 placeholder 완료")


async def job_data_backup() -> None:
    """Job 7 (18:00 KST): 데이터 백업 placeholder.

    실 구현은 S12 단계에서 추가된다.
    """
    logger.info("START: [Job7] 데이터 백업 placeholder (실 구현: S12)")
    logger.info("SUCCESS: [Job7] 데이터 백업 placeholder 완료")


async def job_us_market_watch() -> None:
    """Job 8 (22:00 KST): 야간 미국장 관찰 placeholder.

    실 구현은 S13 단계에서 추가된다.
    """
    logger.info("START: [Job8] 야간 미국장 관찰 placeholder (실 구현: S13)")
    logger.info("SUCCESS: [Job8] 야간 미국장 관찰 placeholder 완료")


# ---------------------------------------------------------------------------
# 스케줄러 싱글턴
# ---------------------------------------------------------------------------


def _build_scheduler() -> AsyncIOScheduler:
    """AsyncIOScheduler를 생성하고 전체 job을 등록해 반환한다.

    timezone은 Asia/Seoul로 고정한다.
    job 실패 시 예외가 외부로 전파되지 않도록 각 job 함수에서 try/except 처리한다.
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    scheduler.add_job(
        job_refresh_kis_token,
        CronTrigger(hour=7, minute=45, timezone="Asia/Seoul"),
        id="job_refresh_kis_token",
        name="KIS 토큰 선제 갱신",
        replace_existing=True,
    )
    scheduler.add_job(
        job_market_tone_analysis,
        CronTrigger(hour=8, minute=0, timezone="Asia/Seoul"),
        id="job_market_tone_analysis",
        name="시장 톤 분석",
        replace_existing=True,
    )
    scheduler.add_job(
        job_universe_filter,
        CronTrigger(hour=8, minute=15, timezone="Asia/Seoul"),
        id="job_universe_filter",
        name="유니버스 필터",
        replace_existing=True,
    )
    scheduler.add_job(
        job_hybrid_screening,
        CronTrigger(hour=8, minute=30, timezone="Asia/Seoul"),
        id="job_hybrid_screening",
        name="하이브리드 스크리닝",
        replace_existing=True,
    )
    scheduler.add_job(
        job_rulepack_generation,
        CronTrigger(hour=8, minute=45, timezone="Asia/Seoul"),
        id="job_rulepack_generation",
        name="RulePack 자동 생성",
        replace_existing=True,
    )
    scheduler.add_job(
        job_intraday_liquidation,
        CronTrigger(hour=15, minute=20, timezone="Asia/Seoul"),
        id="job_intraday_liquidation",
        name="당일 청산",
        replace_existing=True,
    )
    scheduler.add_job(
        job_data_backup,
        CronTrigger(hour=18, minute=0, timezone="Asia/Seoul"),
        id="job_data_backup",
        name="데이터 백업",
        replace_existing=True,
    )
    scheduler.add_job(
        job_us_market_watch,
        CronTrigger(hour=22, minute=0, timezone="Asia/Seoul"),
        id="job_us_market_watch",
        name="야간 미국장 관찰",
        replace_existing=True,
    )

    return scheduler


# 전역 싱글턴 — FastAPI lifespan에서 start/stop 호출
scheduler_instance: AsyncIOScheduler = _build_scheduler()
