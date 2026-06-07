"""Tests for cumulative return fields on GET /api/v1/account/balance.

원금(시드) 대비 누적 수익률을 balance 응답에 추가하는 기능을 검증한다.
운영 DB 미접촉: get_balance / validate_config / get_setting 모두 monkeypatch.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import backend.main as main_mod
import backend.api.routes.account as account_mod

client = TestClient(main_mod.app)


def _balance_data(tot_evlu_amt: int):
    """보유종목 0개 + 총평가금액만 채운 KIS balance 원시 응답."""
    return {
        "output1": [],
        "output2": [
            {
                "dnca_tot_amt": str(tot_evlu_amt),
                "tot_evlu_amt": str(tot_evlu_amt),
                "scts_evlu_amt": "0",
                "ord_psbl_cash": "0",
                "pchs_amt_smtl_amt": "0",
                "evlu_pfls_smtl_amt": "0",
                "asst_icdc_erng_rt": "0",
                "bfdy_buy_amt": "0",
            }
        ],
    }


def _patch_common(monkeypatch):
    monkeypatch.setattr(account_mod, "validate_config", lambda: True)

    async def _fake_balance():
        return _balance_data(102203076)

    monkeypatch.setattr(account_mod, "get_balance", _fake_balance)


def test_cumulative_return_with_principal_setting(monkeypatch):
    """principal=1억, 총평가 102,203,076 → +2.20%, pnl=2,203,076."""
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        account_mod, "get_setting", lambda key, default=None: 100000000
    )

    r = client.get("/api/v1/account/balance")
    assert r.status_code == 200
    payload = r.json()["payload"]
    assert payload["principal"] == 100000000
    assert payload["cumulative_pnl"] == 2203076
    assert payload["cumulative_return_pct"] == 2.2


def test_cumulative_return_uses_default_when_setting_missing(monkeypatch):
    """principal 설정 없으면 기본 1억 적용."""
    _patch_common(monkeypatch)
    # 설정 없음 → default 반환을 그대로 흉내
    monkeypatch.setattr(
        account_mod, "get_setting", lambda key, default=None: default
    )

    r = client.get("/api/v1/account/balance")
    assert r.status_code == 200
    payload = r.json()["payload"]
    assert payload["principal"] == 100000000
    assert payload["cumulative_pnl"] == 2203076
    assert payload["cumulative_return_pct"] == 2.2


def test_cumulative_return_guard_when_principal_zero(monkeypatch):
    """principal<=0이면 cumulative_return_pct=0.0, cumulative_pnl=0."""
    _patch_common(monkeypatch)
    monkeypatch.setattr(account_mod, "get_setting", lambda key, default=None: 0)

    r = client.get("/api/v1/account/balance")
    assert r.status_code == 200
    payload = r.json()["payload"]
    assert payload["principal"] == 0
    assert payload["cumulative_pnl"] == 0
    assert payload["cumulative_return_pct"] == 0.0
