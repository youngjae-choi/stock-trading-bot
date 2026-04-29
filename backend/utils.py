import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Dict, Optional

from .config import settings

logger = logging.getLogger("BackendUtils")

KST = timezone(timedelta(hours=9))
KIS_NEW_CUSTOMER_POLICY_EFFECTIVE_AT = datetime(2026, 4, 3, 17, 0, 0, tzinfo=KST)


class RateLimiter:
    """Simple rate limiter for KIS API (e.g., 20 requests per second)."""

    def __init__(self, requests_per_second: float = 20.0):
        self._requests_per_second = max(0.1, float(requests_per_second))
        self.delay = 1.0 / self._requests_per_second
        self.last_call = 0.0
        self.lock = asyncio.Lock()
        self.last_rate_limit_at = 0.0

    async def wait(self):
        async with self.lock:
            elapsed = time.perf_counter() - self.last_call
            if elapsed < self.delay:
                await asyncio.sleep(self.delay - elapsed)
            self.last_call = time.perf_counter()

    def update_requests_per_second(self, requests_per_second: float):
        self._requests_per_second = max(0.1, float(requests_per_second))
        self.delay = 1.0 / self._requests_per_second

    def mark_rate_limited(self):
        self.last_rate_limit_at = time.time()

    def snapshot(self) -> Dict[str, float]:
        """Expose the active limiter settings for diagnostics and health responses."""
        return {
            "configured_requests_per_second": self._requests_per_second,
            "delay_seconds": self.delay,
            "last_rate_limited_at": self.last_rate_limit_at,
        }


def _is_virtual_trading() -> bool:
    """Return whether the configured KIS endpoint points to the virtual server."""
    return "openapivts" in settings.KIS_URL.lower()


def _normalize_profile(profile: str) -> str:
    """Normalize operator-supplied profile names to stable internal values."""
    normalized = profile.strip().lower().replace("-", "_")
    aliases = {
        "new": "new_account",
        "new_customer": "new_account",
        "standard": "standard",
        "default": "standard",
        "real": "standard",
        "mock": "virtual",
        "demo": "virtual",
    }
    return aliases.get(normalized, normalized or "auto")


def _parse_service_apply_date(raw_value: str) -> Optional[datetime]:
    """Parse the KIS service apply date from the environment in KST."""
    text = raw_value.strip()
    if not text:
        return None
    try:
        if "T" in text:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            parsed = datetime.fromisoformat(f"{text}T00:00:00")
    except ValueError:
        logger.warning("WARN: invalid KIS_SERVICE_APPLY_DATE=%s. Expected YYYY-MM-DD or ISO datetime.", text)
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def get_kis_rate_limit_status(now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Resolve the active KIS rate-limit profile.

    Params:
    - now: Optional timestamp override used by tests or diagnostics.
    """
    now_kst = now.astimezone(KST) if now is not None else datetime.now(tz=KST)
    if _is_virtual_trading():
        return {
            "mode": "virtual",
            "profile": "virtual",
            "requests_per_second": float(settings.KIS_RATE_LIMIT_VIRTUAL_RPS),
            "applied_requests_per_second": float(settings.KIS_RATE_LIMIT_VIRTUAL_RPS),
            "policy_limit_per_second": None,
            "policy_window_days": 0,
            "source": "virtual_default",
            "service_apply_date": None,
            "days_since_apply": None,
            "policy_effective_at": KIS_NEW_CUSTOMER_POLICY_EFFECTIVE_AT.isoformat(),
            "note": "모의투자 서버는 신규 고객 3일 3 TPS 정책 대상이 아닙니다.",
        }

    if settings.KIS_RATE_LIMIT_RPS is not None:
        return {
            "mode": "real",
            "profile": "override",
            "requests_per_second": float(settings.KIS_RATE_LIMIT_RPS),
            "applied_requests_per_second": float(settings.KIS_RATE_LIMIT_RPS),
            "policy_limit_per_second": 3.0 if _normalize_profile(settings.KIS_RATE_LIMIT_PROFILE) == "new_account" else 20.0,
            "policy_window_days": 3 if _normalize_profile(settings.KIS_RATE_LIMIT_PROFILE) == "new_account" else 0,
            "source": "KIS_RATE_LIMIT_RPS",
            "service_apply_date": settings.KIS_SERVICE_APPLY_DATE or None,
            "days_since_apply": None,
            "policy_effective_at": KIS_NEW_CUSTOMER_POLICY_EFFECTIVE_AT.isoformat(),
            "note": "운영자 고정값(KIS_RATE_LIMIT_RPS)이 자동 프로필보다 우선합니다.",
        }

    profile = _normalize_profile(settings.KIS_RATE_LIMIT_PROFILE)
    apply_at = _parse_service_apply_date(settings.KIS_SERVICE_APPLY_DATE)
    policy_active = now_kst >= KIS_NEW_CUSTOMER_POLICY_EFFECTIVE_AT

    if profile == "new_account":
        resolved_profile = "new_account"
        source = "KIS_RATE_LIMIT_PROFILE"
        days_since_apply = None
    elif profile == "standard":
        resolved_profile = "standard"
        source = "KIS_RATE_LIMIT_PROFILE"
        days_since_apply = None
    elif apply_at is not None:
        days_since_apply = (now_kst.date() - apply_at.date()).days
        resolved_profile = "new_account" if days_since_apply < 3 else "standard"
        source = "KIS_SERVICE_APPLY_DATE"
    elif policy_active:
        resolved_profile = "new_account"
        source = "auto_fallback"
        days_since_apply = None
    else:
        resolved_profile = "standard"
        source = "pre_policy_default"
        days_since_apply = None

    requests_per_second = (
        float(settings.KIS_RATE_LIMIT_NEW_ACCOUNT_RPS)
        if resolved_profile == "new_account"
        else float(settings.KIS_RATE_LIMIT_STANDARD_RPS)
    )
    policy_limit_per_second = 3.0 if resolved_profile == "new_account" else 20.0
    note = {
        "new_account": "실전 신규 계정은 신청일 포함 3일간 정책 한도 3 TPS, 내부 limiter는 보수적으로 2 TPS로 시작합니다.",
        "standard": "실전 계정 기본 프로필은 20 TPS입니다.",
    }[resolved_profile]
    if source == "auto_fallback":
        note = (
            "KIS_SERVICE_APPLY_DATE가 없어 신규 계정 보수 프로필로 시작합니다. "
            "3일 경과 후 자동 상향을 원하면 신청일을 설정하세요."
        )

    return {
        "mode": "real",
        "profile": resolved_profile,
        "requests_per_second": requests_per_second,
        "applied_requests_per_second": requests_per_second,
        "policy_limit_per_second": policy_limit_per_second,
        "policy_window_days": 3 if resolved_profile == "new_account" else 0,
        "source": source,
        "service_apply_date": apply_at.date().isoformat() if apply_at is not None else None,
        "days_since_apply": days_since_apply,
        "policy_effective_at": KIS_NEW_CUSTOMER_POLICY_EFFECTIVE_AT.isoformat(),
        "note": note,
    }


def kis_bulkhead_concurrency() -> int:
    """
    Return the default bulkhead concurrency for KIS fan-out calls.

    신규 실전 계정은 EGW00201 위험이 높으므로 동시성을 더 낮게 시작한다.
    """
    if settings.KIS_BULK_CONCURRENCY is not None:
        return max(1, int(settings.KIS_BULK_CONCURRENCY))

    status = get_kis_rate_limit_status()
    if status["profile"] == "virtual":
        return 8
    if status["profile"] == "new_account":
        return 2
    return 6


_kis_rate_limit_status = get_kis_rate_limit_status()
kis_rate_limiter = RateLimiter(requests_per_second=_kis_rate_limit_status["requests_per_second"])
logger.info(
    "INFO: KIS rate limit profile mode=%s profile=%s rps=%.2f source=%s apply_date=%s days_since_apply=%s",
    _kis_rate_limit_status["mode"],
    _kis_rate_limit_status["profile"],
    _kis_rate_limit_status["requests_per_second"],
    _kis_rate_limit_status["source"],
    _kis_rate_limit_status["service_apply_date"],
    _kis_rate_limit_status["days_since_apply"],
)


def get_kis_rate_limiter_runtime_status(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Combine resolved KIS policy data with the currently instantiated limiter state."""
    status = get_kis_rate_limit_status(now)
    limiter_snapshot = kis_rate_limiter.snapshot()
    status["limiter"] = limiter_snapshot
    status["limiter_matches_policy"] = (
        abs(limiter_snapshot["configured_requests_per_second"] - status["applied_requests_per_second"]) < 1e-9
    )
    return status


def retry_on_kis_error(retries: int = 3, backoff: float = 1.0):
    """
    Decorator to retry on specific KIS errors like EGW00201 (Traffic) or EGW00301 (Timeout).
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    error_str = str(e)
                    # EGW00201: Traffic overload, EGW00301: Request timeout
                    if "EGW00201" in error_str or "EGW00301" in error_str:
                        if "EGW00201" in error_str:
                            kis_rate_limiter.mark_rate_limited()
                        wait_time = backoff * (2**attempt)
                        logger.warning(
                            "RETRY: KIS API error code=%s func=%s attempt=%s/%s wait=%.2fs active_rps=%.2f reason=%s",
                            "EGW00201" if "EGW00201" in error_str else "EGW00301",
                            func.__name__,
                            attempt + 1,
                            retries,
                            wait_time,
                            kis_rate_limiter._requests_per_second,
                            error_str,
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        raise e
            logger.error("FAIL: Maximum retries reached for %s reason=%s", func.__name__, str(last_exception))
            raise last_exception

        return wrapper

    return decorator
