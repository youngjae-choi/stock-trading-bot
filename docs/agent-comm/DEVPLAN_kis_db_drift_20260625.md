# KIS↔DB 포지션 드리프트 정합 — 개발계획서 v0.1

## 원본 요구사항 (PM 발화 그대로 인용)
> (6/23 무결성 경고 조사 후) PM 선택: **"3. 근본 원인(FillPoller 매수 기록 누락) 본격 수정 — 큰 작업이라 STEP 1~4 + 개발계획서부터"**
>
> 후속 결정(2026-06-25):
> - 접근 순서: **A→B 순차** (안전망 우선 → FillPoller 경화)
> - 복구 범위: **앞으로만 수정** (과거 손익 역산 복구 안 함)
> - **라이브 드리프트 긴급 점검 먼저** (완료됨)

## 긴급 점검 결과 (착수 전 확인 완료)
- KIS 실보유 9종목 **전부 봇이 정확 수량 + 손절가로 추적 중** → **안전 비상 없음**
- 매장 시작 시 KIS 보유분을 원가(KIS 평단)와 함께 흡수하고 손절을 거는 **auto_import 자가치유 안전망 작동 확인**
- 결론: 드리프트는 과거 기록 누락의 잔재. 자본 보호는 정상. 따라서 본 작업은 **긴급 핫픽스가 아닌 정확성·예방 개선**으로 진행.

## 근본 원인 (코드 확인)
1. **매수 체결 기록 누락** — FillPoller가 ETN Q접두어 심볼 불일치 / output2 `tot_ccld_qty` 누락 / fills INSERT 스킵으로 매수 체결을 DB에 못 남기는 경우 ([fill_poller.py:128-131, 738-747](backend/services/engine/fill_poller.py#L128))
2. **정합이 KIS 실보유 미확인 후 매수 취소** — `eod_reconcile_no_kis_fill`로 체결된 매수를 취소 → 포지션이 KIS에만 잔존 ([order_reconciliation.py:139](backend/services/engine/order_reconciliation.py#L139))
3. **fills 기반 실현손익이 auto_import 매도를 누락** — matched_qty=min(buy,sell)에서 짝 매수가 없어 0 처리 → P&L SSOT 불일치 ([trade_pairs.py:154](backend/services/engine/trade_pairs.py#L154), 기존 과제 [[project_daily_score_ssot_pending]])
4. **무결성 체크 이월 오탐** — 단일일자 창이 전일 매수·당일 매도(균형) 포지션을 오경고 ([position_integrity.py:277](backend/services/engine/position_integrity.py#L277))

## 구현 범위

### Phase A — 안전망·정확성 (출혈 차단)
- [ ] **A1. 정합 취소 가드**: `reconcile_orders_with_kis`가 매수를 `no_kis_fill`로 취소하기 전 **KIS 실잔고 조회** → 보유 확인되면 취소 대신 체결 기록(원가=KIS 평단). 보유 없을 때만 취소.
- [ ] **A2. P&L 정합**: auto_import / 정합 흡수 포지션이 매도될 때 fills 기반 실현손익에서 누락되지 않도록 — 흡수 시점에 **원가 기반 합성 매수 fill 기록** 또는 daily_summary가 position entry_price를 fallback 원가로 사용. (SSOT 일관성)
- [ ] **A3. 무결성 오탐 수정**: 이월 포지션(전일 매수·당일 매도)을 단일일자 창이 오경고하지 않도록 carryover 인지 보정.

### Phase B — FillPoller 경화 (예방)
- [ ] **B1. 심볼 정규화**: ETN Q접두어 등 전 경로에 `norm_symbol` 일관 적용.
- [ ] **B2. output2 처리**: `tot_ccld_qty` 누락 / ETN price=0 케이스 안전 처리(스킵 대신 보정/재시도).
- [ ] **B3. fail-loud**: fills INSERT 스킵/실패 시 CRITICAL 로그 + 알림, 기록 후 검증(_recorded_fill_qty 재확인).

## 변경 파일 목록 (예상)
| 파일 경로 | 변경 유형 | 변경 이유 |
|-----------|-----------|-----------|
| `backend/services/engine/order_reconciliation.py` | 수정 | A1 취소 전 KIS 잔고 가드 |
| `backend/services/engine/residual_reconciliation.py` 또는 auto_import 경로 | 수정 | A2 원가 기반 합성 fill |
| `backend/services/engine/daily_summary.py` / `trade_pairs.py` | 수정 | A2 P&L fallback 원가 |
| `backend/services/engine/position_integrity.py` | 수정 | A3 이월 오탐 보정 |
| `backend/services/engine/fill_poller.py` | 수정 | B1·B2·B3 |
| `tests/` (단위·통합) | 신규 | TDD |
| `tests/e2e/` | 신규 | Phase별 E2E |
| `docs/manual/` | 수정 | 정합·체결 동작 문서화 |

## 요구사항 대조표
| 요구사항 항목 | 계획서 반영 | 비고 |
|---------------|------------|------|
| FillPoller 매수 기록 누락 근본 수정 | ✓ B1·B2·B3 | |
| A→B 순차 진행 | ✓ Phase A 먼저 | |
| 앞으로만 수정 (과거 복구 안 함) | ✓ | 과거 역산 비범위 |
| 라이브 드리프트 긴급 점검 선행 | ✓ 완료 | 비상 없음 확인 |
| 미추적 포지션 손절 보호 | ✓ 이미 작동(auto_import) | 추가 보강은 A2로 |

## 추가 제안 항목 (PM 승인 필요)
- **A2를 P&L SSOT 통합 과제와 병합** — 이미 메모리에 있는 `project_daily_score_ssot_pending`(Daily Results vs Review 카드 불일치)와 뿌리가 같음. 따로 고치면 또 어긋남. **함께 단일 집계모듈로 가는 것을 제안.** (PM 결정 필요)

## 완료 기준
- [ ] 단위테스트: 취소 가드(KIS 보유 有/無), 합성 fill 원가, 이월 오탐, ETN 심볼/output2
- [ ] 통합테스트: 매수누락→정합→포지션·P&L 정합 시나리오
- [ ] E2E (Playwright): Phase별 시나리오 추가·전체 통과
- [ ] 빌드 에러 0개
- [ ] `docs/manual/` 업데이트
- [ ] 실데이터 회귀: 무결성 경고 오탐 0, KIS↔DB 순포지션 일치

## 리스크 / 주의
- 라이브 매매 핵심 경로 → TDD 필수, 합성 fill 조건 엄격(진짜 no-fill 취소를 막지 않도록)
- 정합에 KIS 잔고 조회 추가 → KIS 호출 증가(서버 내부 실행·레이트리밋 준수)
- DB 스키마 변경 시 **백엔드 서버 중지 후 마이그레이션** (과거 SQLite corrupt 사례)
- 구현은 Task 서브에이전트 위임(기계적 부분 sonnet), 커밋은 지휘자만
