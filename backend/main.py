"""Backend application entrypoint (modular router composition)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes.alerts import router as alerts_router
from .api.routes.auth import router as auth_router
from .api.routes.scheduler import router as scheduler_router
from .api.routes.market_tone import router as market_tone_router
from .api.routes.autotrade import router as autotrade_router
from .api.routes.bot import router as bot_router
from .api.routes.rulepack import router as rulepack_router
from .api.routes.rulepack_gen import router as rulepack_gen_router
from .api.routes.engine_test import router as engine_test_router
from .api.routes.console import router as console_router
from .api.routes.fundamental import router as fundamental_router
from .api.routes.health import router as health_router
from .api.routes.kis import router as kis_router
from .api.routes.meta import router as meta_router
from .api.routes.realtime import router as realtime_router
from .api.routes.sim import router as sim_router
from .api.routes.strategy import router as strategy_router
from .api.routes.testing import router as testing_router
from .api.routes.settings import router as settings_router
from .api.routes.trading_data import router as trading_data_router
from .api.routes.screening import router as screening_router
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
app.include_router(trading_data_router)
app.include_router(scheduler_router)
app.include_router(market_tone_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, factory=False)
