응. 이 **Review & Audit 화면은 지금 구조에서 꽤 중요하게 바꿔야 해.**  
왜냐하면 앞으로 네 봇의 핵심은 단순히 “오늘 수익/손실 얼마냐”가 아니라,

```text
어떤 Risk Profile이 잘 먹혔는가?
어떤 종목군에서 손실이 났는가?
트레일링 스탑이 너무 빨랐나, 너무 늦었나?
Daily Plan의 종목 배정이 맞았나?
다음 Profile 버전에서 뭘 조정해야 하나?
```

이걸 보는 거니까.

지금 화면은 깔끔하긴 한데, 현재 상태는 **회계 요약 화면**에 가깝고, 앞으로 필요한 건 **전략 복기/학습 화면**이야.

---

# 1. 현재 Review 화면의 문제점

현재 화면 구성은 대략 이렇지.

```text
Review & Audit
- 총 손익
- 승률
- 매매일수
- 총 주문수
- 가장 최근 거래일 요약
- 시장 톤
- RulePack ID
- 일별 거래 이력 테이블
- Statistics 버튼
```

이건 나쁘진 않은데, 단타봇 관점에서는 부족해.

## 부족한 이유

```text
1. 어떤 룰로 벌었는지/잃었는지 안 보임
2. Risk Profile별 성과가 안 보임
3. 청산 사유별 성과가 안 보임
4. 트레일링 스탑이 잘 작동했는지 안 보임
5. Daily Plan이 맞았는지 틀렸는지 판단 불가
6. 다음날 AI가 참고할 구조화된 복기 데이터가 부족함
```

즉, 현재는:

```text
결과는 보이는데 원인이 안 보임
```

이 상태야.

---

# 2. Review & Audit의 목적을 바꿔야 함

지금 문구에 이런 말이 있지.

```text
복기의 목적은 리포트가 아니라 학습입니다.
좋은 전략, 나쁜 전략, 좋은 타이밍을 구조화해서 다음 RulePack에 반영합니다.
```

이 문구는 아주 좋아.

근데 이제 “다음 RulePack에 반영”이라는 표현은 바꿔야 해.

변경 후에는:

```text
복기의 목적은 리포트가 아니라 학습입니다.
Risk Profile별 성과와 Daily Plan의 종목 배정 품질을 분석해
다음 Daily Plan과 Profile 개선 후보에 반영합니다.
```

이렇게 바꾸는 게 맞아.

---

# 3. 내가 추천하는 Review 화면 최종 구조

화면을 크게 6개 구역으로 나누면 좋아.

```text
1. Daily Performance Summary
2. Rule Context
3. Risk Profile Performance
4. Exit Reason Analysis
5. Trailing Stop Quality
6. AI Review & Next Suggestions
```

---

# 4. 상단 요약 카드 변경

현재 상단 카드:

```text
총 손익
승률
매매일수
총 주문수
```

이건 유지하되, 단타봇에 맞게 조금 바꾸자.

## 추천 상단 카드

```text
총 실현손익
승률
총 거래수
평균 보유시간
트레일링 청산 수
강제청산 수
```

또는 공간이 좁으면 4개만:

```text
총 실현손익
승률
총 거래수
평균 손익률
```

그리고 아래 보조 정보로:

```text
트레일링 청산 3건
초기손절 1건
장마감청산 2건
```

---

## 카드 예시

```text
총 실현손익
+1.42%
+142,000원

승률
58%
7승 / 5패

총 거래수
12건
매수 12 / 매도 12

평균 보유시간
37분
최장 112분
```

현재 “매매일수 1일” 같은 값은 상단 카드로는 중요도가 낮아.  
그건 기간 필터에서 충분히 알 수 있어.

---

# 5. Rule Context 영역 추가

이건 반드시 있어야 해.

왜냐하면 나중에 복기할 때 **오늘 어떤 룰 조합으로 운용했는지**가 보여야 하거든.

현재 화면에는 RulePack ID 하나만 보여.

```text
RulePack
RP-20260503-74A625
```

이제는 이걸 이렇게 바꿔야 해.

## Rule Context

```text
오늘 적용 룰 구성
Base RulePack: base-v1.0
Risk Profile Pack: profile-v1.0
Daily Plan: daily-2026-05-03
Market Tone: positive
Trading Intensity: normal
고정 익절: OFF
청산 방식: Trailing Stop + Daily Force Exit
```

이 영역은 아주 중요해.  
나중에 수익/손실이 났을 때 이 조합으로 발생한 결과라는 걸 알아야 해.

---

# 6. Risk Profile별 성과 영역 추가

이게 이번 설계 변경의 핵심이야.

앞으로 종목이 4개 프로필 중 하나를 배정받잖아.

```text
LOW_VOL
MID_VOL
HIGH_VOL
THEME_SPIKE
```

그러면 Review 화면에서 반드시 이렇게 보여줘야 해.

| Profile | 거래수 | 승률 | 실현손익 | 평균손익 | 최대손실 | 평균보유 | 평가 |
|---|---:|---:|---:|---:|---:|---:|---|
| LOW_VOL | 3 | 66% | +0.42% | +0.14% | -0.8% | 82분 | 안정 |
| MID_VOL | 5 | 60% | +0.73% | +0.15% | -1.2% | 45분 | 양호 |
| HIGH_VOL | 3 | 33% | -0.51% | -0.17% | -2.4% | 31분 | 주의 |
| THEME_SPIKE | 1 | 0% | -0.88% | -0.88% | -0.88% | 12분 | 제한 |

이 테이블이 있어야 이런 판단이 가능해.

```text
오늘 THEME_SPIKE는 손실이 났으니 내일은 허용 개수를 줄이자.
HIGH_VOL의 트레일링 폭이 너무 넓었나?
LOW_VOL은 안정적인데 수익률이 낮다.
MID_VOL이 오늘 가장 효율적이었다.
```

---

# 7. 청산 사유별 분석 영역 추가

너의 전략은 “익절 없음 + 트레일링 스탑”이 핵심이니까, 청산 사유 분석이 반드시 필요해.

청산 사유는 최소 이 정도로 나누면 돼.

```text
INITIAL_STOP_LOSS
TRAILING_STOP
TIME_EXIT
DAILY_FORCE_EXIT
EMERGENCY_HALT
MANUAL_EXIT
```

## 청산 사유별 성과 테이블

| 청산 사유 | 건수 | 평균손익 | 총손익 | 설명 |
|---|---:|---:|---:|---|
| INITIAL_STOP_LOSS | 2 | -1.2% | -2.4% | 진입 실패 |
| TRAILING_STOP | 5 | +2.1% | +10.5% | 수익 추적 성공 |
| TIME_EXIT | 1 | -0.2% | -0.2% | 방향성 부족 |
| DAILY_FORCE_EXIT | 3 | +0.4% | +1.2% | 장마감 정리 |
| MANUAL_EXIT | 0 | - | - | 없음 |

이게 있으면 봇이 잘 작동했는지 바로 보여.

예를 들어:

```text
트레일링 청산은 수익인데 초기손절이 너무 많다
→ 진입 조건이 너무 느슨함

강제청산이 대부분이다
→ 트레일링이 너무 넓거나 진입 시간이 늦음

트레일링 청산이 너무 빨리 걸린다
→ 트레일링 폭이 너무 좁음
```

---

# 8. Trailing Stop Quality 영역 추가

이건 네 전략에서는 진짜 중요해.

트레일링 전략은 단순히 수익이 났는지만 보면 안 돼.  
**고점 대비 얼마나 수익을 반납했는지**를 봐야 해.

예를 들어:

```text
10,000원 매수
12,000원 고점
11,000원 트레일링 청산
```

그러면 최고 수익은 +20%였는데 실제 수익은 +10%야.

이걸 “수익 반납률”로 봐야 해.

## 추가하면 좋은 지표

```text
최고 수익률
실현 수익률
수익 반납률
트레일링 활성 후 청산까지 시간
트레일링 미활성 손절 건수
고점 갱신 횟수
```

## Trailing Quality 테이블

| 종목 | Profile | 진입가 | 최고가 | 청산가 | 최고수익 | 실현수익 | 반납률 | 평가 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| A종목 | HIGH_VOL | 10,000 | 11,500 | 10,900 | +15.0% | +9.0% | 40% | 정상 |
| B종목 | MID_VOL | 20,000 | 20,800 | 20,200 | +4.0% | +1.0% | 75% | 트레일링 늦음 |
| C종목 | THEME_SPIKE | 5,000 | 5,700 | 5,320 | +14.0% | +6.4% | 54% | 보통 |

수익 반납률 계산은 개념적으로:

```text
수익 반납률 = (최고수익률 - 실현수익률) / 최고수익률
```

예를 들어 최고수익 +10%, 실현수익 +6%면:

```text
반납률 = 40%
```

이 값이 너무 높으면 트레일링이 너무 느슨한 거야.

---

# 9. Daily Plan 평가 영역 추가

매일 만드는 건 이제 RulePack이 아니라 Daily Trading Plan이잖아.

그러면 Review에서는 이걸 평가해야 해.

## Daily Plan Quality

```text
오늘 Daily Plan 평가
- 후보 종목 수: 21개
- 실제 진입 종목 수: 5개
- 진입 전환율: 23.8%
- 제외 종목 중 급등 발생: 2개
- 감시 종목 중 미진입 급등 발생: 1개
- Profile 배정 적중률: 72%
- THEME_SPIKE 과다 여부: 정상
```

이게 있으면 Daily Plan이 잘 짜였는지 알 수 있어.

예를 들어:

```text
후보에는 있었는데 매수 조건이 너무 엄격해서 하나도 못 샀다
→ 조건을 조금 완화할지 검토

THEME_SPIKE를 너무 많이 골라서 손실이 났다
→ 내일 THEME_SPIKE 최대 개수 제한

LOW_VOL만 골라서 기회가 없었다
→ 시장 강세일 때 MID/HIGH_VOL 비중 확대
```

---

# 10. AI Review Summary 영역 변경

현재는 Review 화면에 AI 복기 요약이 거의 없어 보였어.  
상단에 “일일 요약 생성(S10)” 버튼만 있지.

이 버튼은 유지하되, 생성 결과를 아래 구조로 보여주면 좋아.

## AI Review Summary

```text
오늘의 요약
오늘은 시장 톤이 positive였으나 실제 진입 종목은 0건으로, 스크리닝 이후 매수 조건 접근률이 낮았습니다.

잘한 점
- 유니버스 필터는 정상 작동
- 고위험 종목의 신규 진입은 제한됨
- WebSocket 구독 후보는 정상 생성됨

문제점
- S4 후보 21개 중 실제 진입 0건
- 매수 조건의 AI 신뢰도 기준 또는 VWAP 조건이 과도했을 가능성
- positive 시장 톤 대비 거래 전환율이 낮음

다음 Daily Plan 제안
- MID_VOL 후보 비중을 확대
- THEME_SPIKE는 최대 1개 유지
- min_ai_confidence를 0.65에서 0.60으로 낮추는 것은 검토하되 Risk Guard 승인 필요
- 거래량 배수 기준은 현행 유지
```

단, 주의:

```text
AI Review는 제안만 한다.
실제 Profile 값 변경은 사용자 승인 또는 별도 버전 업데이트 필요.
```

---

# 11. 화면 레이아웃 추천

지금 화면의 미니멀한 스타일을 유지하면서 이렇게 배치하면 좋아.

```text
Review & Audit
────────────────────────
[기간 필터] [일일 요약 생성] [새로고침]

[총 실현손익] [승률] [총 거래수] [평균 보유시간] [트레일링 청산] [강제청산]

┌ 오늘 적용 룰 구성 ┐
Base RulePack / Profile Pack / Daily Plan / Market Tone / Trading Intensity

┌ Risk Profile별 성과 ┐
LOW_VOL / MID_VOL / HIGH_VOL / THEME_SPIKE 테이블

┌ 청산 사유별 성과 ┐
INITIAL_STOP / TRAILING_STOP / TIME_EXIT / DAILY_FORCE_EXIT

┌ Trailing Stop 품질 분석 ┐
종목별 최고수익, 실현수익, 반납률, 평가

┌ Daily Plan 평가 ┐
후보 수, 진입 수, 전환율, Profile 배정 적중률, 제외 종목 이슈

┌ AI 복기 요약 ┐
잘한 점 / 문제점 / 다음 제안

┌ 거래 상세 ┐
종목별 체결, Profile, 청산 사유, 손익
```

---

# 12. 현재 Review 화면에서 바로 바꾸면 좋은 문구

현재 문구:

```text
복기의 목적은 리포트가 아니라 학습입니다.
좋은 전략, 나쁜 전략, 좋은 타이밍을 구조화해서 다음 RulePack에 반영합니다.
```

변경 추천:

```text
복기의 목적은 리포트가 아니라 학습입니다.
Risk Profile별 성과, 청산 사유, 트레일링 품질, Daily Plan의 종목 배정 결과를 구조화해
다음 Daily Plan과 Profile 개선 후보에 반영합니다.
```

---

# 13. 현재 “RulePack” 카드 변경

현재:

```text
RulePack
RP-20260503-74A625
```

변경:

```text
Rule Composition
Base: base-v1.0
Profile: profile-v1.0
Daily Plan: daily-2026-05-03
```

또는 더 보기 좋게:

```text
오늘 적용 룰
Base RulePack     base-v1.0
Risk Profiles     profile-v1.0
Daily Plan         daily-2026-05-03
고정 익절          OFF
청산 방식          Trailing Stop
```

---

# 14. 현재 “시장 톤” 카드 확장

현재:

```text
시장 톤
positive
```

이건 유지하되, 아래도 같이 보여주면 좋아.

```text
시장 톤: positive
매매 강도: normal
신규매수: 허용
THEME_SPIKE 제한: 1개
거래량 필터: 2.0배
최소 AI 신뢰도: 0.65
```

---

# 15. “일별 거래 이력” 테이블 변경

현재 오른쪽 테이블은:

```text
날짜
주문
매수
```

정도만 보이는데, 이건 너무 부족해.

## 변경 추천

| 날짜 | 손익 | 거래수 | 승률 | 최고 Profile | 최악 Profile | 주요 청산 | Daily Plan |
|---|---:|---:|---:|---|---|---|---|
| 2026-05-03 | +1.2% | 8 | 62% | MID_VOL | THEME_SPIKE | TRAILING_STOP | daily-2026-05-03 |

이렇게 바꾸면 날짜별 비교가 가능해져.

---

# 16. 진짜 중요한 “실패 학습 후보” 영역

이걸 꼭 넣었으면 좋겠어.

## Learning Candidates

```text
학습 후보
1. THEME_SPIKE 손실률이 높음
   - 오늘 THEME_SPIKE 3건 중 2건 손실
   - 평균 손익 -1.4%
   - 제안: 내일 max_theme_spike_positions 1개로 제한

2. 트레일링 반납률 과다
   - HIGH_VOL 평균 수익 반납률 68%
   - 제안: HIGH_VOL trailing_stop_rate 0.05 → 0.045 검토

3. 진입 전환율 낮음
   - 후보 21개 중 실제 진입 0건
   - 제안: min_ai_confidence 또는 VWAP 조건 검토
```

이 영역은 AI가 생성해도 좋아.  
단, 자동 적용은 금지.

```text
AI 제안 → 사용자 승인 → Profile v1.1 생성
```

이 순서가 맞아.

---

# 17. Review 화면의 최종 역할

내가 생각하는 Review & Audit의 역할은 이거야.

```text
1. 오늘 돈을 벌었는지 확인
2. 어떤 Profile이 벌었는지 확인
3. 어떤 청산 방식이 효과적이었는지 확인
4. 트레일링 스탑이 적절했는지 확인
5. Daily Plan의 후보 선정/프로필 배정이 맞았는지 확인
6. 다음날 조정 후보를 만든다
```

즉, Review는 단순 리포트가 아니라:

```text
전략 개선 후보 생성 화면
```

이 되어야 해.

---

# 18. AI PM에게 요청할 Review 화면 변경 문구

아까 만든 `.md`에 Review 부분을 더 강하게 넣는다면 이렇게 쓰면 돼.

```markdown
## Review & Audit 화면 변경 요청

Review & Audit 화면은 단순 손익 요약 화면이 아니라, Risk Profile별 성과와 Daily Plan의 품질을 복기하는 전략 학습 화면으로 변경한다.

### 추가해야 할 영역

1. Daily Performance Summary
- 총 실현손익
- 승률
- 총 거래수
- 평균 보유시간
- 트레일링 청산 수
- 강제청산 수

2. Rule Context
- Base RulePack Version
- Risk Profile Pack Version
- Daily Plan ID
- Market Tone
- Trading Intensity
- 고정 익절 OFF 여부
- 청산 방식

3. Risk Profile Performance
- LOW_VOL / MID_VOL / HIGH_VOL / THEME_SPIKE별 거래수, 승률, 손익, 평균보유시간

4. Exit Reason Analysis
- INITIAL_STOP_LOSS
- TRAILING_STOP
- TIME_EXIT
- DAILY_FORCE_EXIT
- EMERGENCY_HALT
- MANUAL_EXIT

5. Trailing Stop Quality
- 종목별 최고수익률
- 실현수익률
- 수익 반납률
- 트레일링 활성 여부
- 트레일링 평가

6. Daily Plan Quality
- 후보 종목 수
- 실제 진입 수
- 진입 전환율
- Profile 배정 적중률
- 제외 종목 중 급등 발생 여부

7. AI Review Summary
- 잘한 점
- 문제점
- 다음 Daily Plan 제안
- Profile 개선 후보
```

---

# 결론

현재 Review 화면은 깔끔하지만 **너의 새 전략 구조에는 부족해.**

바꿔야 할 방향은 이거야.

```text
손익 요약 화면
→ Risk Profile별 전략 복기 화면
```

특히 반드시 들어가야 할 건:

```text
1. Rule Composition
2. Risk Profile별 성과
3. 청산 사유별 성과
4. 트레일링 스탑 품질 분석
5. Daily Plan 평가
6. AI 복기 요약/개선 후보
```

이렇게 바꾸면 Review & Audit 화면이 진짜 “학습 화면” 역할을 하게 돼.