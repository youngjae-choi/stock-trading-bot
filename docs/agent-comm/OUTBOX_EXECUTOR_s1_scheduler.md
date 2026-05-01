# OUTBOX — Executor (S1: Scheduler 뼈대 + KIS 토큰 갱신) 결과

## 실행 일시
2026-04-29

## 완료 여부
✅ 전체 완료

---

## 구현 결과 요약

### 1. requirements.txt — apscheduler 추가
```
apscheduler==3.10.4
```
- 설치 확인: `pip install apscheduler==3.10.4` 성공

---

### 2. backend/services/scheduler.py — 신규 생성
- `AsyncIOScheduler` (timezone: Asia/Seoul)
- 전역 싱글턴 `scheduler_instance` 제공
- 등록된 Job 6개:

| Job ID | 시간 (KST) | 설명 | 구현 단계 |
|--------|-----------|------|----------|
| `job_refresh_kis_token` | 07:45 | KIS 토큰 선제 갱신 | ✅ 실 구현 (S1) |
| `job_market_tone_analysis` | 08:00 | 시장 톤 분석 | placeholder (S2) |
| `job_universe_filter` | 08:15 | 유니버스 필터 | placeholder (S3) |
| `job_intraday_liquidation` | 15:20 | 당일 청산 | placeholder (S9) |
| `job_data_backup` | 18:00 | 데이터 백업 | placeholder (S12) |
| `job_us_market_watch` | 22:00 | 야간 미국장 관찰 | placeholder (S13) |

- KIS 토큰 갱신 로직: `kis_client.token = None` + `token_expires_at = 0` 으로 캐시 무효화 후 `get_token()` 강제 호출
- job 실패 시 `logger.error` 기록 후 서버 계속 실행 (예외 전파 차단)

---

### 3. backend/api/routes/scheduler.py — 신규 생성
- `GET /api/v1/scheduler/status`
- auth: `require_console_user` (콘솔 세션 쿠키 필요)
- 응답 envelope:
```json
{
  "ok": true,
  "source": "scheduler",
  "live": true,
  "payload": {
    "running": true,
    "jobs": [
      {"id": "job_refresh_kis_token", "name": "KIS 토큰 선제 갱신", "next_run_time": "2026-04-30T07:45:00+09:00"},
      ...
    ]
  }
}
```

---

### 4. backend/main.py — 수정
- `scheduler_router` import 추가
- `scheduler_instance` import 추가
- `lifespan`에 `scheduler_instance.start()` / `scheduler_instance.shutdown(wait=False)` 추가
- `app.include_router(scheduler_router)` 추가

---

## py_compile 검증
```
python -m py_compile \
  backend/services/scheduler.py \
  backend/api/routes/scheduler.py \
  backend/main.py
→ ALL OK (에러 0개)
```

---

## 로그 예상 출력 (서버 기동 시)
```
INFO  BackendServer  START: Backend API Server
INFO  Scheduler      SUCCESS: Scheduler started (6 jobs registered)
```

## 확인 필요 항목
- 실 서버 기동 후 `GET /api/v1/scheduler/status` 응답 확인 (PM 또는 Oracle 담당)
- 07:45 KST job 실행 시 KIS 토큰 갱신 로그 확인
