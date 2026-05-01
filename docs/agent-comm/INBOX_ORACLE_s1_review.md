# INBOX — Oracle (S1 코드 리뷰)

## 작업 배경
Executor가 S1 Scheduler 구현을 완료하면 Oracle이 아키텍처/보안/기존 기능 파괴 여부를 검토한다.

## 검토 대상
- backend/services/scheduler.py (신규)
- backend/api/routes/scheduler.py (신규)
- backend/main.py (수정)
- requirements.txt (수정)

## 검토 항목
1. APScheduler job 실패 시 서버 전체에 영향을 주지 않는가
2. KIS 토큰 갱신 job이 중복 실행되지 않는가 (lock/singleton 확인)
3. scheduler lifespan이 FastAPI shutdown 시 정상 종료되는가
4. 기존 lifespan 코드(initialize_database, initialize_auth)가 깨지지 않는가
5. /api/v1/scheduler/status 가 auth guard를 올바르게 적용했는가

## 완료 기준
- 리뷰 결과를 OUTBOX_ORACLE_s1_review.md에 작성
- 이상 없음 / 수정 필요 항목 목록으로 명시
