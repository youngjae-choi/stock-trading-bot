"""선정 출처 마킹(llm vs quant_topup)이 trade 태그 sources에 들어가는지 + EV 차원 집계.

LLM이 보류/탈락시켰으나 정량 top-up으로 재포함된 종목을 추적해, 추후 성과(EV)로 강화/제거 판단.
"""

from backend.services.engine.trade_tagging import build_selection_reason
from backend.services.engine.ev_analysis import _keys_for_dimension


def test_selection_source_is_first_source():
    llm = build_selection_reason({"selection_source": "llm", "volume_rank": 9})
    topup = build_selection_reason({"selection_source": "quant_topup", "volume_rank": 9})
    assert llm["sources"][0] == "llm"
    assert topup["sources"][0] == "quant_topup"


def test_no_source_when_unmarked():
    r = build_selection_reason({"volume_rank": 9})
    assert "llm" not in r["sources"] and "quant_topup" not in r["sources"]


def test_ev_dimension_reads_selection_source():
    tag = {"selection_reason": {"sources": ["quant_topup", "거래량순위#9"]}}
    keys = _keys_for_dimension(tag, "selection_source")
    assert "quant_topup" in keys
