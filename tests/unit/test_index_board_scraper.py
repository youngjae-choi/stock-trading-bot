"""index-board.space 스크래퍼 파싱 단위 테스트 (고정 HTML fixture, 네트워크 의존 제거).

PART A 회귀: regular(장중) 타입이 파싱되어야 한다.
PART B: select_latest_by_type / scrape_intraday 식 선택.
PART C: parse_briefing_numbers 수치 추출.
"""
from pathlib import Path

from backend.services.engine.index_board_scraper import (
    parse_briefing_numbers,
    parse_briefings,
    select_latest,
    select_latest_by_type,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "index_board_briefing_sample.html"


# ─────────────────────────────────────────────────────────────
# 실제 라이브 사이트 관찰 샘플 텍스트
# ─────────────────────────────────────────────────────────────
SAMPLE_PRE = (
    "간밤 필라델피아 반도체지수가 3.39% 급등하며 기술주 강세를 이끌었으나, "
    "원/달러 환율 상승(1,541원대)과 코스피200 선물 약세(-1.73%)가 부담으로 작용해 "
    "오늘 코스피는 외국인 수급 불안 속 약보합 출발이 예상됩니다."
)
SAMPLE_REGULAR = (
    "필라델피아 반도체지수가 +3.93% 급등하며 기술주 반등을 견인하고 있으나, "
    "Mag 7 전반이 일제히 하락하며 S&P 500은 보합권에 머물고 있습니다. "
    "VIX가 18.84로 소폭 상승하고 공포&탐욕 지수가 26점(Fear)을 기록하는 가운데, "
    "금($4,046)과 유가(+2.00%)가 동반 강세를 보이며 안전자산·원자재 선호 심리가 "
    "혼재된 장세가 이어질 수 있습니다."
)


def _briefing_json(text: str, type_: str, market: str, generated_at: str) -> str:
    """라이브 HTML에 박히는 백슬래시-이스케이프 JSON 조각을 흉내낸다."""
    return (
        f'\\"text\\":\\"{text}\\",'
        f'\\"type\\":\\"{type_}\\",'
        f'\\"market\\":\\"{market}\\",'
        f'\\"generatedAt\\":\\"{generated_at}\\"'
    )


def _build_html() -> str:
    parts = [
        _briefing_json(SAMPLE_PRE, "pre", "kospi", "2026-06-26T22:00:00.000Z"),
        _briefing_json(SAMPLE_REGULAR, "regular", "nasdaq", "2026-06-26T02:31:00.000Z"),
        _briefing_json("장후 요약입니다.", "post", "nasdaq", "2026-06-26T06:00:00.000Z"),
    ]
    return "<html><body><script>" + "}{".join(parts) + "</script></body></html>"


# ─────────────────────────────────────────────────────────────
# PART A — 회귀: pre / regular / post 모두 파싱
# ─────────────────────────────────────────────────────────────
def test_parse_extracts_pre_regular_and_post():
    items = parse_briefings(_build_html())
    types = {(b["type"], b["market"]) for b in items}
    assert ("pre", "kospi") in types
    assert ("regular", "nasdaq") in types  # 회귀: 이전 regex로는 누락되던 타입
    assert ("post", "nasdaq") in types


def test_existing_fixture_still_parses_pre_and_post():
    html = FIXTURE.read_text(encoding="utf-8")
    items = parse_briefings(html)
    types = {(b["type"], b["market"]) for b in items}
    assert ("pre", "kospi") in types
    assert ("post", "nasdaq") in types


def test_parse_text_content_from_fixture():
    html = FIXTURE.read_text(encoding="utf-8")
    items = parse_briefings(html)
    pre = select_latest(items, "pre", "kospi")
    assert pre is not None
    assert "코스피" in pre["text"]
    assert pre["generated_at"].startswith("2026-06-12")


def test_parse_empty_html_returns_empty():
    assert parse_briefings("<html></html>") == []


# ─────────────────────────────────────────────────────────────
# PART B — select_latest / select_latest_by_type / intraday 선택
# ─────────────────────────────────────────────────────────────
def test_select_latest_picks_newest():
    items = [
        {"text": "old", "type": "pre", "market": "kospi", "generated_at": "2026-06-12T02:52:00"},
        {"text": "new", "type": "pre", "market": "kospi", "generated_at": "2026-06-12T08:56:00"},
    ]
    assert select_latest(items, "pre", "kospi")["text"] == "new"


def test_select_latest_missing_returns_none():
    assert select_latest([], "pre", "kospi") is None


def test_select_latest_by_type_ignores_market():
    items = [
        {"text": "nasdaq one", "type": "regular", "market": "nasdaq", "generated_at": "2026-06-26T02:00:00Z"},
        {"text": "kospi two", "type": "regular", "market": "kospi", "generated_at": "2026-06-26T05:00:00Z"},
        {"text": "pre", "type": "pre", "market": "kospi", "generated_at": "2026-06-26T22:00:00Z"},
    ]
    sel = select_latest_by_type(items, "regular")
    assert sel is not None
    assert sel["text"] == "kospi two"  # market 무관, 최신
    assert sel["market"] == "kospi"


def test_intraday_selection_from_parsed_html():
    items = parse_briefings(_build_html())
    sel = select_latest_by_type(items, "regular")
    assert sel is not None
    assert sel["type"] == "regular"
    assert sel["market"] == "nasdaq"
    assert "필라델피아" in sel["text"]


# ─────────────────────────────────────────────────────────────
# PART C — parse_briefing_numbers
# ─────────────────────────────────────────────────────────────
def test_numbers_from_regular_sample():
    n = parse_briefing_numbers(SAMPLE_REGULAR)
    assert n["vix"] == 18.84
    assert n["fear_greed"] == 26
    assert n["fear_greed_label"] is not None
    assert "Fear" in n["fear_greed_label"]
    assert n["sox_pct"] == 3.93


def test_numbers_from_pre_sample():
    n = parse_briefing_numbers(SAMPLE_PRE)
    assert n["kospi200_futures_pct"] == -1.73
    assert n["usdkrw"] == 1541.0
    assert n["sox_pct"] == 3.39
    assert n["foreign_flow"] == "불안"


def test_numbers_empty_and_garbage_all_none():
    for bad in ["", "아무 의미 없는 문장입니다.", None]:
        n = parse_briefing_numbers(bad)  # type: ignore[arg-type]
        assert set(n.keys()) == {
            "vix",
            "fear_greed",
            "fear_greed_label",
            "kospi200_futures_pct",
            "usdkrw",
            "sox_pct",
            "foreign_flow",
        }
        assert all(v is None for v in n.values())


def test_numbers_comma_and_parenthesized_negative():
    txt = "원/달러 환율(1,234원대), 코스피200 선물(-2.05%) 약세."
    n = parse_briefing_numbers(txt)
    assert n["usdkrw"] == 1234.0
    assert n["kospi200_futures_pct"] == -2.05
    # 없는 필드는 None
    assert n["vix"] is None
    assert n["fear_greed"] is None


def test_numbers_vix_without_particle():
    n = parse_briefing_numbers("VIX 21.5 수준입니다.")
    assert n["vix"] == 21.5


def test_numbers_sox_positive_sign():
    n = parse_briefing_numbers("필라델피아 반도체지수가 +1.20% 상승")
    assert n["sox_pct"] == 1.20


# ─────────────────────────────────────────────────────────────
# PART C-2 — 실제 6/27 장전 브리핑 형식 회귀
#   (중첩 라벨 fear_greed "'극단적 공포(25점)'" + 부호없는 급락)
# ─────────────────────────────────────────────────────────────
SAMPLE_PRE_0627 = (
    "간밤 필라델피아 반도체지수가 4% 넘게 급락하고 공포·탐욕 지수가 "
    "'극단적 공포(25점)'를 가리키는 가운데, 원/달러 환율 하락과 코스피200 "
    "선물 강세가 일부 하방을 지지하며 오늘 코스피는 혼조세 속 보합권 출발"
)


def test_numbers_nested_label_fear_greed_0627():
    """'극단적 공포(25점)' 처럼 한글라벨 뒤 괄호숫자(점) 형식도 추출한다."""
    n = parse_briefing_numbers(SAMPLE_PRE_0627)
    assert n["fear_greed"] == 25
    assert n["fear_greed_label"] is not None
    assert "극단적 공포" in n["fear_greed_label"]


def test_numbers_sox_unsigned_drop_is_negative_0627():
    """부호 없이 '4% 넘게 급락' → 음수 부호 부여."""
    n = parse_briefing_numbers(SAMPLE_PRE_0627)
    assert n["sox_pct"] == -4.0


def test_numbers_sox_unsigned_rise_is_positive():
    """부호 없이 '3.39% 급등' → 양수 유지 (기존 동작 회귀)."""
    n = parse_briefing_numbers("필라델피아 반도체지수가 3.39% 급등")
    assert n["sox_pct"] == 3.39
