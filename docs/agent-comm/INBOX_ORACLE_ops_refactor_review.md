# INBOX_ORACLE_ops_refactor_review

## 역할
너는 Oracle(Codex)다. Executor/Gemini 작업 완료 후 1차 운영 화면 개편 결과를 리뷰하라.
코드 수정은 하지 말고 `docs/agent-comm/OUTBOX_ORACLE_ops_refactor_review.md`에 결과를 작성하라.

## 리뷰 대상
- `backend/static/console.html`
- `backend/api/routes/orders.py`
- `backend/api/routes/account.py`
- `backend/api/routes/trading_monitor.py`
- `backend/services/engine/order_executor.py`

## 확인할 것
- Approval Queue / Alert Center 별도 페이지 숨김이 기존 API를 깨지 않는지
- Today Control 최근 주문 5개/자세히보기/Funnel 이동 동작
- 카드별 새로고침 제거와 상단 새로고침 동작
- Trading Monitor 계좌정보 표시 정확성
- 보유포지션 매수금액/정수 단가 표시
- 오늘 적용 정책이 Settings 값이 아니라 AI 산출물 기반인지
- LIVE 갱신이 과도한 깜빡임을 줄였는지
- Trade History 요약 카드 제거 여부
- API 오류/빈 상태/권한 실패 시 사용자 경험

## 검증 권고
- py_compile
- HTMLParser
- smoke E2E
- 필요 시 Playwright로 화면 이동 확인
