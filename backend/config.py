import logging
from typing import Dict, List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # KIS API Configuration
    KIS_CANO: str = ""           # 종합계좌번호 (8자리)
    KIS_ACNT_PRDT_CD: str = "01" # 계좌상품코드 (2자리, 보통 01)
    KIS_APP_KEY: str = ""        # 한국투자증권 앱 키
    KIS_APP_SECRET: str = ""     # 한국투자증권 앱 시크릿
    KIS_URL: str = "https://openapi.koreainvestment.com:9443" # 실전/모의 URL
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Operational Settings
    KIS_DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    KIS_SERVICE_APPLY_DATE: str = ""
    KIS_RATE_LIMIT_PROFILE: str = "auto"
    KIS_RATE_LIMIT_RPS: Optional[float] = None
    KIS_RATE_LIMIT_NEW_ACCOUNT_RPS: float = 2.0
    KIS_RATE_LIMIT_STANDARD_RPS: float = 20.0
    KIS_RATE_LIMIT_VIRTUAL_RPS: float = 15.0
    KIS_BULK_CONCURRENCY: Optional[int] = None
    APP_DB_PATH: str = "data/stock_trading_bot.sqlite3"
    APP_ADMIN_USERNAME: str = "admin"
    APP_ADMIN_PASSWORD: str = ""
    APP_SESSION_TTL_HOURS: int = 12

    # LLM API Keys (S2: 시장 톤 분석 — fallback 순서: Gemini → Groq → OpenAI)
    GEMINI_API_KEY: str = ""   # Google Gemini API key
    GROQ_API_KEY: str = ""     # Groq API key
    OPENAI_API_KEY: str = ""   # OpenAI GPT fallback key

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

def get_missing_kis_config() -> List[str]:
    """Return the missing critical KIS configuration keys."""
    missing: List[str] = []
    if not settings.KIS_APP_KEY:
        missing.append("KIS_APP_KEY")
    if not settings.KIS_APP_SECRET:
        missing.append("KIS_APP_SECRET")
    if not settings.KIS_CANO:
        missing.append("KIS_CANO")
    if not settings.KIS_ACNT_PRDT_CD:
        missing.append("KIS_ACNT_PRDT_CD")
    return missing

def validate_config() -> bool:
    """Validate critical KIS configuration."""
    missing = get_missing_kis_config()
    if missing:
        logging.warning(f"FAIL: Missing KIS configuration: {', '.join(missing)}. API calls will fail.")
        return False
    logging.info("SUCCESS: KIS configuration loaded.")
    return True

def get_kis_config_status() -> Dict[str, object]:
    """Expose KIS configuration status for API responses."""
    missing = get_missing_kis_config()
    return {
        "configured": len(missing) == 0,
        "missing": missing,
    }

def mask_secret(secret: str) -> str:
    """Mask sensitive information for logging."""
    if not secret: return "N/A"
    if len(secret) <= 8: return "*" * len(secret)
    return f"{secret[:4]}****{secret[-4:]}"


def telegram_enabled() -> bool:
    """Return whether Telegram notification credentials are configured."""
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)
