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
    # 시세 데이터 수집 전용 키(선택, 2026-10-06) — 실전계좌 앱키를 넣으면 과거 분봉/일봉 수집이
    # 매매 키(모의)와 별도 호출한도(실전 ~20rps)로 돈다. 주문에는 절대 쓰지 않는다(조회 전용).
    # 비어 있으면 수집기는 매매 키(KIS_APP_KEY·KIS_URL)를 저속(1rps)으로 쓴다.
    KIS_DATA_APP_KEY: str = ""
    KIS_DATA_APP_SECRET: str = ""
    KIS_DATA_URL: str = "https://openapi.koreainvestment.com:9443"
    KIS_DATA_RPS: Optional[float] = None
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
    KIS_RATE_LIMIT_VIRTUAL_RPS: float = 3.0  # 모의(VTS)는 공식상 실전(20)보다 현저히 낮음. 15→5(2026-06-16)→3(2026-08-31): 5에서도 EGW00201 지속, 아침 prep 루프 지연(misfire) 기여. 모의 공식 ~2rps에 근접. 장중 응답성 위해 2 대신 3.
    KIS_BULK_CONCURRENCY: Optional[int] = None
    APP_DB_PATH: str = "data/stock_trading_bot.sqlite3"
    APP_ADMIN_USERNAME: str = "admin"
    APP_ADMIN_PASSWORD: str = ""
    APP_SESSION_TTL_HOURS: int = 12

    # [LLM 제거 2026-08-05] Anthropic/Gemini/Groq/OpenAI 키 필드 삭제.
    # 전략·시황·복기 전부 결정론화되어 LLM을 호출하지 않는다. .env의 잔여 키는 extra=ignore로 무시된다.

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
