"""배포 게이트 정확성 — 잔고 캐시 경합으로 95% 통제가 어긋나던 버그 (2026-06-11).

배경: 매수는 Semaphore(1)로 직렬화돼 있으나 잔고가 30초 캐시라, 개장 버스트에서
15건이 같은 스냅샷(배포율 0%)을 보고 전부 게이트를 통과 → 목표 95% 대비 100% 배포.
PM 지시: "시스템으로 통제했는데 어긋나는 건 버그".
수정: ①매수 제출 성공 시 잔고 캐시 무효화 ②제출중(in-flight) 매수금액(TTL 60s)을
배포액에 가산·가용현금에서 차감해 캐시/KIS 반영 지연과 무관하게 게이트를 정확화.
"""

import backend.services.engine.order_executor as oe


def _fresh_executor():
    ex = oe.OrderExecutor()
    return ex


def test_inflight_amount_accumulates_and_expires(monkeypatch):
    ex = _fresh_executor()
    t = [1000.0]
    monkeypatch.setattr(oe.time, "monotonic", lambda: t[0])
    ex._note_inflight_buy(12_000_000)
    t[0] += 10
    ex._note_inflight_buy(8_000_000)
    assert ex._inflight_amount() == 20_000_000
    t[0] += 55  # 첫 건은 TTL(60s) 초과, 둘째 건은 유지
    assert ex._inflight_amount() == 8_000_000
    t[0] += 60
    assert ex._inflight_amount() == 0


def test_note_inflight_invalidates_balance_cache(monkeypatch):
    ex = _fresh_executor()
    ex._balance_cache = {"dummy": 1}
    ex._balance_cache_at = 999999.0
    ex._note_inflight_buy(1_000_000)
    assert ex._balance_cache_at == 0.0  # 다음 매수는 신선한 잔고 조회


def test_effective_deploy_includes_inflight(monkeypatch):
    # 잔고 스냅샷상 배포 0이어도 in-flight 90M이면 게이트 계산엔 90M 반영
    ex = _fresh_executor()
    t = [500.0]
    monkeypatch.setattr(oe.time, "monotonic", lambda: t[0])
    ex._note_inflight_buy(90_000_000)
    deposit = 100_000_000.0  # 캐시상 전액 가용(미반영)
    # in-flight 매수는 _inflight_amount()로 집계되어 게이트(_effective_deployable)에 반영된다.
    deployed = ex._inflight_amount()
    deployable = ex._effective_deployable(deposit, buffer=5_000_000.0)
    assert deployed == 90_000_000.0
    assert deployable == 5_000_000.0  # 100M - 5M버퍼 - 90M inflight


# ── 동시배포 게이트 분자 _current_deployed (2026-09-01 게이트 배선 복원) ──

def test_current_deployed_is_holdings_plus_inflight(monkeypatch):
    """동시배포액 = (총평가 − 예수금) + inflight. 배포 게이트가 이 값/총평가로 판정."""
    ex = _fresh_executor()
    t = [500.0]
    monkeypatch.setattr(oe.time, "monotonic", lambda: t[0])
    # 총평가 100M · 예수금 30M → 보유배포 70M. + inflight 5M = 75M
    ex._note_inflight_buy(5_000_000)
    assert ex._current_deployed(100_000_000.0, 30_000_000.0) == 75_000_000.0


def test_current_deployed_frees_room_after_harvest():
    """수확(매도)하면 보유평가↓·예수금↑ → 동시배포액 감소 = 룸 회복(누적캡과 다른 핵심)."""
    ex = _fresh_executor()
    before = ex._current_deployed(100_000_000.0, 20_000_000.0)  # 80M 배포
    after = ex._current_deployed(100_000_000.0, 50_000_000.0)   # 수확으로 현금 50M → 50M 배포
    assert before == 80_000_000.0 and after == 50_000_000.0
    assert after < before  # 수확분이 룸으로 회복됨


def test_current_deployed_zero_when_total_eval_unknown():
    """총평가 조회 실패(≤0)면 0 반환 → 게이트가 count fallback으로 안전 전환."""
    ex = _fresh_executor()
    assert ex._current_deployed(0.0, 0.0) == 0.0
