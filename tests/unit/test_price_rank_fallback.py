import asyncio

import backend.services.kis.domestic.universe_service as us


def test_trade_amount_segmented_empty_falls_back_to_single_J(monkeypatch):
    """top_n>30 분리호출(STK/KSQ)이 0행이면 단일 J/0 호출로 폴백해야 한다."""

    async def fake_request(method, path, tr_id, params):
        mrkt = params.get("FID_COND_MRKT_DIV_CODE")
        if mrkt in ("STK", "KSQ"):
            return {"output": []}  # 분리호출 빈 결과(거래대금 TR이 STK/KSQ 미지원)
        # 단일 J/0 호출은 정상 데이터
        return {
            "output": [
                {
                    "mksc_shrn_iscd": "005930",
                    "hts_kor_isnm": "삼성전자",
                    "stck_prpr": "70000",
                    "prdy_ctrt": "1.5",
                    "acml_tr_pbmn": "20000000",
                }
            ]
        }

    monkeypatch.setattr(us.kis_client, "request", fake_request)
    r = asyncio.run(us.get_price_rank(sort_by="trade_amount", market_code="J", top_n=60))
    assert r["count"] >= 1
    assert r["items"][0]["symbol"] == "005930"
