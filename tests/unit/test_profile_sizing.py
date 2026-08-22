"""order_executor 잔고 파싱 테스트.

탐색모드 제거(2026-08-22)로 _calc_profile_qty(탐색 Profile 비중 사이징)는 삭제됨 —
관련 테스트 제거. 사이징은 예수금비중 신모델(execution_engine)이 담당한다.
"""
from backend.services.engine.order_executor import OrderExecutor


def test_extract_total_eval():
    ex = OrderExecutor.__new__(OrderExecutor)
    data = {"output2": [{"tot_evlu_amt": "102267986", "ord_psbl_cash": "50000000"}]}
    assert ex._extract_total_eval(data) == 102267986.0
