"""Phase 2 머티리얼라이제이션 회귀 가드 (2026-06-20).

PM 원칙: 웹 화면은 그리기만, 연산·저장은 서버 프로그램이. 이산적 쓰기 이벤트를 갖는
요약(alerts/summary, dividends/stats)을 쓰기시점에 계산·저장하고 화면은 읽기만 한다.

이 테스트는 (1) 쓰기 경로가 스냅샷을 갱신하는지 (2) 읽기가 저장값을 반환하는지
(3) 스냅샷이 없을 때 lazy 백필되는지를 강제한다.
"""

import asyncio
import tempfile
import uuid

import pytest


@pytest.fixture()
def fresh_db(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    initialize_database()
    return tmp


# ──────────────────────────────────────────────────────────────────────────────
# alerts/summary — create/acknowledge 쓰기 경로가 스냅샷을 갱신
# ──────────────────────────────────────────────────────────────────────────────

def test_alert_summary_refreshed_on_write(fresh_db):
    import backend.services.engine.alert_center as ac
    from backend.services.db import get_connection

    ac.create_alert("emergency_halt", "정지", "CRITICAL", trade_date="2026-06-20")
    ac.create_alert("ws_delay", "지연", "WARNING", trade_date="2026-06-20")

    # 읽기는 저장 스냅샷에서 (읽기시점 집계 아님)
    s = ac.get_alert_summary("2026-06-20")
    assert s["total_count"] == 2 and s["unacknowledged_count"] == 2
    assert s["severity_counts"]["CRITICAL"] == 1

    # 스냅샷 행이 실제 저장됐는지
    with get_connection() as c:
        row = c.execute("SELECT * FROM alert_summary_daily WHERE trade_date='2026-06-20'").fetchone()
    assert row is not None and row["total_count"] == 2

    # 확인(ack) 시 스냅샷 갱신
    alerts = ac.get_today_alerts("2026-06-20")
    ac.acknowledge_alert(alerts[0]["id"])
    assert ac.get_alert_summary("2026-06-20")["unacknowledged_count"] == 1


def test_alert_summary_lazy_backfill(fresh_db):
    """스냅샷 없이 system_alerts만 있을 때(과거 데이터) 읽기시 1회 백필."""
    import backend.services.engine.alert_center as ac
    from backend.services.db import get_connection

    # 스냅샷 갱신을 우회해 직접 알림만 적재(과거 데이터 시뮬레이션)
    with get_connection() as c:
        c.execute(
            "INSERT INTO system_alerts (id, trade_date, alert_type, severity, title, detail, acknowledged, created_at) "
            "VALUES (?, '2026-06-01', 'db_fail', 'WARNING', 'x', '', 0, '2026-06-01T00:00:00Z')",
            (str(uuid.uuid4()),),
        )
        assert c.execute("SELECT COUNT(*) n FROM alert_summary_daily").fetchone()["n"] == 0

    s = ac.get_alert_summary("2026-06-01")
    assert s["total_count"] == 1
    with get_connection() as c:  # 읽기가 백필했는지
        assert c.execute("SELECT COUNT(*) n FROM alert_summary_daily WHERE trade_date='2026-06-01'").fetchone()["n"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# dividends/stats — 입력 쓰기 경로가 연도별 캐시 갱신
# ──────────────────────────────────────────────────────────────────────────────

def _seed_account(aid):
    from backend.services.db import get_connection
    with get_connection() as c:
        c.execute(
            "INSERT INTO dividend_accounts (id, owner_name, account_number, bank_name, is_active, created_at, updated_at) "
            "VALUES (?, '홍길동', '123', '신한', 1, '2026-01-01', '2026-01-01')",
            (aid,),
        )


def test_dividend_stats_materialized_on_write(fresh_db):
    import backend.api.routes.dividends as dv
    from backend.services.db import get_connection

    aid = str(uuid.uuid4())
    _seed_account(aid)

    async def run():
        await dv.create_dividend_entry(dv.DividendEntryCreate(
            account_id=aid, stock_id=None, dividend_date="2026-03-15",
            amount=10000, tax=1540, net_amount=8460, dividend_rate=None, memo=""))
        await dv.create_dividend_entry(dv.DividendEntryCreate(
            account_id=aid, stock_id=None, dividend_date="2026-06-10",
            amount=20000, tax=3080, net_amount=16920, dividend_rate=None, memo=""))
        return await dv.get_dividend_stats(2026)

    s = asyncio.run(run())
    assert s["total"]["net"] == 25380 and len(s["monthly"]) == 2

    # 캐시가 실제 저장됐는지(읽기시점 GROUP BY 아님)
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) n FROM dividend_stats_cache WHERE year=2026").fetchone()["n"] == 1


def test_dividend_stats_lazy_backfill_unknown_year(fresh_db):
    import backend.api.routes.dividends as dv
    from backend.services.db import get_connection

    async def run():
        return await dv.get_dividend_stats(2030)  # 데이터 없는 연도

    s = asyncio.run(run())
    assert s["total"] == {"gross": 0, "tax": 0, "net": 0}
    with get_connection() as c:  # 빈 연도도 캐시에 1회 저장(다음 읽기는 순수)
        assert c.execute("SELECT COUNT(*) n FROM dividend_stats_cache WHERE year=2030").fetchone()["n"] == 1
