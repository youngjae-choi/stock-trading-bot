# 시스템 점검 보고서 — 2026-05-04 첫 실전 테스트

> 작성: 2026-05-05  
> 점검 범위: 어제(2026-05-04) 실행 결과 + 현재 시스템 완성도 + 발견된 버그

---

## 1. 어제 실행 결과 요약

### 전체 흐름

```
09:05  S3 유니버스 필터    ✅ 58종목 수집 → 30종목 선별
09:20  S4 Hybrid Screening ✅ 30→21종목, confidence 0.62, Claude Opus 실행
09:35  S5 Daily Plan       ✅ 10종목 배정, aggressive 강도, Claude 실행
09:45  S6 Decision Engine  ⚠️ 활성화됨, WebSocket 21종목 구독 — 단, 6분간 버그
09:51  매수 신호 발생       ⚠️ 21종목 동시 발생 → 11 executed / 9 failed / 1 preflight_blocked
09:51  매수 주문 실행       ⚠️ 11건 submitted / 9건 failed (KIS 초당 한도 초과)
16:00  S10 Review          ⚠️ 1건만 집계됨 (체결 확인 미구현으로 부정확)
16:30  S11 Memory          ❌ 학습 메모리 0건 생성됨
```

---

### S5 Daily Plan — 어제 종목 배정

| 종목코드 | 종목명 | 프로파일 |
|----------|--------|----------|
| 491090 | KODEX 미국테크TOP3플러스 | LOW_VOL |
| 473590 | ACE 미국주식베스트셀러 | LOW_VOL |
| 0101N0 | RISE AI전력인프라 | LOW_VOL |
| 367760 | RISE 네트워크인프라 | LOW_VOL |
| 006340 | 대원전선 | MID_VOL |
| 199820 | 제일일렉트릭 | HIGH_VOL |
| 432720 | 퀄리타스반도체 | HIGH_VOL |
| 126730 | 코칩 | MID_VOL |
| 125020 | 티씨머티리얼즈 | HIGH_VOL |
| 006345 | 대원전선우 | THEME_SPIKE |

Claude 판단 근거: "미국·유럽 증시 동반 강세, AI전력인프라·미국테크 ETF를 LOW_VOL 안정 축으로, 대원전선을 MID_VOL로 편입. 대원전선우는 +25.86% 극단적 급등으로 THEME_SPIKE"

제외된 11종목: 스코어 0.65 미만 또는 테마 부합도 낮거나 급등 부담 큰 종목

---

### 매수 신호 및 주문 결과

| 종목 | confidence | profile | 신호 | 주문 | 실패 원인 |
|------|-----------|---------|------|------|-----------|
| 제일일렉트릭 | 0.70 | HIGH_VOL | executed | submitted 410주 @19,500 | — |
| PS일렉트로닉스 | 0.45 | MID_VOL | executed | submitted 955주 @10,470 | — |
| 티씨머티리얼즈 | 0.58 | MID_VOL | executed | submitted 1,117주 @8,950 | — |
| 프로이천 | 0.30 | MID_VOL | executed | submitted 3,095주 @3,230 | — |
| 컴퍼니케이 | 0.35 | MID_VOL | executed | submitted 955주 @10,470 | — |
| RISE AI전력인프라 | 0.74 | LOW_VOL | executed | submitted 372주 @26,860 | — |
| 아진엑스텍 | 0.50 | MID_VOL | executed | submitted 985주 @10,150 | — |
| 코칩 | 0.55 | HIGH_VOL | executed | submitted 349주 @22,900 | — |
| RISE 네트워크인프라 | 0.68 | LOW_VOL | executed | submitted 200주 @49,855 | — |
| ACE 미국주식베스트셀러 | 0.68 | LOW_VOL | executed | submitted 446주 @22,405 | — |
| KODEX 미국테크TOP3플러스 | 0.72 | LOW_VOL | executed | submitted 557주 @17,930 | — |
| 대원전선 | 0.72 | MID_VOL | failed | failed 0주 | **KIS 초당 한도 초과** |
| 퀄리타스반도체 | 0.65 | HIGH_VOL | failed | failed 0주 | **KIS 초당 한도 초과** |
| 남해화학 | 0.45 | MID_VOL | failed | failed 0주 | **KIS 초당 한도 초과** |
| 세아메카닉스 | 0.42 | MID_VOL | failed | failed 0주 | **KIS 초당 한도 초과** |
| 휴맥스 | 0.48 | MID_VOL | failed | failed 0주 | **KIS 초당 한도 초과** |
| 해성옵틱스 | 0.40 | MID_VOL | failed | failed 0주 | **KIS 초당 한도 초과** |
| 대원전선우 | 0.50 | THEME_SPIKE | failed | failed 0주 | **KIS 초당 한도 초과** |
| KBI메탈 | 0.40 | MID_VOL | failed | failed 0주 | **KIS 초당 한도 초과** |
| 휴맥스홀딩스 | 0.45 | MID_VOL | failed | failed 0주 | **KIS 토큰 재발급 한도 (1분당 1회)** |
| JTC | 0.28 | MID_VOL | preflight_blocked | — | **preflight 차단** |

**총 주문 금액 (submitted 기준): 105,919,110원**  
**체결 확인: 미구현 — fills 테이블 0건** (주문은 KIS에 전달됐으나 체결 확인 로직 없음)

---

## 2. 발견된 버그 (심각도 순)

### 🔴 버그 1: trading_signals에 profile_assigned 컬럼 누락

**증상**: Decision Engine 활성화(09:45) 직후 6분간 모든 tick에서 에러 발생
```
FAIL: tick callback error — table trading_signals has no column named profile_assigned
```
**영향**: 09:45~09:51 6분간 tick 처리 전면 불가. 이 시간 동안 매수 기회 완전 손실  
**원인**: db.py migration에서 `profile_assigned` 컬럼 추가가 빠진 채로 배포됨  
**현재 상태**: DB에는 컬럼이 존재함 (서버 재시작 또는 수동 추가로 해결된 것으로 보임)  
**조치 필요**: db.py migration 코드에 명시적으로 추가하여 재현 방지

---

### 🔴 버그 2: KIS 초당 거래 한도 초과 (EGW00201)

**증상**: 21개 신호가 동시에 발생 → 잔고 조회(inquire-balance)를 21번 동시 호출 → 한도 초과
```
KIS API Error: EGW00201 초당 거래건수를 초과하였습니다.
```
**영향**: 9건의 주문이 아예 전달되지 못함 (qty=0, status=failed)  
**원인**: 주문 실행 시 각 종목마다 잔고를 별도 조회하는 구조 + 순차 처리 없음  
**조치 필요**: 주문 실행 직전 잔고 1회만 조회 후 공유, 주문 간 최소 간격 추가

---

### 🔴 버그 3: 체결 확인(Fill Confirmation) 미구현

**증상**: KIS에 주문은 전달됐으나 fills 테이블 = 0건, positions 테이블 = 0건, realized_pnl = null  
**영향**:
- S8(Position Manager)가 보유 포지션을 인식하지 못함 → 트레일링 스탑 미작동
- S10 Review가 정확한 손익 계산 불가 (1건만 집계)
- S11 Learning Memory 생성 불가 (근거 데이터 없음)
- 실제로 모의 계좌에서 포지션이 생겼는지 시스템이 모름

**원인**: KIS 체결 통보를 WebSocket이나 Polling으로 받아서 fills에 기록하는 로직이 없음  
**조치 필요**: KIS 주문체결 WebSocket(H0_STCNI0) 구독 또는 체결 polling 로직 구현 — **이게 가장 큰 미구현 항목**

---

### 🟡 버그 4: 21개 신호 동시 발생 (일괄 처리 문제)

**증상**: 09:51:29에 거의 모든 신호가 동시에 발생 (tick-by-tick이 아님)  
**원인**: 09:45 Decision Engine 활성화 시 이미 조건을 충족하는 종목들이 첫 tick에서 일괄 판단됨  
**영향**: 실제 운영에서는 종목당 조건이 달성되는 시점이 다를 것이나 현재는 일괄 처리됨  
**조치 필요**: 문제라기보다 모의투자 환경 특성. 단, rate limit과 결합하면 실패율 높아짐

---

### 🟡 버그 5: confidence 낮은 종목이 Daily Plan에서 걸러지지 않음

**증상**: RulePack의 `min_ai_confidence: 0.65` 설정인데 confidence 0.28~0.45 종목들이 신호 발생  
**영향**: 퀄리티 낮은 종목에 주문 시도. 다행히 KIS 한도 초과로 대부분 실패  
**원인**: Decision Engine의 Layer 3 조건 체크에서 confidence 필터가 동작하지 않은 것으로 보임  
**조치 필요**: `_evaluate_rules`에서 confidence 필터 로직 확인 및 수정

---

### 🟡 버그 6: S10/S11이 실제 거래를 거의 감지하지 못함

**증상**:  
- S10: total_trades=1, win=0, loss=1, total_pnl=0.0 (11건 주문했는데 1건만)
- S11: 메모리 0건 생성

**원인**: S10이 fills 테이블 기반으로 집계하는데 fills가 비어있음 → 버그 3의 파생  
**조치 필요**: 체결 확인 구현 후 자연스럽게 해결됨

---

## 3. 현재 시스템 완성도

### 단계별 완성도

| 단계 | 기능 | 완성도 | 상태 |
|------|------|--------|------|
| S1 | KIS 토큰 갱신 | ✅ 완성 | 정상 작동 |
| S2 | AI 시장 톤 분석 | ✅ 완성 | Claude 실행, 결과 정확 |
| S3 | 유니버스 필터 | ✅ 완성 | KIS 데이터 수집, 필터링 정상 |
| S4 | Hybrid Screening | ✅ 완성 | Claude Opus 정성 평가 정상 |
| S5 | Daily Plan 생성 | ✅ 완성 | 종목 배정, 프로파일 배정 정상 |
| S6 | Decision Engine | ⚠️ 부분 완성 | 활성화 가능, profile_assigned 버그 잠재 |
| S7 | 주문 실행 | ⚠️ 부분 완성 | 제출은 되나 rate limit + confidence 필터 문제 |
| S8 | Position Manager | ❌ 미완성 | 체결 확인 없어 포지션 추적 불가 |
| S9 | 당일 청산 | ❓ 미확인 | 포지션이 없어 실행 여부 확인 불가 |
| S10 | Review & Audit | ⚠️ 부분 완성 | 실행됨, 체결 데이터 없어 집계 부정확 |
| S11 | Learning Memory | ❌ 미완성 | 데이터 없어 메모리 생성 안됨 |

### UI 완성도

| 화면 | 완성도 | 비고 |
|------|--------|------|
| Today Control | ✅ 완성 | 핵심 현황 확인 가능 |
| Trading Hub | ✅ 완성 | 시세/잔고 조회 |
| Settings | ✅ 완성 | Risk Profile, RulePack 관리 |
| Expert Knowledge | ✅ 완성 | 지식 등록/승인 |
| Alert Center | ✅ 완성 | 알림 목록 |
| Approval Queue | ✅ 완성 | 승인 대기 |
| Shadow Trading | ✅ 완성 | 미진입 가상 추적 |
| Missed Opportunity | ✅ 완성 | 놓친 기회 분석 |
| False Positive | ✅ 완성 | 오진입 분석 |
| Confidence Cal. | ✅ 완성 | 신뢰도 캘리브레이션 |
| Review & Audit | ✅ 완성 | 복기 화면 |
| Funnel Monitor | ✅ 완성 | S2~S5 퍼널 |
| **Positions (실시간)** | ❌ 미완성 | 체결 연동 안됨 |
| **Orders/Fills** | ❌ 미완성 | 체결 내역 없음 |

---

## 4. 우선순위별 조치 계획

### P0 — 즉시 해결 (실전 불가 수준)

1. **체결 확인 (Fill Confirmation) 구현**
   - KIS 체결 통보 WebSocket(`H0STCNI0` 또는 Polling) 연결
   - fills 테이블에 체결 내역 기록
   - Position Manager가 fills 기반으로 포지션 인식
   - S10/S11이 실제 손익 데이터로 작동

2. **KIS Rate Limit 개선**
   - 주문 실행 전 잔고 1회 조회 후 캐시 공유
   - 주문 간 0.1~0.2초 간격 추가

### P1 — 이번 주 해결 (품질 저하 수준)

3. **confidence 필터 수정**
   - Decision Engine에서 `min_ai_confidence` 조건이 실제로 동작하는지 확인
   - confidence < 0.65인 신호는 발생 자체를 막기

4. **profile_assigned 마이그레이션 명시화**
   - db.py에 `ALTER TABLE trading_signals ADD COLUMN profile_assigned TEXT` 추가

### P2 — 다음 주 (개선 사항)

5. **S9 당일 청산 동작 확인**
   - 포지션이 있는 날 15:20에 실제 청산 실행 여부 검증

6. **Positions 실시간 UI 연동**
   - 체결 확인 구현 후 콘솔에서 현재 보유 포지션 실시간 확인

---

## 5. 결론

**실전 테스트로서의 의미**: S2~S5 AI 판단 파이프라인은 완전히 작동했다. Claude가 실제로 시장 데이터를 분석해 종목을 선별하고 프로파일을 배정했으며, KIS 모의 서버에 주문까지 전달됐다.

**핵심 미완성 항목**: 체결 확인이 없다. 주문이 KIS에 전달됐는지는 알지만 실제로 체결됐는지를 시스템이 모른다. 이 때문에 포지션 추적, 손익 계산, 복기, 학습이 모두 무력화됐다.

**실계좌 전환 조건**: 체결 확인 + Position Manager 정상 작동 + S9 청산 검증 완료 후.
