# COMMIT_RECORD_20260505_sisyphus

## 커밋 목적
- Claude 중단 이후 Sisyphus 역할로 작업 상태를 인수했다.
- Codex Executor, Gemini Frontend, Codex Oracle을 재실행해 Funnel summary API와 콘솔 하드코딩 제거 작업을 완료했다.
- Oracle 리뷰에서 발견된 settings 응답 필드 불일치와 S10/S11 scheduler 연결 문제를 보완했다.

## 주요 반영 사항
- `GET /api/v1/funnel/summary` 신규 API 추가 및 라우터 등록
- Today Control / Funnel Monitor의 Funnel 숫자 동적 로드
- `/api/v1/settings/list`, `/api/v1/settings/set` 잘못된 프론트 경로 제거
- `/api/v1/settings` 응답의 `value` 필드 사용으로 수정
- S10/S11 scheduler 시간이 `schedule_s10_time`, `schedule_s11_time` 설정값을 따르도록 연결
- Phase/운영 안정화 관련 기존 미커밋 변경 전체를 함께 저장

## 검증 기록
- `.venv/bin/python -m py_compile backend/api/routes/funnel.py backend/main.py backend/services/db.py backend/services/scheduler.py` 통과
- `backend/static/console.html` HTMLParser 파싱 통과
- 서버 재시작 후 `/health` 200 확인
- 인증 후 `/api/v1/funnel/summary` 응답 확인
  - `layer1_raw=59`
  - `layer1_count=54`
  - `layer2_count=29`
- 인증 후 `/api/v1/scheduler/status`에서 확인
  - `job_review_audit=2026-05-05T18:00:00+09:00`
  - `job_learning_memory=2026-05-05T22:00:00+09:00`
- `npx playwright test tests/e2e/console-smoke.spec.cjs --reporter=list` 통과: 2 passed

## 주의 사항
- 루트의 빈 로컬 DB 파일 `stock_trading_bot.db`, `trading_bot.db`는 커밋 대상에서 제외한다.
- 실제 운영 DB `data/stock_trading_bot.sqlite3`는 `.gitignore`의 `data/` 규칙으로 제외된다.
- 오늘 날짜 `2026-05-05` Daily Plan이 없어 `profile_counts`는 현재 0으로 반환된다.
