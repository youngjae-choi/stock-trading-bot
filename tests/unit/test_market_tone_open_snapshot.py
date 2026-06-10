"""S2 아침 분기 — 장 개시 후(09:00~) 실행 시 KIS 실시간 국내 스냅샷 보강.

배경: S1~S5 실행 시간이 09:01~로 이동(PM 2026-06-10). 프리마켓에는 KR 지수가 구조적으로
없지만(6/9 Yahoo stale 사고), 09:00 개장 후에는 KIS 실시간 KOSPI/KOSDAQ 개장가를 쓸 수 있다.
아침 분기 프롬프트에 KIS 스냅샷(지수+상위종목+섹터)을 보강 주입한다. Yahoo KR 지수 부활 금지.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.services.engine.market_tone import (
    _format_intraday_for_prompt,
    _should_attach_open_snapshot,
)

KST = ZoneInfo("Asia/Seoul")


def _dt(h: int, m: int) -> datetime:
    # 2026-06-10 수요일 — 거래일
    return datetime(2026, 6, 10, h, m, tzinfo=KST)


def test_attach_after_market_open():
    assert _should_attach_open_snapshot(_dt(9, 1)) is True
    assert _should_attach_open_snapshot(_dt(10, 30)) is True


def test_skip_before_market_open():
    # 08:30 프리마켓 수동 실행 — KIS 스냅샷은 무의미(전일 데이터) → 스킵
    assert _should_attach_open_snapshot(_dt(8, 59)) is False
    assert _should_attach_open_snapshot(_dt(7, 0)) is False


def test_skip_non_trading_day():
    # 2026-06-13 토요일 — 비거래일이면 09:00 이후라도 스킵
    sat = datetime(2026, 6, 13, 9, 30, tzinfo=KST)
    assert _should_attach_open_snapshot(sat) is False


def test_format_includes_kospi_kosdaq():
    snap = {
        "ok": True,
        "kospi": {"change_rate": 1.23},
        "kosdaq": {"change_rate": -0.45},
        "top10": [],
        "sectors": [],
    }
    txt = _format_intraday_for_prompt(snap)
    assert "KOSPI: +1.23%" in txt
    assert "KOSDAQ: -0.45%" in txt
