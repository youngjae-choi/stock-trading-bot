# Missed Entry 선별 기준 개선 — 개발계획서 v1.0 (확정)

## 원본 요구사항 (PM 발화 그대로 인용)
> Missed로 뺀 종목은 제외시점의 가격, 장마감 후 장중 최고가, 장중 최저가만 확인해서 그 결과가 다음에 우리 시스템에서 매매하기 좋은 종목 즉, 필터에 걸려 제외하였지만 장중 최고가로 보면 매수했어도 괜찮은 종목으로 분류하여 다음에는 필터에 걸리지 않도록 Review에 그 의견을 전달하는게 목표야

## PM 확정 결정
- 측정값 = **[제외시점가 · 장중 최고가 · 장중 최저가]** 3개만 (분봉 10분/30분 측정 폐기)
- 판정 기준 = **장중 최고가 상승률 ≥ 임계치** ("매수했어도 좋았을 종목")
- **장중 최저가 = 리스크 정보로만 기록**(분류엔 미반영, Review 의견에 첨부)
- 임계치 = Settings 설정값(`missed.improvement_threshold`, 기본 2%) + Settings UI 노출
- 목표 산출물 = Review(학습 메모리)에 **"필터에서 제외됐으나 장중 최고 +X% → 다음엔 거르지 말 것"** 의견 전달 → S3/S4 필터 개선

## 배경 (진단)
- missed_opportunities 684건 중 improvement_candidate 60건(8%)인데 missed_entry 메모리는 571건 → LLM 주입의 92%가 노이즈(6/5 토큰비용 급증 핵심).
- 현재 판정은 **EOD 종가**만 사용 → 장중 급등 후 종가 하락한 단타 기회 누락.
- `max_return_after_10m/30m`은 이름과 달리 점(point)가 측정.

## 설계
**측정 (update_missed_returns):**
- 분봉(get_intraday_chart) 호출 **제거**. 일봉(get_daily_chart) 한 번으로:
  - 장중 최고가 = `stck_hgpr`, 장중 최저가 = `stck_lwpr` (추가 KIS 호출 없음)
  - `intraday_high_return = (hgpr - price_at_missed)/price_at_missed*100`
  - `intraday_low_return  = (lwpr - price_at_missed)/price_at_missed*100`
- `improvement_candidate = 1 if intraday_high_return >= threshold(settings)`
- threshold는 `get_setting("missed.improvement_threshold", 2.0)`로 read.

**저장 (스키마):**
- `max_return_until_eod` → **장중 최고가 상승률** 의미로 사용(컬럼명 "max_return"에 부합).
- 신규 컬럼 `intraday_low_return` 추가(저가 상승률, 음수). db.py CREATE TABLE + 기존 DB ALTER 마이그레이션.
- `max_return_after_10m/30m`은 더 이상 채우지 않음(NULL).

**메모리화 필터 (review_audit `_load_missed_entries` 또는 learning_memory):**
- `improvement_candidate=1` 인 missed_opportunities만 missed_entry 메모리화.
- shadow_trades 출처는 `max_return_eod >= threshold` 동등 기준.
- 메모리 `recommendation` = "필터 제외됐으나 장중 최고 +{high}% (최저 {low}%) → 다음엔 거르지 말 것".

**UI (Missed Entries):**
- 컬럼을 [제외가 · 장중 최고 +% · 장중 최저 +%]로 변경(기존 10m/30m/eod 대체).

**Settings UI:**
- `missed.improvement_threshold` 입력 필드 추가.

## 변경 파일
| 파일 | 변경 |
|------|------|
| `backend/services/engine/missed_opportunity.py` | 분봉 제거, 일봉 고가/저가로 high/low return, candidate=고가≥설정임계치 |
| `backend/services/db.py` | `intraday_low_return` 컬럼 + 마이그레이션, `missed.improvement_threshold`=2.0 시드 |
| `backend/services/scheduler.py` | update_missed_returns가 settings threshold 사용 |
| `backend/services/engine/review_audit.py` | `_load_missed_entries`에서 improvement_candidate=1만(+shadow 수익기준), recommendation 문구 |
| `backend/static/js/screens/console-missed-tracking.js` + `console.html` | 컬럼 제외가/장중최고/장중최저 |
| `backend/static/js/screens/console-settings.js` + `console.html` | threshold 입력 UI |
| `tests/unit/test_missed_*` | candidate 판정·필터 TDD |

## 요구사항 대조표
| 요구사항 | 반영 | 비고 |
|----------|------|------|
| 제외시점가·장중최고·장중최저만 확인 | ✓ | 일봉 1회, 분봉 폐기 |
| 장중 최고가로 "매수했어도 좋았을" 분류 | ✓ | candidate=고가≥임계치 |
| 최저가 = 리스크 기록 | ✓ | 저장+의견 첨부, 분류 미반영 |
| Review에 "거르지 말 것" 의견 전달 | ✓ | candidate만 메모리화 + recommendation |
| 임계치 설정값 | ✓ | settings+UI, 기본 2% |

## 알려진 한계 (v1)
- 일봉 당일고가는 miss 시각 *이전* 고점도 포함 가능(장초반 급등 후 늦게 거른 경우). 대부분 스크리닝 미스가 개장 직후 확정이라 수용. 정확한 "miss 이후 고점"은 분봉 풀데이 필요 → 추후.

## 완료 기준
- [ ] TDD: candidate(장중고가) 판정 + 메모리 필터 통과, 회귀 통과
- [ ] db 마이그레이션 무손실(기존 행 보존)
- [ ] 서버 재시작 후 다음 EOD부터 적용
- [ ] Missed Entries UI에 제외가/최고/최저 표시, Settings에서 threshold 조절
