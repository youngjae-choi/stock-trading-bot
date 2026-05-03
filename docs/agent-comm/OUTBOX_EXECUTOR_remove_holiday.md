# OUTBOX_EXECUTOR_remove_holiday — 공휴일 기능 전체 삭제 결과

## 작업 요약

공휴일 관리 기능을 요청 범위대로 제거했다. 스케줄러 시간 DB 설정과 다른 시장 데이터 기능은 수정하지 않았다.

## 변경 파일

- `backend/services/trading_calendar.py`
  - 파일 삭제
- `backend/api/routes/trading_calendar.py`
  - 파일 삭제
- `backend/main.py`
  - `trading_calendar_router` import 제거
  - `app.include_router(trading_calendar_router)` 제거
- `backend/services/scheduler.py`
  - `_is_non_trading_day()` 함수 제거
  - Job3/Job4/Job5의 비거래일 skip 호출 제거
  - 각 job의 KST 날짜 로그 흐름은 유지
- `backend/static/console.html`
  - Settings 탭의 공휴일 관리 카드 제거
  - `loadHolidays()`, `addHoliday()`, `deleteHoliday()` 제거
  - `holidayYearSelect` 초기화와 `loadHolidays()` 호출 제거

## 검증 결과

```bash
python -m py_compile backend/main.py && echo "main OK"
# main OK

python -m py_compile backend/services/scheduler.py && echo "scheduler OK"
# scheduler OK

python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
# HTML OK

grep -n "trading_calendar\|is_trading_day\|holiday" backend/main.py backend/services/scheduler.py
# 결과 없음
```

추가 확인:

```bash
rg -n "trading-calendar|trading_calendar|is_trading_day|holidayYearSelect|loadHolidays|addHoliday|deleteHoliday|공휴일" backend/main.py backend/services/scheduler.py backend/static/console.html backend/api backend/services
# 결과 없음
```

## 남은 리스크 / 확인 필요

- 브라우저 수동 확인은 실행하지 않았다. 정적 HTML 파싱과 문자열 잔여 참조 검사는 통과했다.
- 삭제 대상 2개 파일은 작업 전 git 상태에서 untracked 파일이었다. 삭제 후 git status 대상 목록에는 남지 않는다.
