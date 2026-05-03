# OUTBOX_EXECUTOR_trading_infra — 작업 결과

## 요약

공휴일 관리, 해외 시장 데이터 수집, S2 프롬프트 데이터 주입, 스케줄러 비거래일 스킵, 스케줄 시간 DB 설정 로드를 구현했다.

## 변경 파일

- `backend/services/trading_calendar.py` 신규
  - `trading_holidays` 테이블 자동 생성
  - 공휴일 등록/삭제/조회
  - 주말 + 등록 공휴일 기준 `is_trading_day()` 판정
- `backend/services/engine/market_data_fetcher.py` 신규
  - Yahoo Finance chart API 기반 해외 지수/환율/금리 데이터 수집
  - 부분 실패 시 `errors`에 기록하고 나머지 데이터 계속 처리
  - LLM 프롬프트용 텍스트 포맷터 추가
- `backend/api/routes/trading_calendar.py` 신규
  - `/api/v1/trading-calendar/holidays`
  - `/api/v1/trading-calendar/holiday`
  - `/api/v1/trading-calendar/is-trading-day`
- `backend/services/engine/market_tone.py` 수정
  - S2 프롬프트에 `{market_data}` 삽입
  - `.format()` 대신 `replace()` 사용해 JSON 중괄호 충돌 방지
  - 해외 시장 데이터 수집 실패 시 경고 로그 후 분석 계속 진행
- `backend/services/scheduler.py` 수정
  - `system_settings`의 `schedule_*_time` 값을 읽어 job 시간을 구성
  - 잘못된 시간값은 기본값으로 fallback
  - S3/S4/S5 시작 시 비거래일이면 스킵
- `backend/main.py` 수정
  - trading calendar router 등록

## 검증 결과

### 통과

```bash
python -m py_compile backend/services/trading_calendar.py
python -m py_compile backend/services/engine/market_data_fetcher.py
python -m py_compile backend/services/engine/market_tone.py
python -m py_compile backend/api/routes/trading_calendar.py
python -m py_compile backend/services/scheduler.py
python -m py_compile backend/main.py
python -c "from backend.services.trading_calendar import is_trading_day; print('holiday import OK')"
```

결과:

```text
trading_calendar OK
market_data_fetcher OK
market_tone OK
trading_calendar route OK
scheduler OK
main OK
holiday import OK
```

추가 서비스 검증:

- `is_trading_day('2026-05-04')` → `True`
- `is_trading_day('2026-05-02')` → `False` (주말)
- `add_holiday('2026-05-04')` 후 `is_trading_day('2026-05-04')` → `False`
- 테스트 공휴일 삭제 성공
- `format_for_prompt()` 출력 정상
- `scheduler_instance.get_jobs()` → 8개 job 등록 확인
- trading calendar route 함수 직접 호출 검증:
  - 등록 성공
  - 연도별 조회 성공
  - 공휴일 거래일 여부 `False`
  - 삭제 성공
  - 잘못된 날짜 입력 `400`

### 실패 / 환경 제한

`npm run test:e2e`와 `npm run _playwright_test_internal`을 실행했지만 샌드박스 네트워크/브라우저 제한으로 실패했다.

주요 오류:

```text
apiRequestContext.get: connect EPERM 127.0.0.1:8000
browserType.launch: ... sandbox_host_linux.cc ... Operation not permitted
```

판단:

- localhost 연결과 Chromium sandbox 실행이 현재 Codex 샌드박스에서 제한되어 E2E를 완료하지 못했다.
- 코드 문법, import, 서비스 단위, 라우트 함수 단위 검증은 통과했다.

## 주의 사항

- 작업 시작 전 이미 존재하던 unrelated 변경사항은 수정하지 않았다:
  - `.env.example`
  - `backend/config.py`
  - `backend/services/engine/llm_router.py`
  - `backend/static/console.html`
  - `requirements.txt`
  - 기타 기존 agent-comm 문서
- Codex는 규칙상 git commit을 실행하지 않았다.

## 다음 추천 작업

1. 실제 개발 서버 환경에서 `npm run test:e2e` 재실행
2. 프론트엔드 설정 화면에서 `schedule_*_time` 저장 UI와 이번 scheduler 설정 로드 연동 확인
3. 공휴일 CRUD API를 콘솔 UI에 노출하고 PM이 브라우저에서 등록/삭제 흐름 확인
