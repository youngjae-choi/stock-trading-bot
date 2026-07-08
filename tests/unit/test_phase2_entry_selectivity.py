"""Phase 2 — 진입 선별성 강화 회귀 테스트.

배경: 승률 22%·손실거래 4~6건/일 전부 entry_fail. 칼리브레이션/false_positive는
기록만 되고 진입에 반영되지 않았다 (2026-07-08 감사). 세 게이트를 추가한다:
  P2-1 칼리브레이션 게이트 — 누적 실적 나쁜 confidence bin 진입 차단
  P2-2 entry_fail 쿨다운 — 최근 반복 손실 진입 심볼 차단
  P2-3 방어 레짐 confidence 강제 — risk_off/volatile에서 하한 가산+게이트 강제
모든 게이트는 fail-open (조회 실패 시 차단하지 않음).
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.config import settings

_KST = ZoneInfo("Asia/Seoul")


def _today() -> str:
    return datetime.now(_KST).strftime("%Y-%m-%d")


# ──────────────────────────────────────────────
# P2-1: 칼리브레이션 게이트
# ──────────────────────────────────────────────

def _set_bin(conn, label: str, trades: int, wins: int, avg_pnl: float) -> None:
    conn.execute(
        "UPDATE confidence_calibration_bins SET cumulative_trades=?, cumulative_wins=?, "
        "cumulative_avg_pnl=?, last_updated='2026-07-08T18:00:00+09:00' WHERE bin_label=?",
        (trades, wins, avg_pnl, label),
    )


def test_calibration_gate_blocks_bad_bin():
    """표본 충분 + 승률 갭 큰 bin → 차단. 표본 부족/실적 양호 bin → 통과."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/t.sqlite3"):
        from backend.services.db import get_connection, initialize_database
        initialize_database()
        with get_connection() as conn:
            # 60to70: 100건 중 22승(기대 0.60, 실제 0.22 → 갭 0.38) — 차단 대상
            _set_bin(conn, "60to70", 100, 22, 15000.0)
            # 70to80: 100건 중 68승(갭 0.02) + 양의 EV — 통과
            _set_bin(conn, "70to80", 100, 68, 50000.0)
            # 80to90: 10건(표본 부족) 0승 — 통과 (min_samples=30)
            _set_bin(conn, "80to90", 10, 0, -99999.0)

        from backend.services.engine.confidence_calibration import (
            get_blocked_bins,
            is_confidence_blocked,
        )
        blocked = get_blocked_bins(min_samples=30, gap_threshold=0.15)
        assert "60to70" in blocked and blocked["60to70"]["reason"] == "win_rate_gap"
        assert "70to80" not in blocked
        assert "80to90" not in blocked  # 표본 부족

        b, why = is_confidence_blocked(0.65, min_samples=30)   # 0.65 → 60to70
        assert b is True and "60to70" in why
        b2, _ = is_confidence_blocked(0.75, min_samples=30)    # 0.75 → 70to80
        assert b2 is False


def test_calibration_gate_blocks_negative_ev_bin():
    """승률 갭이 작아도 누적 평균손익이 음수면 차단 (EV<0)."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/t.sqlite3"):
        from backend.services.db import get_connection, initialize_database
        initialize_database()
        with get_connection() as conn:
            _set_bin(conn, "70to80", 50, 34, -12000.0)  # 승률 0.68(갭 0.02) but EV<0
        from backend.services.engine.confidence_calibration import get_blocked_bins
        blocked = get_blocked_bins(min_samples=30)
        assert blocked.get("70to80", {}).get("reason") == "negative_ev"


def test_calibration_gate_fail_open_without_db():
    """테이블/DB 접근 불가 시 빈 dict — 차단하지 않는다."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/nonexistent/x.sqlite3"):
        from backend.services.engine.confidence_calibration import is_confidence_blocked
        b, why = is_confidence_blocked(0.65)
        assert b is False and why == ""


def test_calibration_gate_skips_unscored_confidence():
    """confidence<=0(점수 미기록)은 판정 불가 — lt060 bin이 나빠도 차단하지 않는다.

    (신호 대부분이 무점수(기본 0.0)라 lt060 차단 = 엔진 정지가 되는 함정 방지)
    """
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/t.sqlite3"):
        from backend.services.db import get_connection, initialize_database
        initialize_database()
        with get_connection() as conn:
            _set_bin(conn, "lt060", 200, 40, -50000.0)  # 나쁜 bin
        from backend.services.engine.confidence_calibration import is_confidence_blocked
        assert is_confidence_blocked(0.0, min_samples=30) == (False, "")   # 무점수 → 스킵
        b, _ = is_confidence_blocked(0.45, min_samples=30)                 # 실제 저점수 → 차단
        assert b is True


def test_calibration_aggregation_excludes_unscored_signals():
    """run_confidence_calibration은 confidence>0 신호만 집계한다."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/t.sqlite3"):
        from backend.services.db import get_connection, initialize_database
        initialize_database()
        import backend.services.engine.decision_engine as de
        de._ensure_signals_table()
        today = _today()
        with get_connection() as conn:
            for i, (conf, pnl) in enumerate([(0.0, -100.0), (0.0, 50.0), (0.72, 200.0)]):
                conn.execute(
                    "INSERT INTO trading_signals (id, trade_date, symbol, name, signal_type, "
                    "trigger_price, confidence, rule_matched, profile_assigned, status, created_at, realized_pnl) "
                    "VALUES (?, ?, '005930', '', 'BUY', 100, ?, '{}', 'MID_VOL', 'done', ?, ?)",
                    (f"sig-{i}", today, conf, today, pnl),
                )
        from backend.services.engine.confidence_calibration import run_confidence_calibration
        result = run_confidence_calibration(today)
        total = sum(b["trade_count"] for b in result["bins"])
        assert total == 1  # 무점수 2건 제외, 0.72 1건만


# ──────────────────────────────────────────────
# P2-2: entry_fail 쿨다운
# ──────────────────────────────────────────────

def _insert_fp(conn, symbol: str, trade_date: str, fp_type: str = "entry_fail") -> None:
    conn.execute(
        """
        INSERT INTO false_positive_cases
            (id, trade_date, symbol, symbol_name, false_positive_type, entry_reason,
             loss_reason, exit_reason, applied_knowledge_ids, applied_memory_ids, created_at)
        VALUES (?, ?, ?, '', ?, '', '', '', '[]', '[]', ?)
        """,
        (f"fp-{symbol}-{trade_date}", trade_date, symbol, fp_type, trade_date + "T18:00:00+09:00"),
    )


def test_entry_fail_cooldown_counts_recent_only():
    """최근 N일 내 entry_fail만 센다 — 기간 밖·다른 유형은 제외."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/t.sqlite3"):
        from backend.services.db import get_connection, initialize_database
        initialize_database()
        today = _today()
        d1 = (datetime.now(_KST) - timedelta(days=1)).strftime("%Y-%m-%d")
        d5 = (datetime.now(_KST) - timedelta(days=5)).strftime("%Y-%m-%d")
        with get_connection() as conn:
            _insert_fp(conn, "042040", today)
            _insert_fp(conn, "042040", d1)
            _insert_fp(conn, "042040", d5)                      # 3일 밖 — 제외
            _insert_fp(conn, "005930", d1, fp_type="early_exit")  # 다른 유형 — 제외

        from backend.services.engine.false_positive import recent_entry_fail_count
        assert recent_entry_fail_count("042040", days=3) == 2
        assert recent_entry_fail_count("005930", days=3) == 0
        assert recent_entry_fail_count("042040", days=7) == 3


def test_entry_fail_cooldown_fail_open():
    """DB 접근 불가 시 0 — 차단하지 않는다."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/nonexistent/x.sqlite3"):
        from backend.services.engine.false_positive import recent_entry_fail_count
        assert recent_entry_fail_count("042040", days=3) == 0


# ──────────────────────────────────────────────
# 게이트 통합: _entry_gate_block_reason (모든 진입 경로의 단일 길목)
# ──────────────────────────────────────────────

def _gate_settings(overrides=None):
    base = {
        "engine.enforce_new_entry_allowed": True,
        "engine.calibration_gate_enabled": True,
        "engine.calibration_gate_min_samples": 30,
        "engine.calibration_gate_gap": 0.15,
        "engine.entry_fail_cooldown_enabled": True,
        "engine.entry_fail_cooldown_days": 3,
        "engine.entry_fail_cooldown_min_count": 2,
    }
    if overrides:
        base.update(overrides)
    return lambda key, default=None: base.get(key, default)


def _isolate_flash_defense(monkeypatch):
    """게이트 #0(급락 방어)을 비활성으로 고정 — 실 DB의 방어 플래그 상태와 무관하게."""
    import backend.services.engine.intraday_regime_monitor as irm
    monkeypatch.setattr(irm, "is_flash_crash_defense_active", lambda *a, **k: False)


def test_gate_blocks_when_new_entry_not_allowed(monkeypatch):
    import backend.services.engine.decision_engine as de
    import backend.services.regime_set_service as rss
    monkeypatch.setattr(de, "get_setting", _gate_settings())
    _isolate_flash_defense(monkeypatch)
    monkeypatch.setattr(
        rss, "get_today_application",
        lambda d: {"regime_label": "volatile", "applied_settings": {"new_entry_allowed": False}},
    )
    reason = de._entry_gate_block_reason("005930", 0.80)
    assert "new_entry_not_allowed" in reason and "volatile" in reason


def test_gate_respects_enforce_off(monkeypatch):
    """enforce_new_entry_allowed=False(롤백 스위치)면 구동작 — 차단 안 함."""
    import backend.services.engine.confidence_calibration as cc
    import backend.services.engine.decision_engine as de
    import backend.services.engine.false_positive as fp
    import backend.services.regime_set_service as rss
    monkeypatch.setattr(de, "get_setting", _gate_settings({"engine.enforce_new_entry_allowed": False}))
    _isolate_flash_defense(monkeypatch)
    monkeypatch.setattr(
        rss, "get_today_application",
        lambda d: {"regime_label": "volatile", "applied_settings": {"new_entry_allowed": False}},
    )
    monkeypatch.setattr(cc, "is_confidence_blocked", lambda *a, **k: (False, ""))
    monkeypatch.setattr(fp, "recent_entry_fail_count", lambda *a, **k: 0)
    assert de._entry_gate_block_reason("005930", 0.80) == ""


def test_gate_blocks_calibration_bin(monkeypatch):
    import backend.services.engine.confidence_calibration as cc
    import backend.services.engine.decision_engine as de
    import backend.services.regime_set_service as rss
    monkeypatch.setattr(de, "get_setting", _gate_settings())
    _isolate_flash_defense(monkeypatch)
    monkeypatch.setattr(rss, "get_today_application", lambda d: None)
    monkeypatch.setattr(cc, "is_confidence_blocked",
                        lambda conf, min_samples, gap_threshold: (True, "calibration_bin=60to70 win_rate_gap"))
    reason = de._entry_gate_block_reason("005930", 0.65)
    assert "calibration_bin=60to70" in reason


def test_gate_blocks_entry_fail_cooldown(monkeypatch):
    import backend.services.engine.confidence_calibration as cc
    import backend.services.engine.decision_engine as de
    import backend.services.engine.false_positive as fp
    import backend.services.regime_set_service as rss
    monkeypatch.setattr(de, "get_setting", _gate_settings())
    _isolate_flash_defense(monkeypatch)
    monkeypatch.setattr(rss, "get_today_application", lambda d: None)
    monkeypatch.setattr(cc, "is_confidence_blocked", lambda *a, **k: (False, ""))
    monkeypatch.setattr(fp, "recent_entry_fail_count", lambda symbol, days: 2)
    reason = de._entry_gate_block_reason("042040", 0.80)
    assert "entry_fail_cooldown" in reason


def test_gate_passes_clean_symbol(monkeypatch):
    import backend.services.engine.confidence_calibration as cc
    import backend.services.engine.decision_engine as de
    import backend.services.engine.false_positive as fp
    import backend.services.regime_set_service as rss
    monkeypatch.setattr(de, "get_setting", _gate_settings())
    _isolate_flash_defense(monkeypatch)
    monkeypatch.setattr(
        rss, "get_today_application",
        lambda d: {"regime_label": "neutral", "applied_settings": {"new_entry_allowed": True}},
    )
    monkeypatch.setattr(cc, "is_confidence_blocked", lambda *a, **k: (False, ""))
    monkeypatch.setattr(fp, "recent_entry_fail_count", lambda *a, **k: 0)
    assert de._entry_gate_block_reason("005930", 0.80) == ""


def test_gate_fail_open_on_errors(monkeypatch):
    """모든 하위 조회가 예외를 던져도 게이트는 통과(fail-open) — 진입 자체를 막지 않는다."""
    import backend.services.engine.confidence_calibration as cc
    import backend.services.engine.decision_engine as de
    import backend.services.engine.false_positive as fp
    import backend.services.regime_set_service as rss

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(de, "get_setting", _gate_settings())
    _isolate_flash_defense(monkeypatch)
    monkeypatch.setattr(rss, "get_today_application", _boom)
    monkeypatch.setattr(cc, "is_confidence_blocked", _boom)
    monkeypatch.setattr(fp, "recent_entry_fail_count", _boom)
    assert de._entry_gate_block_reason("005930", 0.80) == ""


# ──────────────────────────────────────────────
# P2-3: 방어 레짐 confidence 강제 (_evaluate_rules)
# ──────────────────────────────────────────────

def _rules_env(monkeypatch, *, regime: str, mode: str = "regime_defensive"):
    import backend.services.engine.decision_engine as de
    settings_map = {
        "engine.min_ai_confidence": 0.60,
        "engine.min_confidence_floor": 0.40,
        "engine.confidence_gate_mode": mode,
        "engine.regime_confidence_bonus_risk_off": 0.05,
        "engine.regime_confidence_bonus_volatile": 0.10,
        "engine.min_price_change_pct": 1.5,
        "engine.max_price_change_pct": 8.0,
        "engine.min_volume_ratio": 1.0,
        "engine.entry_start_time": "00:00",
        "engine.entry_end_time": "23:59",
    }
    monkeypatch.setattr(de, "_get_setting_float", lambda key, default: float(settings_map.get(key, default)))
    monkeypatch.setattr(de, "_get_setting_str", lambda key, default: str(settings_map.get(key, default)))
    monkeypatch.setattr(de, "_current_regime_label", lambda ttl_seconds=120.0: regime)
    return de


def test_defensive_regime_enforces_confidence(monkeypatch):
    """risk_off에서 confidence 0.62 < (0.60+0.05) → pass=False."""
    de = _rules_env(monkeypatch, regime="risk_off")
    engine = de.DecisionEngine()
    result = engine._evaluate_rules(
        candidate={"confidence": 0.62},
        final_rule={},
        tick={"change_rate": 2.0, "prev_volume_ratio": 3.0},
    )
    assert result["pass"] is False
    assert "confidence 미달" in result["reason"]
    assert result["observed_values"]["ai_confidence_min"] >= 0.65


def test_neutral_regime_keeps_confidence_observational(monkeypatch):
    """neutral에서는 confidence 낮아도 confidence 사유로 차단하지 않는다(탐색 철학 보존)."""
    de = _rules_env(monkeypatch, regime="neutral")
    engine = de.DecisionEngine()
    result = engine._evaluate_rules(
        candidate={"confidence": 0.45},
        final_rule={},
        tick={"change_rate": 2.0, "prev_volume_ratio": 3.0},
    )
    # confidence 미달 사유의 조기 차단이 없어야 한다
    assert "confidence 미달" not in str(result.get("reason", ""))


def test_volatile_regime_higher_bonus(monkeypatch):
    """volatile에서 하한 가산 0.10 — 0.68도 차단(0.60+0.10=0.70)."""
    de = _rules_env(monkeypatch, regime="volatile")
    engine = de.DecisionEngine()
    result = engine._evaluate_rules(
        candidate={"confidence": 0.68},
        final_rule={},
        tick={"change_rate": 2.0, "prev_volume_ratio": 3.0},
    )
    assert result["pass"] is False and "confidence 미달" in result["reason"]


def test_confidence_gate_mode_off(monkeypatch):
    """mode=off면 방어 레짐에서도 강제하지 않는다(완전 롤백)."""
    de = _rules_env(monkeypatch, regime="risk_off", mode="off")
    engine = de.DecisionEngine()
    result = engine._evaluate_rules(
        candidate={"confidence": 0.45},
        final_rule={},
        tick={"change_rate": 2.0, "prev_volume_ratio": 3.0},
    )
    assert "confidence 미달" not in str(result.get("reason", ""))
