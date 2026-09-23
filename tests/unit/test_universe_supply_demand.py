"""S3 유니버스 — 수급(외국인+기관 순매수) 기반 선정 (SHADOW 우선) 테스트.

근거: KOSPI 상승은 외국인·기관 순매수(수급)가 주도. 현행 선정(거래량+등락률)은
수급 없는 '고거래량 laggard'를 잡아 손실. 수급 팩터를 추가하되 SHADOW(로그·테이블만)로
먼저 관찰 후 enforce 전환한다.

검증:
- _compute_supply_score: 순매수(+) → 높은 점수, 순매도(-) → 낮은 점수, 데이터없음 → 0.5 중립.
- _extract_supply_row: 일별 시계열에서 순매수 데이터 있는 최근 행 선택(오늘 미형성 대비).
- shadow 모드: 실제 top_n 불변 + selection_supply_shadow 비교 기록.
- enforce 모드: 수급 강한 종목이 거래량 하위여도 재정렬로 상승.
- off 모드: 수급 조회 없음 + 기존 top_n과 동일(byte-for-byte).
- KIS(get_investor_profile) 전면 mock — 실제 KIS 호출 금지.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import backend.services.engine.universe_filter as uf
from backend.config import settings as cfg
from backend.services.db import get_connection, initialize_database


# ---------------------------------------------------------------------------
# _compute_supply_score / _extract_supply_row — 순수 정규화 로직
# ---------------------------------------------------------------------------

def test_supply_score_positive_netbuy_high():
    """외국인+기관 순매수(+)면 supply_score > 0.5(매집)."""
    payload = {"output": [{"stck_bsop_date": "20260922",
                           "frgn_ntby_tr_pbmn": "8000", "orgn_ntby_tr_pbmn": "5000"}]}
    d = uf._compute_supply_score(payload)
    assert d["available"] is True
    assert d["supply_score"] > 0.5
    assert d["supply_signed"] > 0.0
    assert d["frgn_ntby_amount"] == 8000.0
    assert d["orgn_ntby_amount"] == 5000.0


def test_supply_score_negative_netsell_low():
    """순매도(-)면 supply_score < 0.5(분산)."""
    payload = {"output": [{"stck_bsop_date": "20260922",
                           "frgn_ntby_tr_pbmn": "-9000", "orgn_ntby_tr_pbmn": "-4000"}]}
    d = uf._compute_supply_score(payload)
    assert d["available"] is True
    assert d["supply_score"] < 0.5
    assert d["supply_signed"] < 0.0


def test_supply_score_positive_outranks_negative():
    """매집 종목 점수 > 분산 종목 점수."""
    pos = uf._compute_supply_score({"output": [{"frgn_ntby_tr_pbmn": "5000", "orgn_ntby_tr_pbmn": "3000"}]})
    neg = uf._compute_supply_score({"output": [{"frgn_ntby_tr_pbmn": "-5000", "orgn_ntby_tr_pbmn": "-3000"}]})
    assert pos["supply_score"] > neg["supply_score"]


def test_supply_score_missing_is_neutral():
    """수급 데이터 부재 → 0.5 중립(fail-open)."""
    assert uf._compute_supply_score({})["supply_score"] == 0.5
    assert uf._compute_supply_score({})["available"] is False
    assert uf._compute_supply_score({"output": []})["supply_score"] == 0.5
    assert uf._compute_supply_score(None)["supply_score"] == 0.5


def test_supply_score_bounded_0_1():
    """극단 금액도 [0,1] 안(tanh 포화)."""
    huge = uf._compute_supply_score({"output": [{"frgn_ntby_tr_pbmn": "99999999", "orgn_ntby_tr_pbmn": "99999999"}]})
    tiny = uf._compute_supply_score({"output": [{"frgn_ntby_tr_pbmn": "-99999999", "orgn_ntby_tr_pbmn": "-99999999"}]})
    assert 0.0 <= huge["supply_score"] <= 1.0
    assert 0.0 <= tiny["supply_score"] <= 1.0
    assert huge["supply_score"] > 0.99
    assert tiny["supply_score"] < 0.01


def test_extract_supply_row_skips_empty_today():
    """오늘 행(순매수 미형성)을 건너뛰고 데이터 있는 최근 행 선택.

    S3 prep(~09:01)엔 output[0]=오늘이 빈값일 수 있으므로 첫 유효행을 골라야 한다.
    """
    payload = {"output": [
        {"stck_bsop_date": "20260923", "frgn_ntby_tr_pbmn": "", "orgn_ntby_tr_pbmn": ""},  # 오늘(미형성)
        {"stck_bsop_date": "20260922", "frgn_ntby_tr_pbmn": "7000", "orgn_ntby_tr_pbmn": "2000"},  # 전일
    ]}
    row = uf._extract_supply_row(payload)
    assert row["stck_bsop_date"] == "20260922"
    d = uf._compute_supply_score(payload)
    assert d["as_of"] == "20260922"
    assert d["available"] is True


def test_extract_supply_row_accepts_dict_output():
    """output이 dict(단일 행)여도 안전 처리."""
    row = uf._extract_supply_row({"output": {"frgn_ntby_tr_pbmn": "100", "orgn_ntby_tr_pbmn": "0"}})
    assert row.get("frgn_ntby_tr_pbmn") == "100"


# ---------------------------------------------------------------------------
# _supply_combined_score / _rerank_by_supply — 결합·재정렬
# ---------------------------------------------------------------------------

def test_combined_score_weights():
    """(1-w)*existing + w*supply."""
    assert uf._supply_combined_score(0.8, 0.2, 0.0) == 0.8      # w=0 → 기존 그대로
    assert uf._supply_combined_score(0.8, 0.2, 1.0) == 0.2      # w=1 → 수급만
    assert uf._supply_combined_score(0.8, 0.4, 0.5) == 0.6      # 절반


def test_rerank_promotes_strong_supply():
    """거래량 점수 낮아도 수급 강하면 결합 재정렬로 상위로."""
    candidates = [
        {"symbol": "VOL_HI", "score": 0.90, "supply_score": 0.50},  # 거래량강·수급중립
        {"symbol": "SUP_HI", "score": 0.60, "supply_score": 0.99},  # 거래량약·수급강
    ]
    reranked = uf._rerank_by_supply(candidates, weight=0.5)
    by = {r["symbol"]: r for r in reranked}
    # (1-0.5)*0.90+0.5*0.50=0.70  vs  (1-0.5)*0.60+0.5*0.99=0.795 → SUP_HI 우위
    assert by["SUP_HI"]["supply_combined_score"] > by["VOL_HI"]["supply_combined_score"]
    assert by["SUP_HI"]["supply_rank"] == 1


def test_rerank_missing_supply_treated_neutral():
    """supply_score 부재 종목은 0.5(중립)로 취급."""
    candidates = [{"symbol": "X", "score": 0.7}]  # supply_score 없음
    reranked = uf._rerank_by_supply(candidates, weight=0.5)
    assert reranked[0]["supply_combined_score"] == pytest.approx(0.5 * 0.7 + 0.5 * 0.5)


# ---------------------------------------------------------------------------
# _resolve_supply_config — 설정 소비/클램프
# ---------------------------------------------------------------------------

def test_resolve_config_defaults_shadow(monkeypatch):
    monkeypatch.setattr(uf, "get_setting", lambda k, d=None: d)
    cfg_ = uf._resolve_supply_config()
    assert cfg_["mode"] == "shadow"
    assert cfg_["weight"] == 0.3
    assert cfg_["topk"] == 30


def test_resolve_config_clamps_and_validates(monkeypatch):
    s = {"selection.supply_demand_mode": "BOGUS",
         "selection.supply_demand_weight": 5.0, "selection.supply_demand_topk": -3}
    monkeypatch.setattr(uf, "get_setting", lambda k, d=None: s.get(k, d))
    cfg_ = uf._resolve_supply_config()
    assert cfg_["mode"] == "shadow"   # 알 수 없는 모드 → shadow
    assert cfg_["weight"] == 1.0      # >1 클램프
    assert cfg_["topk"] == 1          # <1 클램프


# ---------------------------------------------------------------------------
# run_universe_filter 통합 — off / shadow / enforce (KIS mock + 임시 DB)
# ---------------------------------------------------------------------------

def _setup_db(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "APP_DB_PATH", str(tmp_path / "supply.sqlite3"))
    initialize_database()


def _patch_kis_ranks(monkeypatch, volume_items, change_items):
    """S3가 부르는 거래량/등락률 순위 KIS 호출을 mock."""
    async def _vol(**_kw):
        return {"items": volume_items}

    async def _chg(**_kw):
        return {"items": change_items}

    monkeypatch.setattr(uf, "get_volume_rank", _vol)
    monkeypatch.setattr(uf, "get_price_rank", _chg)


def _patch_supply(monkeypatch, supply_by_symbol):
    """get_investor_profile를 심볼별 순매수 금액으로 mock (실 KIS 금지)."""
    async def _profile(*, symbol, market_code="J"):
        frgn, orgn = supply_by_symbol.get(symbol, (0.0, 0.0))
        return {"output": [{"stck_bsop_date": "20260922",
                            "frgn_ntby_tr_pbmn": str(frgn), "orgn_ntby_tr_pbmn": str(orgn)}]}

    import backend.services.kis.domestic.service as domestic_service
    monkeypatch.setattr(domestic_service, "get_investor_profile", _profile)


def _settings_map(mode, weight=0.3, topk=30, gate_min=-0.5):
    base = {
        "engine.exclude_etf_enabled": True,
        "engine.rebound_universe_enabled": False,
        "engine.crash_inverse_universe_enabled": False,
        "engine.crash_playbook_enabled": False,
        "engine.min_liquidity_krw": 0,
        "selection.weights_source": "settings",
        "selection.change_weight": 0.5,
        "selection.surge_weight": 0.5,
        "selection.supply_demand_mode": mode,
        "selection.supply_demand_weight": weight,
        "selection.supply_demand_topk": topk,
        "selection.supply_demand_gate_min": gate_min,
    }
    return base


def _run(monkeypatch, settings_map):
    _getter = lambda k, d=None: settings_map.get(k, d)
    monkeypatch.setattr(uf, "get_setting", _getter)
    # run_universe_filter 내부 로컬 import(_gs/_gs2)도 settings_store.get_setting를 부른다.
    import backend.services.settings_store as ss
    monkeypatch.setattr(ss, "get_setting", _getter)
    # spacing 0 — 테스트 속도(rate-limit은 프로덕션 설정)
    orig = uf._fetch_supply_for_candidates

    async def _fast(candidates, topk, spacing_sec=0.0):
        return await orig(candidates, topk, spacing_sec=0.0)

    monkeypatch.setattr(uf, "_fetch_supply_for_candidates", _fast)
    return asyncio.run(uf.run_universe_filter("api_manual"))


def test_off_mode_no_supply_fetch_and_identical_topn(monkeypatch, tmp_path):
    """off: 수급 조회 없음(get_investor_profile 미호출) + 기존 top_n 그대로."""
    _setup_db(monkeypatch, tmp_path)
    vol = [
        {"symbol": "AAA", "name": "가", "price": 1000, "change_rate": 3.0, "volume": 100, "volume_surge": 200.0},
        {"symbol": "BBB", "name": "나", "price": 2000, "change_rate": 1.0, "volume": 90, "volume_surge": 50.0},
    ]
    _patch_kis_ranks(monkeypatch, vol, [])

    called = {"n": 0}

    async def _profile(*, symbol, market_code="J"):
        called["n"] += 1
        return {"output": []}

    import backend.services.kis.domestic.service as domestic_service
    monkeypatch.setattr(domestic_service, "get_investor_profile", _profile)

    res = _run(monkeypatch, _settings_map("off"))
    assert res["ok"] is True
    assert called["n"] == 0                       # off → KIS 수급 미호출
    assert res["supply_demand"]["mode"] == "off"
    syms = [it["symbol"] for it in res["items"]]
    assert set(syms) == {"AAA", "BBB"}
    # 수급 필드가 후보에 붙지 않음
    assert all("supply_score" not in it for it in res["items"])


def test_shadow_mode_topn_unchanged_and_recorded(monkeypatch, tmp_path):
    """shadow: 실제 top_n 불변 + selection_supply_shadow 비교 기록."""
    _setup_db(monkeypatch, tmp_path)
    vol = [
        {"symbol": "VOLHI", "name": "거래량강", "price": 1000, "change_rate": 5.0, "volume": 100, "volume_surge": 300.0},
        {"symbol": "SUPHI", "name": "수급강", "price": 1000, "change_rate": 0.2, "volume": 10, "volume_surge": 5.0},
    ]
    _patch_kis_ranks(monkeypatch, vol, [])
    # SUPHI: 강한 순매수 / VOLHI: 순매도
    _patch_supply(monkeypatch, {"SUPHI": (9000, 9000), "VOLHI": (-9000, -9000)})

    # off로 먼저 실행해 기준 top_n 확보
    base = _run(monkeypatch, _settings_map("off"))
    base_syms = [it["symbol"] for it in base["items"]]

    res = _run(monkeypatch, _settings_map("shadow", weight=0.6))
    live_syms = [it["symbol"] for it in res["items"]]
    # 실제 선정(top_n)은 off와 동일해야 한다(shadow는 매매 불변)
    assert live_syms == base_syms
    assert res["supply_demand"]["mode"] == "shadow"
    assert res["supply_demand"].get("shadow_recorded") is True

    # 비교 테이블 기록 확인
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM selection_supply_shadow").fetchall()
    assert len(rows) == 1
    rec = dict(rows[0])
    current = json.loads(rec["current_topn_json"])
    reranked = json.loads(rec["supply_reranked_topn_json"])
    detail = json.loads(rec["detail_json"])
    assert current == live_syms                    # current == 실제 선정
    # 수급 재정렬 top_n의 1위는 수급강(SUPHI)
    assert reranked[0] == "SUPHI"
    assert "added_symbols" in detail and "dropped_symbols" in detail


def test_enforce_mode_reranks_live_selection(monkeypatch, tmp_path):
    """enforce: 거래량 하위여도 수급 강한 종목이 실제 top_n에서 상위로."""
    _setup_db(monkeypatch, tmp_path)
    vol = [
        {"symbol": "VOLHI", "name": "거래량강", "price": 1000, "change_rate": 5.0, "volume": 100, "volume_surge": 300.0},
        {"symbol": "SUPHI", "name": "수급강", "price": 1000, "change_rate": 0.2, "volume": 10, "volume_surge": 5.0},
    ]
    _patch_kis_ranks(monkeypatch, vol, [])
    _patch_supply(monkeypatch, {"SUPHI": (9000, 9000), "VOLHI": (0, 0)})

    # 기준(off): 거래량 강한 VOLHI가 1위
    base = _run(monkeypatch, _settings_map("off"))
    assert base["items"][0]["symbol"] == "VOLHI"

    res = _run(monkeypatch, _settings_map("enforce", weight=0.7))
    assert res["supply_demand"]["mode"] == "enforce"
    assert res["supply_demand"].get("enforced") is True
    # enforce 재정렬로 수급강(SUPHI)이 실제 top_n 1위
    assert res["items"][0]["symbol"] == "SUPHI"


def test_enforce_gate_excludes_strong_netsell(monkeypatch, tmp_path):
    """enforce: 강한 순매도(gate_min 미만) 종목은 실제 후보에서 제외."""
    _setup_db(monkeypatch, tmp_path)
    vol = [
        {"symbol": "KEEP", "name": "유지", "price": 1000, "change_rate": 5.0, "volume": 100, "volume_surge": 300.0},
        {"symbol": "DUMP", "name": "덤핑", "price": 1000, "change_rate": 4.0, "volume": 90, "volume_surge": 200.0},
    ]
    _patch_kis_ranks(monkeypatch, vol, [])
    # DUMP: 매우 강한 순매도 → signed≈-1 < gate_min(-0.5) → 제외
    _patch_supply(monkeypatch, {"KEEP": (5000, 5000), "DUMP": (-99999, -99999)})

    res = _run(monkeypatch, _settings_map("enforce", weight=0.5, gate_min=-0.5))
    syms = [it["symbol"] for it in res["items"]]
    assert "DUMP" not in syms
    assert "KEEP" in syms
    assert res["supply_demand"].get("gate_excluded", 0) >= 1


def test_supply_fetch_failure_is_fail_open(monkeypatch, tmp_path):
    """수급 조회 실패해도 S3가 깨지지 않고 선정은 완료된다(fail-open)."""
    _setup_db(monkeypatch, tmp_path)
    vol = [{"symbol": "AAA", "name": "가", "price": 1000, "change_rate": 3.0, "volume": 100, "volume_surge": 200.0}]
    _patch_kis_ranks(monkeypatch, vol, [])

    async def _boom(*, symbol, market_code="J"):
        raise RuntimeError("KIS down")

    import backend.services.kis.domestic.service as domestic_service
    monkeypatch.setattr(domestic_service, "get_investor_profile", _boom)

    res = _run(monkeypatch, _settings_map("enforce"))
    assert res["ok"] is True                       # 크래시 없음
    assert [it["symbol"] for it in res["items"]] == ["AAA"]  # 선정 완료(중립 처리)
