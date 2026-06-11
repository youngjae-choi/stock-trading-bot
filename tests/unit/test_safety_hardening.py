"""실계좌 전환 안전벨트(B3) — SQLite WAL + KIS rate-limit 동적 감속 + 일중손실 자동 긴급정지.

운영 DB 미접촉: settings.APP_DB_PATH를 임시 파일로 monkeypatch.
- B3-1: get_connection()이 WAL 저널모드 + busy_timeout=5000을 적용하는지
- B3-2: mark_rate_limited() 후 60초 동안 적용 RPS 절반(최소 1.0), 만료 후 자동 원복
- B3-3: ops_watchdog auto_halt 체크 — 일중손실 임계 도달 시 신규 매수 차단 + CRITICAL 알림
"""

import datetime as dt

import pytest

import backend.services.engine.ops_watchdog as ow
import backend.utils as utils_mod
from backend.config import settings
from backend.services import db as db_mod
from backend.services.settings_store import get_setting, upsert_setting

# ─────────────────────── B3-1: SQLite WAL ───────────────────────


def test_get_connection_enables_wal(tmp_path, monkeypatch):
    """get_connection 경로의 DB는 journal_mode=wal + busy_timeout=5000 이어야 한다."""
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "wal.sqlite3"))
    conn = db_mod.get_connection()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert int(timeout) == 5000
    finally:
        conn.close()


def test_get_connection_wal_persists_across_connections(tmp_path, monkeypatch):
    """WAL은 DB 영속 속성 — 두 번째 연결에서도 wal 이어야 한다(이미 WAL이면 no-op)."""
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "wal2.sqlite3"))
    first = db_mod.get_connection()
    first.close()
    second = db_mod.get_connection()
    try:
        assert str(second.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    finally:
        second.close()


# ─────────────────────── B3-2: rate-limit 동적 감속 ───────────────────────


def test_mark_rate_limited_halves_rps_then_recovers(monkeypatch):
    """mark_rate_limited 후 60초간 delay 2배(=RPS 절반), 만료 후 자동 원복."""
    fake_now = [1000.0]
    monkeypatch.setattr(utils_mod.time, "monotonic", lambda: fake_now[0])
    limiter = utils_mod.RateLimiter(requests_per_second=4.0)

    # 평상시: 4 RPS → delay 0.25s
    assert limiter.current_delay() == pytest.approx(0.25)

    limiter.mark_rate_limited()
    # 감속 모드: RPS 절반(2.0) → delay 2배(0.5s)
    assert limiter.current_delay() == pytest.approx(0.5)

    # 만료 직전까지는 감속 유지
    fake_now[0] = 1059.9
    assert limiter.current_delay() == pytest.approx(0.5)

    # 60초 경과 후 자동 원복
    fake_now[0] = 1060.1
    assert limiter.current_delay() == pytest.approx(0.25)


def test_throttle_respects_min_rps_floor(monkeypatch):
    """절반 RPS가 1.0 미만이면 최소 1.0 RPS로 바닥 보장."""
    monkeypatch.setattr(utils_mod.time, "monotonic", lambda: 500.0)
    limiter = utils_mod.RateLimiter(requests_per_second=1.5)
    limiter.mark_rate_limited()
    # 절반=0.75 < 최소 1.0 → 적용 RPS 1.0 → delay 1.0s
    assert limiter.current_delay() == pytest.approx(1.0)


def test_snapshot_exposes_throttle_state(monkeypatch):
    """snapshot에 throttled_until/throttle_factor 노출 + 기존 키 보존."""
    fake_now = [2000.0]
    monkeypatch.setattr(utils_mod.time, "monotonic", lambda: fake_now[0])
    limiter = utils_mod.RateLimiter(requests_per_second=4.0)

    snap = limiter.snapshot()
    # 기존 키 보존
    assert snap["configured_requests_per_second"] == pytest.approx(4.0)
    assert snap["delay_seconds"] == pytest.approx(0.25)
    assert "last_rate_limited_at" in snap
    # 신규 키 — 평상시
    assert snap["throttle_factor"] == pytest.approx(1.0)
    assert snap["throttled_until"] == pytest.approx(0.0)

    limiter.mark_rate_limited()
    snap = limiter.snapshot()
    assert snap["throttle_factor"] == pytest.approx(0.5)
    assert snap["throttled_until"] == pytest.approx(2060.0)

    # 만료 후 원복
    fake_now[0] = 2061.0
    snap = limiter.snapshot()
    assert snap["throttle_factor"] == pytest.approx(1.0)


# ─────────────────────── B3-3: 일중손실 자동 긴급정지 ───────────────────────

# 2026-06-08(월)=거래일, 장중 10:00 — auto_halt 게이트(09:05~15:20) 안
_MON_1000 = dt.datetime(2026, 6, 8, 10, 0, tzinfo=ow.KST)
_TD = "2026-06-08"


def _halt_db(tmp_path, monkeypatch):
    """실제 스키마(system_settings/system_alerts 포함)로 임시 DB 초기화."""
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "halt.sqlite3"))
    db_mod.initialize_database()


def _halt_alert_count(td: str) -> int:
    with db_mod.get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM system_alerts WHERE trade_date=? AND title LIKE '%자동 긴급정지%'",
            (td,),
        ).fetchone()
    return int(row[0])


def test_auto_halt_registered_with_intraday_gate():
    """auto_halt 체크가 09:05~15:20 게이트로 레지스트리에 등록되어야 한다."""
    checks = {chk.id: chk for chk in ow._REGISTRY}
    assert "auto_halt" in checks
    chk = checks["auto_halt"]
    assert chk.severity == "CRITICAL"
    assert chk.start_min == 9 * 60 + 5
    assert chk.end_min == 15 * 60 + 20


def test_auto_halt_fires_on_threshold_breach(tmp_path, monkeypatch):
    """① 손실 -6% ≤ 임계 -5% → emergency_halt_enabled=True + CRITICAL 알림."""
    _halt_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_observed_daily_loss_percent", lambda td: (-6.0, "test/equity"))
    result = ow.run_ops_watchdog(now=_MON_1000)
    assert result.get("skipped") is None
    assert get_setting("risk.emergency_halt_enabled", False) is True
    assert _halt_alert_count(_TD) == 1


def test_auto_halt_not_fired_above_threshold(tmp_path, monkeypatch):
    """② 손실 -3% > 임계 -5% → 미발동."""
    _halt_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_observed_daily_loss_percent", lambda td: (-3.0, "test/equity"))
    ow.run_ops_watchdog(now=_MON_1000)
    assert get_setting("risk.emergency_halt_enabled", False) is False
    assert _halt_alert_count(_TD) == 0


def test_auto_halt_skips_when_already_halted(tmp_path, monkeypatch):
    """③ 이미 emergency_halt_enabled=True → 중복 발동/알림 없음."""
    _halt_db(tmp_path, monkeypatch)
    upsert_setting("risk.emergency_halt_enabled", True, "boolean", "테스트 선행 발동", "test")

    def _boom(td):
        raise AssertionError("이미 정지 상태면 손실 조회조차 하지 않아야 함")

    monkeypatch.setattr(ow, "_observed_daily_loss_percent", _boom)
    ow.run_ops_watchdog(now=_MON_1000)
    assert _halt_alert_count(_TD) == 0


def test_auto_halt_disabled_when_threshold_zero(tmp_path, monkeypatch):
    """④ threshold=0(또는 양수) → 체크 비활성."""
    _halt_db(tmp_path, monkeypatch)
    upsert_setting("risk.auto_halt_loss_percent", 0, "number", "자동 긴급정지 임계(비활성)", "test")
    monkeypatch.setattr(ow, "_observed_daily_loss_percent", lambda td: (-99.0, "test/equity"))
    ow.run_ops_watchdog(now=_MON_1000)
    assert get_setting("risk.emergency_halt_enabled", False) is False
    assert _halt_alert_count(_TD) == 0


def test_auto_halt_fail_open_when_unobservable(tmp_path, monkeypatch):
    """관측 불가(None) → 아무것도 안 함(fail-open — preflight 쪽이 fail-closed 담당)."""
    _halt_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_observed_daily_loss_percent", lambda td: (None, "query_failed"))
    ow.run_ops_watchdog(now=_MON_1000)
    assert get_setting("risk.emergency_halt_enabled", False) is False
    assert _halt_alert_count(_TD) == 0
