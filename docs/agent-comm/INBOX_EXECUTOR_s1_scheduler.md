# INBOX — Executor (S1: Scheduler 뼈대 + KIS 토큰 갱신)

## 작업 배경
하루 사이클 기반 자동매매 시스템 구현 S1 단계.
Scheduler 뼈대를 만들고, 첫 번째 job으로 07:45 KST KIS 토큰 갱신을 붙인다.
이후 S2~S13 모든 스케줄 job이 이 뼈대 위에 올라간다.

## 참조 문서
- AGENTS.md, IMPLEMENTATION_RULES.md, ERROR_HANDLING.md
- backend/services/kis/common/client.py — KISClient.get_token() 참조
- backend/main.py — lifespan 패턴 참조

## 구현 목표

### 1. requirements.txt에 APScheduler 추가
```
apscheduler==3.10.4
```

### 2. backend/services/scheduler.py 신규 생성
- APScheduler AsyncIOScheduler 사용
- timezone: Asia/Seoul
- Job 1: 매일 07:45 KST — KIS 토큰 선제 갱신 (`kis_client.get_token()` 강제 호출)
- Job 2: 매일 08:00 KST — 시장 톤 분석 placeholder (로그만, 실 구현은 S2)
- Job 3: 매일 08:15 KST — 유니버스 필터 placeholder (로그만, 실 구현은 S3)
- Job 4: 매일 15:20 KST — 당일 청산 placeholder (로그만, 실 구현은 S9)
- Job 5: 매일 18:00 KST — 데이터 백업 placeholder (로그만, 실 구현은 S12)
- Job 6: 매일 22:00 KST — 야간 미국장 관찰 placeholder (로그만, 실 구현은 S13)
- 스케줄러 start/stop은 FastAPI lifespan에서 제어
- 전역 싱글턴 `scheduler_instance` 제공

### 3. backend/api/routes/scheduler.py 신규 생성
- `GET /api/v1/scheduler/status`
  - 현재 등록된 job 목록, next_run_time, 상태 반환
  - 응답 envelope: `{ok, source, live, payload: {jobs: [...], running: bool}}`
- auth: require_console_user

### 4. backend/main.py 수정
- scheduler import 추가
- lifespan에서 scheduler start/stop 추가
- scheduler_router include 추가

## 구현 규칙
- 모든 함수에 docstring 작성
- START / SUCCESS / FAIL 로그 필수
- 기존 파일 최소 수정 (main.py만 수정, 나머지는 신규)
- APScheduler job 실패 시 로그만 남기고 서버는 계속 실행

## 완료 기준
- py_compile 전체 통과
- `GET /api/v1/scheduler/status` 응답 정상
- 로그에 scheduler start 확인
- 결과를 OUTBOX_EXECUTOR_s1_scheduler.md 상단에 작성
