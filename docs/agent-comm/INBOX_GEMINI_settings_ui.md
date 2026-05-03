# INBOX_GEMINI_settings_ui — Settings UI: 공휴일 관리 + 스케줄러 시간 설정

## 수정 대상
`backend/static/console.html`

---

## 배경

백엔드에서 아래 두 가지가 신규 구현된다:
1. **공휴일 관리 API** (`/api/v1/trading-calendar/`)
2. **스케줄러 시간 설정** (`system_settings` DB에 `schedule_s1_time` 등 키로 저장)

이에 맞게 기존 **Settings 탭** UI를 확장한다.

---

## 작업 1 — 공휴일 캘린더 섹션 추가

Settings 탭에 "공휴일 관리" 섹션을 추가한다.

### API 목록
| 메서드 | URL | 설명 |
|--------|-----|------|
| GET | `/api/v1/trading-calendar/holidays?year=YYYY` | 해당 연도 공휴일 목록 |
| POST | `/api/v1/trading-calendar/holiday` | 공휴일 등록 (body: `{"date": "2026-05-05", "name": "어린이날"}`) |
| DELETE | `/api/v1/trading-calendar/holiday/{date}` | 공휴일 삭제 |
| GET | `/api/v1/trading-calendar/is-trading-day?date=YYYY-MM-DD` | 거래일 여부 확인 |

### UI 구성
```
[공휴일 관리]
연도 선택: [2026 ▼] [조회] 

  날짜         이름          삭제
  2026-01-01   신정          [삭제]
  2026-03-01   삼일절         [삭제]
  ...
  (목록이 없으면 "등록된 공휴일이 없습니다")

공휴일 등록:
  날짜: [          ] (placeholder: YYYY-MM-DD)
  이름: [          ] (placeholder: 공휴일 이름)
  [등록]
```

### 동작
- 페이지 로드 시 현재 연도 자동 조회
- 삭제 버튼 클릭 → confirm() → DELETE API 호출 → 목록 갱신
- 등록 버튼 → POST API → 성공 시 목록 갱신, 실패 시 에러 표시
- 날짜 형식 검증: `YYYY-MM-DD` 정규식 체크

---

## 작업 2 — 스케줄러 시간 설정 섹션 추가

Settings 탭에 "스케줄러 시간 설정" 섹션을 추가한다.

### 관련 system_settings 키
| 키 | 기본값 | 설명 |
|----|--------|------|
| `schedule_s1_time` | `07:45` | S1 KIS 토큰 갱신 |
| `schedule_s2_time` | `08:00` | S2 시장 톤 분석 |
| `schedule_s3_time` | `08:15` | S3 유니버스 필터 |
| `schedule_s4_time` | `08:30` | S4 종목 스크리닝 |
| `schedule_s5_time` | `08:45` | S5 RulePack 생성 |
| `schedule_close_time` | `15:20` | 당일 청산 |
| `schedule_backup_time` | `18:00` | 데이터 백업 |
| `schedule_usmarket_time` | `22:00` | 야간 미국장 관찰 |

### API
- `GET /api/v1/settings` — 전체 settings 목록 (기존 API)
- `POST /api/v1/settings` — 키 저장 (기존 API, body: `{"key": "schedule_s1_time", "value": "07:45"}`)

### UI 구성
```
[스케줄러 시간 설정]
⚠️ 변경 후 서버를 재시작해야 반영됩니다.

  단계           현재 시간    새 시간       저장
  S1 토큰 갱신    07:45       [07:45]      [저장]
  S2 시장 분석    08:00       [08:00]      [저장]
  S3 유니버스     08:15       [08:15]      [저장]
  S4 스크리닝     08:30       [08:30]      [저장]
  S5 RulePack     08:45       [08:45]      [저장]
  당일 청산       15:20       [15:20]      [저장]
  데이터 백업     18:00       [18:00]      [저장]
  야간 미국장     22:00       [22:00]      [저장]
```

### 동작
- 페이지 로드 시 `GET /api/v1/settings` 호출하여 현재 값 표시
- 값 없으면 위 기본값 표시
- 저장 버튼 → `POST /api/v1/settings` → 성공 토스트 "저장됨 (재시작 필요)"
- 시간 형식 검증: `HH:MM` 정규식 체크

---

## Settings 탭 위치

기존 Settings 탭(`#tab-settings` 또는 유사 ID)에 두 섹션을 추가한다.
- 기존 settings 내용 아래에 순서대로: 공휴일 관리 → 스케줄러 시간

---

## 완료 기준
```bash
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
grep -n "trading-calendar\|schedule_s1_time\|공휴일" backend/static/console.html | head -20
```

OUTBOX(`docs/agent-comm/OUTBOX_GEMINI_settings_ui.md`)에 결과 작성.
