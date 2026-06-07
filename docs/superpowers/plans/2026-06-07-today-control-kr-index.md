# Today Control 국내지수 보강 — 개발계획서 v1.0

## 원본 요구사항 (PM 발화)
> 1. 아침브리핑 KOSPI는 전일값이지? 8시25분 프리마켓 데이터는 어디서? 전일도 필요하고 오늘 아침 Premarket 데이터도 필요
> 2. KOSDAQ 정보 없음 → KOSPI와 동일 조건으로 아침브리핑에 추가
> 3. 운용모드 카드 화면에 Live 코스피·코스닥 정보카드 2개 추가

## Q1 답 (확인 완료)
- 브리핑 지수 = Yahoo 오버나이트(`^KS11`) = **전일 종가**. 한국은 프리마켓 정규장 없음 → 09:00 전 라이브 국내지수 부재(야간선물이 갭 선행지표). 라이브 국내지수는 KIS `fetch_intraday_kr_market_snapshot`(0001/1001)에 있고 장중 수집됨.
- 해결: 브리핑=전일(오버나이트), 별도 라이브 카드=오늘 장중 → "전일+오늘" 둘 다 충족.

## PM 확정
- Q3 라이브 카드 개장 전 표시 = **전일 종가 + '장전' 배지**, 09:00 후 라이브 전환.

## 구현 범위
### Q2 — 브리핑 KOSDAQ 추가 (전일/오버나이트, KOSPI와 동격)
- [ ] `market_data_fetcher.py` INDEX_TICKERS에 `"kosdaq": "^KQ11"` + 라벨맵 `"kosdaq":"KOSDAQ"`
- [ ] 오버나이트 fetch 결과(kosdaq 포함)가 morning_context/brief API까지 흐르는지 확인
- [ ] `console-daily-plan.js` 브리핑 라벨맵·keys 목록에 `kosdaq` 추가(kospi 다음 배치)

### Q3 — 라이브 KOSPI/KOSDAQ 카드 2개
- [ ] 백엔드 API: `GET /api/v1/market/kr-index-live` → `fetch_intraday_kr_market_snapshot()`에서 `{kospi:{price,change_rate}, kosdaq:{price,change_rate}, market_open:bool}` 반환. market_open = KST 거래일 09:00~15:30.
- [ ] Today Control(console.html): 운용모드 카드열에 KOSPI·KOSDAQ 라이브 카드 2개 추가(개장전 '장전' 배지+전일종가, 장중 라이브 등락률 색상)
- [ ] `console-today-orders.js`(또는 today 로더): 라이브 지수 로더 추가, 'today' 진입 + 기존 30초 타이머에서 갱신

## 변경 파일
| 파일 | 변경 |
|------|------|
| `backend/services/engine/market_data_fetcher.py` | KOSDAQ 오버나이트 티커+라벨 |
| `backend/api/routes/` (신규 또는 기존 market 라우트) | `/market/kr-index-live` 엔드포인트 |
| `backend/static/js/screens/console-daily-plan.js` | 브리핑에 kosdaq 키 |
| `backend/static/console.html` | Today Control 라이브 카드 2개 |
| `backend/static/js/screens/console-today-orders.js` | 라이브 지수 로더 |
| tests | 라이브지수 API·market_open 판정 테스트 |

## 요구사항 대조표
| 요구사항 | 반영 | 비고 |
|----------|------|------|
| KOSPI 전일값 여부 설명 | ✓ | Q1 답변 |
| 프리마켓 출처 설명 | ✓ | 야간선물=갭선행, 라이브=장중 KIS |
| 브리핑에 KOSDAQ 추가 | ✓ | ^KQ11 오버나이트, KOSPI 동격 |
| 라이브 KOSPI/KOSDAQ 카드 2개 | ✓ | KIS 0001/1001, 30초 갱신 |
| 개장전 전일종가+장전 배지 | ✓ | PM 결정 |

## 완료 기준
- [ ] 브리핑에 KOSDAQ 표시(전일 등락률)
- [ ] Today Control에 라이브 KOSPI/KOSDAQ 카드, 개장전 '장전' 배지
- [ ] API 정상(장중 라이브/개장전 전일종가), 30초 갱신
- [ ] TDD 통과, 서버 재시작 후 동작
