"""Backend application entrypoint (modular router composition)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes.alerts import router as alerts_router
from .api.routes.account import router as account_router
from .api.routes.auth import router as auth_router
from .api.routes.scheduler import router as scheduler_router
from .api.routes.market_tone import router as market_tone_router
from .api.routes.orders import router as orders_router
from .api.routes.pipeline import router as pipeline_router
from .api.routes.autotrade import router as autotrade_router
from .api.routes.bot import router as bot_router
from .api.routes.rulepack import router as rulepack_router
from .api.routes.rulepack_gen import router as rulepack_gen_router
from .api.routes.engine_test import router as engine_test_router
from .api.routes.console import router as console_router
from .api.routes.decision import router as decision_router
from .api.routes.fundamental import router as fundamental_router
from .api.routes.health import router as health_router
from .api.routes.kis import router as kis_router
from .api.routes.meta import router as meta_router
from .api.routes.realtime import router as realtime_router
from .api.routes.sim import router as sim_router
from .api.routes.strategy import router as strategy_router
from .api.routes.testing import router as testing_router
from .api.routes.settings import router as settings_router
from .api.routes.trades import router as trades_router
from .api.routes.trading_data import router as trading_data_router
from .api.routes.screening import router as screening_router
from .api.routes.rule import router as rule_router
from .api.routes.daily_plan import router as daily_plan_router
from .api.routes.data_quality import router as data_quality_router
from .api.routes.alert_center import router as alert_center_router
from .api.routes.human_approval import router as human_approval_router
from .api.routes.expert_knowledge import router as expert_knowledge_router
from .api.routes.learning_memory import router as learning_memory_router
from .api.routes.review_audit import router as review_audit_router
from .api.routes.shadow_trading import router as shadow_trading_router
from .api.routes.missed_opportunity import router as missed_opportunity_router
from .api.routes.false_positive import router as false_positive_router
from .api.routes.confidence_calibration import router as confidence_calibration_router
from .api.routes.funnel import router as funnel_router
from .api.routes.symbol_override import router as symbol_override_router
from .api.routes.trading_monitor import router as trading_monitor_router
from .api.routes.universe import router as universe_router, filter_router as universe_filter_router
from .config import settings, validate_config
from .services.auth_service import initialize_auth
from .services.db import initialize_database
from .services.scheduler import scheduler_instance

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("BackendServer")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("START: Backend API Server")
    validate_config()
    initialize_database()
    initialize_auth()
    scheduler_instance.start()
    logger.info("SUCCESS: Scheduler started (%d jobs registered)", len(scheduler_instance.get_jobs()))
    yield
    scheduler_instance.shutdown(wait=False)
    logger.info("SUCCESS: Scheduler stopped")
    logger.info("SUCCESS: Backend API Server Shutdown")


app = FastAPI(title="Stock Trading Bot API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(console_router)
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(account_router)
app.include_router(alerts_router)
app.include_router(meta_router)
app.include_router(kis_router)
app.include_router(universe_router)
app.include_router(universe_filter_router)
app.include_router(screening_router)
app.include_router(rulepack_gen_router)
app.include_router(engine_test_router)
app.include_router(realtime_router)
app.include_router(fundamental_router)
app.include_router(sim_router)
app.include_router(testing_router)
app.include_router(strategy_router)
app.include_router(autotrade_router)
app.include_router(bot_router)
app.include_router(rulepack_router)
app.include_router(settings_router)
app.include_router(trades_router)
app.include_router(trading_data_router)
app.include_router(scheduler_router)
app.include_router(market_tone_router)
app.include_router(decision_router)
app.include_router(orders_router)
app.include_router(pipeline_router)
app.include_router(rule_router)
app.include_router(daily_plan_router)
app.include_router(data_quality_router)
app.include_router(alert_center_router)
app.include_router(human_approval_router)
app.include_router(expert_knowledge_router)
app.include_router(review_audit_router)
app.include_router(learning_memory_router)
app.include_router(shadow_trading_router)
app.include_router(missed_opportunity_router)
app.include_router(false_positive_router)
app.include_router(confidence_calibration_router)
app.include_router(funnel_router)
app.include_router(symbol_override_router)
app.include_router(trading_monitor_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, factory=False)
