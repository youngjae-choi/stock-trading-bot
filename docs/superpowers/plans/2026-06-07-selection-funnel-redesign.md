# 선정 퍼널 재설계 (Funnel Monitor) — 개발계획서 v1.0

## 원본 요구사항 (PM 발화)
> 내가 보고 싶었던건 종목이 선정되는 과정이었고 거기서 어떤 종목이 필터링 되고 선택되는지가 궁금해서 화면을 만든건데.. 각 화면들이 일관성이 없는거 같아.

## 목표
Funnel Monitor를 **단계별 선정 퍼널**로 재설계: 전체 → S3 → S4 → S5 각 단계에서 **통과 종목(선정사유)·탈락 종목(탈락사유)** 을 명단으로 한 화면에. ("이름이 Funnel인데 정작 종목 퍼널이 없던" 문제 해소)

## 데이터 소스 (전부 존재 — 확인됨)
| 단계 | 통과 | 탈락 |
|---|---|---|
| 전체 | `universe_filter_results.raw_count`(89) | — |
| S3 유니버스 | `universe_filter_results.items`(symbol,name,score,rank,change_rate,volume_surge,price) | `missed_opportunities` WHERE missed_stage='S3_UNIVERSE_FILTER' (symbol,symbol_name,missed_reason,price_at_missed) |
| S4 스크리닝 | `hybrid_screening_results.candidates`(JSON: ticker,name,sector,suitability_score,reason) | missed_stage='S4_HYBRID_SCREENING' |
| S5 Daily Plan | `daily_trading_plans.symbol_assignments`(profile 배정) | missed_stage='S5_DAILY_PLAN' + `excluded_symbols` |

모두 `trade_date` 필터.

## 구현 범위
### 백엔드 — 신규 API `GET /api/v1/funnel/selection?trade_date=`
응답 계약(payload):
```
{ "trade_date": "...",
  "stages": [
    {"id":"raw","label":"전체 종목","passed_count":89},
    {"id":"s3","label":"S3 유니버스 필터","subtitle":"등락률+거래량급증",
     "passed_count":9,"passed":[{symbol,name,score,rank,change_rate,volume_surge,price}],
     "dropped_count":N,"dropped":[{symbol,name,reason,price}]},
    {"id":"s4","label":"S4 하이브리드 스크리닝","subtitle":"LLM 정성",
     "passed_count":6,"passed":[{symbol,name,sector,score,reason}],
     "dropped_count":N,"dropped":[{symbol,name,reason}]},
    {"id":"s5","label":"S5 Daily Plan","subtitle":"Profile 배정",
     "passed_count":N,"passed":[{symbol,name,profile}],
     "dropped_count":N,"dropped":[{symbol,name,reason}]}
  ]}
```
- 데이터 없으면 빈 배열 + count 0 (graceful).

### 프론트 — Funnel Monitor 화면 재구성
- **세로 퍼널**: 각 단계 = `N 통과 │ M 탈락` 헤더 + 클릭 시 펼침(통과=녹색·점수/선정사유, 탈락=적색·탈락사유).
- 기존 카운트 카드(기준 universe/Layer1/Layer2/BUY)는 상단 요약으로 축소 유지.
- **장중 재선별 타임라인(섹터회전)·적용메모리 카운트는 하단으로 분리/강등** (아침 선정과 다른 주제).
- Today Control Funnel Progress(카운트)는 그대로 → 이 화면으로 연결.

## 변경 파일
| 파일 | 변경 |
|---|---|
| `backend/api/routes/funnel.py` | `/selection` 엔드포인트 신규 |
| `backend/static/console.html` | Funnel Monitor 섹션 퍼널 마크업 |
| `backend/static/js/screens/console-funnel-data-health.js` | 퍼널 로더/렌더, 섹터회전·메모리 하단 강등 |
| tests | selection API TDD |

## 요구사항 대조표
| 요구사항 | 반영 |
|---|---|
| 단계별 선정 과정 | ✓ raw→S3→S4→S5 퍼널 |
| 어떤 종목이 필터링(탈락) | ✓ 단계별 dropped+사유 |
| 어떤 종목이 선택(통과) | ✓ 단계별 passed+선정사유 |
| 화면 일관성 | ✓ Funnel Monitor에 선정 스토리 통합, 섹터회전 분리 |

## 완료 기준
- [ ] `/api/v1/funnel/selection` 정상(통과·탈락 명단+사유), TDD 통과
- [ ] Funnel Monitor에서 단계별 통과/탈락 명단 펼침 동작
- [ ] 섹터회전·메모리 카운트 하단 분리
- [ ] 서버 재시작 후 라이브 검증
