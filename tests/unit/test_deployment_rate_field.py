from backend.api.routes.account import _build_balance_payload


def test_deployed_rate_field():
    data = {"output1": [], "output2": [{
        "tot_evlu_amt": "100000000", "ord_psbl_cash": "20000000",
        "scts_evlu_amt": "80000000", "pchs_amt_smtl_amt": "0", "evlu_pfls_smtl_amt": "0",
    }]}
    p = _build_balance_payload(data)
    # 배포율 = (총자산-가용현금)/총자산 = 80%
    assert p["deployed_rate_pct"] == 80.0
