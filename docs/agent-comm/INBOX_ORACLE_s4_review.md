# INBOX_ORACLE_s4_review — S4 Hybrid Screening 코드 리뷰

## 리뷰 대상

S4 하이브리드 스크리닝 구현 결과를 리뷰한다.

### 신규 파일
- `backend/services/engine/hybrid_screening.py`
- `backend/api/routes/screening.py`

### 수정 파일
- `backend/services/scheduler.py` (job_hybrid_screening 추가, job 번호 재정렬)
- `backend/main.py` (screening_router 등록)

## 리뷰 기준

1. **LLM 연동 안전성**: llm_router 호출 실패 시 서버가 계속 실행되는가
2. **DB 저장 일관성**: 모든 경로(정상/LLM실패/S3결과없음)에서 DB에 저장되는가
3. **프롬프트 인젝션 위험**: candidates 데이터가 LLM 프롬프트에 삽입될 때 위험이 있는가
4. **API 응답 포맷**: `{"ok", "source", "live", "payload"}` envelope 준수 여부
5. **import 오류 가능성**: 순환 참조, 존재하지 않는 함수 참조 등
6. **scheduler job 번호 재정렬**: 기존 Job 4(intraday_liquidation) → Job 5, 로그 메시지 업데이트 여부

## 결과 작성

`docs/agent-comm/OUTBOX_ORACLE_s4_review.md`에 아래 형식으로 작성:
- 전체 평가: PASS / FAIL / WARN
- 항목별 체크 결과
- FAIL/WARN 항목은 수정 방법 명시
