# OUTBOX: 구조적 버그 2개 수정 결과

**날짜:** 2026-05-22  
**담당:** Codex (Backend / Executor)  
**요청 문서:** `docs/agent-comm/INBOX_CODEX_20260522_structural_bugs.md`

---

## 처리 요약

1. `trading_signals.realized_pnl` 동기화 로직 추가
   - 수정 파일: `backend/services/engine/review_audit.py`
   - `run_review_audit(trade_date)`에서 신호를 로드하기 전에 `trade_pairs`의 매도완료 손익을 BUY 신호의 `realized_pnl`에 반영하도록 `_sync_realized_pnl_from_trade_pairs()`를 추가했다.
   - `trading_signals.realized_pnl` 컬럼이 없는 구버전 DB에서는 경고 로그 후 건너뛰도록 방어 처리했다.
   - 정상/실패 로그를 추가했다.

2. `fill_poller` output2 fallback 수량 과다 기록 방지
   - 수정 파일: `backend/services/engine/fill_poller.py`
   - `_fetch_symbol_output2(symbol, date_str, order_no)`로 주문번호를 명시 전달하고 KIS 요청의 `ODNO` 파라미터에 반영했다.
   - output2가 리스트로 오는 경우 `odno`가 주문번호와 일치하는 행만 사용하도록 했다.
   - `kis_order_no`가 없는 주문은 output2 fallback을 건너뛰고 경고 로그를 남기도록 했다.
   - `_make_output2_fill_data()`와 `_mark_order_filled()`에서 체결 수량이 주문 수량을 초과하지 않도록 cap 처리했다.

3. 2026-05-22 잘못 기록된 sell fill 수량 보정
   - 보정 전 초과 기록 4건:
     - `006400`: 24 → 12
     - `009150`: 16 → 8
     - `034020`: 180 → 90
     - `373220`: 48 → 24
   - 보정 후 2026-05-22 sell fill 초과 수량: 0건

---

## 검증 결과

### py_compile

통과:

```bash
python -m py_compile backend/services/engine/review_audit.py backend/services/engine/fill_poller.py
```

### Review & Audit 재계산

`run_review_audit('2026-05-22')`를 직접 실행해 DB 집계를 재생성했다. 외부 텔레그램 발송 부작용을 피하기 위해 액션 플랜 발송 함수는 테스트 실행 중 no-op으로 대체했다.

결과:

```text
ok=True
trade_date=2026-05-22
total_trades=4
win_count=2
loss_count=2
total_pnl=191175.0
pnl_status=verified
pnl_source=fills
md_path=/home/young/repos/stock-trading-bot/docs/SYSTEM_AUDIT_20260522.md
```

### realized_pnl 확인

`trading_signals` BUY 신호의 `realized_pnl`:

```text
006400: 36000.0
009150: 312500.0
034020: -37325.0
373220: -120000.0
```

`daily_review_reports` 최신 행:

```text
total_trades=4
win_count=2
loss_count=2
total_pnl=191175.0
pnl_status=verified
pnl_source=fills
```

---

## 미수행 / 확인 필요

- 서버 프로세스 재시작은 이 세션에서 수행하지 않았다.
- 실제 스케줄러의 `job_review_audit()` 경유 실행은 하지 않았고, 동일 집계 함수인 `run_review_audit('2026-05-22')`를 직접 실행해 검증했다.
- 현재 작업트리에는 본 작업 이전부터 다수의 미커밋 변경이 존재한다. Codex는 커밋하지 않았다.

