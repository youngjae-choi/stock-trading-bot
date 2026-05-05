# Today Control / Trading Monitor / Expert Knowledge 개선 — 개발계획서 v0.1

## 원본 요구사항
> 1. Today Control 화면
> A. "오늘주문내역"을 "최근 주문내역"으로 변경하고 최신 5개만 표시 카드안에 자세히보기버튼를 만들고 이를 클릭하면 "Trade History" 화면으로 이동시켜줘.
> B. "Funnel Progress" 카드에서 자세히보기 버튼 만들고 그걸 누르면 "Funnel monitor"로 이동 시켜줘.
> C. 각 카드에서 새로고침 버튼 제거하고 우측 상단의 "새로고침"을 누르면 그냥 페이지 전체가 새로고침하는 걸로 하자.
>
> 2. Trading Monitor
> A. 계좌정보카드와 오늘적용정책카드 좌우 위치 변경
> B. 계좌정보에 예수금표시 오류 예수금 - 얼마, 주식매수- 얼마 이렇게 표시되어야 함.
> C. 보유포지션 모니터링카드 각 종목의 매수금액 필요, 단가표시시 소수점이하 삭제,
> D. 오늘적용정책카드 정말로 동적으로 동작하고 있는지 체크 시장톤에 매수, 매도, 현금사용유를 비중이 다른것이 아닌가? Setting값이 아닌 AI가 판단한 오늘의 매수, 매도 조건이 표현되야함. 가급적 자연어로 사람이 알아보게.
> E. 매수대기종목, 보유포지션카드 두카드 모두 LIVE로 변경하게 하였는데 화면깜빡임이 심한데 자연스럽게 바뀌는 Flont Engineering을 없는건가?
>
> 3. Trade History
> A. 첨부된 이미지의 카드 제거 - History만 확인/조회하는 페이지로 변경 해당 기능을 나중에 통계화면을 만들면 그때 다시 생성함.
>
> 4. Expert Knowledge
> A. 페이지기능수정 - 사용자 무조건 PDF 업로드 => 시스템 => LLM(Gemini or Opus)의뢰 (매매전략생성 없으면 없는대로도 괜찮음) => 생성된 전략을 사용자가 내용을 확인해서 승인 => 시스템이 매매전략을 반드시 Setting 값을 수정하여 반영하고 Setting 에 DATA설정이 없는 경우 메시지박스 출력 "OOO 기능을 Setting 화면에 추가여여야 합니다. 개발 후 재 요청해주세요"

## 의도 해석
- PM은 매일 운영자가 보는 화면 수와 승인 절차를 줄이고 싶다.
- `Settings`가 이미 매수/매도/리스크의 PM 승인 기준이므로 별도 `Approval Queue`는 중복이다.
- Today Control은 운영 허브, Trading Monitor는 실시간 감시, Trade History는 기록 조회, Expert Knowledge는 전략 입력/반영 플로우로 역할을 명확히 나눈다.

## 1차 구현 범위
- [ ] `Approval Queue` 메뉴/모바일 메뉴/화면 진입 숨김
- [ ] `Alert Center` 별도 메뉴 숨김
- [ ] Alert는 삭제하지 않고 Today Control의 운영 알림 요약으로 흡수
- [ ] Today Control: `오늘 주문내역` -> `최근 주문내역`
- [ ] Today Control: 최근 주문 최신 5개만 표시
- [ ] Today Control: 최근 주문 카드의 `자세히보기` 클릭 시 `Trade History` 화면 이동
- [ ] Today Control: `Funnel Progress` 카드의 `자세히보기` 클릭 시 `Funnel Monitor` 이동
- [ ] Today Control: 카드별 새로고침 버튼 제거
- [ ] Today Control: 우측 상단 `새로고침`은 전체 페이지 데이터 재조회로 통일
- [ ] Trading Monitor: `계좌정보`와 `오늘 적용 정책` 카드 좌우 위치 변경
- [ ] Trading Monitor: 계좌정보를 `예수금`, `주식매수 가능금액` 형태로 표시
- [ ] Trading Monitor: 보유포지션 종목별 매수금액 추가
- [ ] Trading Monitor: 단가/금액 표시에서 불필요한 소수점 제거
- [ ] Trading Monitor: 오늘 적용 정책은 `Settings` 값이 아니라 AI/시장톤/스크리닝/일일계획 결과를 사람이 읽는 자연어로 표시
- [ ] Trading Monitor: 매수대기종목/보유포지션 LIVE 갱신 시 전체 테이블 교체를 줄이고 변경된 값만 부드럽게 갱신
- [ ] Trade History: 요약 카드 제거, 거래 내역 조회 전용 화면으로 단순화

## 1차 변경 예상 파일
| 파일 | 변경 유형 | 이유 |
|---|---|---|
| `backend/static/console.html` | UI/JS 수정 | Today Control, Trading Monitor, Trade History, 메뉴 정리 |
| `backend/api/routes/orders.py` | 필요 시 API 보강 | 최근 주문 5개/계좌 표시 데이터 부족 시 보강 |
| `backend/services/engine/order_executor.py` | 필요 시 데이터 보강 | 매수금액/단가 산출 데이터 확인 |
| `docs/agent-comm/INBOX_GEMINI_phase_ui_ops_refactor.md` | 신규 | 프론트 구현 지시 |
| `docs/agent-comm/INBOX_EXECUTOR_phase_ui_data_support.md` | 신규 | 필요한 백엔드 데이터 보강 지시 |

## 1차 테스트계획
- [ ] 로그인 후 Today Control 진입
- [ ] `최근 주문내역` 카드가 최신 5개만 표시하는지 확인
- [ ] 최근 주문 `자세히보기` 클릭 시 `Trade History` 화면 이동
- [ ] Funnel `자세히보기` 클릭 시 `Funnel Monitor` 화면 이동
- [ ] Today Control 카드별 새로고침 버튼이 제거됐는지 확인
- [ ] 우측 상단 새로고침으로 Today Control 데이터가 다시 로드되는지 확인
- [ ] Trading Monitor에서 계좌정보/오늘 적용 정책 위치 변경 확인
- [ ] 계좌정보의 예수금/주식매수 가능금액 표시 확인
- [ ] 보유포지션의 매수금액/단가 정수 표시 확인
- [ ] LIVE 갱신 시 화면 전체 깜빡임이 줄었는지 확인
- [ ] Trade History 요약 카드 제거 확인
- [ ] 기존 smoke E2E 통과

## 2차 구현 범위: Expert Knowledge
- [ ] Expert Knowledge를 PDF 업로드 중심 화면으로 재설계
- [ ] PDF 업로드 API 추가
- [ ] 업로드 파일 저장/임시 처리 정책 결정
- [ ] LLM 분석 요청: Gemini 또는 Opus 선택 가능 구조
- [ ] LLM 결과를 `전략 후보`로 표시
- [ ] 사용자가 전략 내용을 확인 후 승인
- [ ] 승인 시 전략 항목을 기존 `Settings` 키에 매핑
- [ ] 매핑 가능한 Settings가 없으면 적용 차단
- [ ] 메시지: `"OOO 기능을 Setting 화면에 추가여야 합니다. 개발 후 재 요청해주세요"`
- [ ] 적용/차단/오류 내역 로그 기록

## 2차 변경 예상 파일
| 파일 | 변경 유형 | 이유 |
|---|---|---|
| `backend/static/console.html` | UI/JS 수정 | PDF 업로드/전략 승인 UX |
| `backend/api/routes/expert_knowledge.py` | API 수정 | PDF 업로드, 분석 요청, 승인/적용 |
| `backend/services/engine/expert_knowledge.py` | 서비스 수정 | LLM 분석 결과와 Settings 매핑 |
| `backend/services/settings_store.py` | 필요 시 보강 | Settings 적용/검증 헬퍼 |
| `docs/agent-comm/INBOX_EXECUTOR_expert_knowledge_pdf.md` | 신규 | 백엔드 구현 지시 |
| `docs/agent-comm/INBOX_GEMINI_expert_knowledge_pdf_ui.md` | 신규 | 프론트 구현 지시 |

## 2차 테스트계획
- [ ] PDF 미첨부 시 업로드 차단
- [ ] PDF 업로드 성공/실패 상태 표시
- [ ] LLM 분석 실패 시 재시도 가능
- [ ] 전략 후보가 없을 때 빈 상태 표시
- [ ] 승인 전 Settings 미반영 확인
- [ ] 승인 후 매핑 가능한 Settings 반영 확인
- [ ] 매핑 불가 항목은 지정 메시지 출력
- [ ] 적용 내역 로그 확인

## 요구사항 대조표
| 요구사항 | 1차 | 2차 | 비고 |
|---|---:|---:|---|
| Approval Queue 자동승인/불필요 정리 | 반영 |  | 1차에서 메뉴/화면 숨김 |
| Alert Center 역할 변경 | 반영 |  | Today Control 요약으로 흡수 |
| Today Control 주문/Funnel/새로고침 개선 | 반영 |  |  |
| Trading Monitor 카드/표시/LIVE 개선 | 반영 |  | 데이터 부족 시 백엔드 보강 |
| Trade History 카드 제거 | 반영 |  |  |
| Expert Knowledge PDF/LLM/Settings 반영 |  | 반영 | 범위가 커서 2차 |

## 완료 기준
- 1차: UI 정리, 데이터 표시, 화면 이동, smoke E2E 통과
- 2차: PDF 업로드부터 Settings 반영/차단까지 검증
