# OUTBOX — Codex | 배당금 수정 시 stock_id 미반영 버그 수정

## 작업 요약
- `backend/api/routes/dividends.py`의 `update_dividend_entry` 라우트에서 배당 이력 수정 시 `stock_id`가 DB에 반영되도록 수정했다.

## 변경 파일
- `backend/api/routes/dividends.py`

## 변경 내용
- `UPDATE dividends` SQL의 `SET` 절에 `stock_id = ?`를 추가했다.
- SQL 파라미터에 `payload.stock_id or None`을 추가했다.

## 완료 기준 확인
- [x] `update_dividend_entry` SQL에 `stock_id` 포함됨
- [x] `payload.stock_id or None`을 파라미터에 추가
- [x] 파이썬 문법 오류 없음

## 검증 결과
- 실행 명령: `python -m py_compile backend/api/routes/dividends.py`
- 결과: 통과

## 참고
- 현재 작업트리에는 이 작업 전부터 존재하던 다른 미커밋 변경이 다수 있다. 이번 작업은 요청된 `update_dividend_entry`의 `stock_id` 반영 수정으로 범위를 제한했다.
