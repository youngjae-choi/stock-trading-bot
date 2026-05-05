먼저 핵심 흐름 다이어그램부터:
  ::view-transition-group(*),
  ::view-transition-old(*),
  ::view-transition-new(*) {
    animation-duration: 0.25s;
    animation-timing-function: cubic-bezier(0.19, 1, 0.22, 1);
  }
VvisualizeVvisualize show_widget이 4단 구조를 머리에 두고 기획안을 정리하면 다음과 같습니다.

자동매매 시스템 최종 기획안
0. 핵심 설계 원칙 한 문장
"AI는 분석만, 시스템이 실행한다. AI 출력은 모두 검증 게이트를 통과해야 매매 엔진에 도달한다."
이 원칙 하나만 지키면 AI가 허언/오판/사고를 내도 매매 사고로 번지지 않습니다. PM 님이 보내주신 다른 AI의 기획도 같은 결론이고, 프로젝트 문서 체계(AGENTS.md의 게이트 패턴)와도 동일한 철학입니다.

1. 시스템 vs AI 권한 경계 (가장 중요)
항목시스템 (Python)AI (Gemini/Opus/GPT)실시간 매수/매도 결정✅ 단독 권한❌ 절대 금지주문 전송✅ 단독 권한❌ 절대 금지손절/익절 조건 변경✅ Risk Guard만❌ 절대 금지일일 손실 한도✅ 고정값(코드)❌ 변경 불가시장 톤 판단❌✅ Opus뉴스 요약❌✅ GeminiRulePack JSON 구조화❌✅ GPTRulePack 검증✅ Validator❌복기 해석❌✅ Opus + Gemini
AI 출력은 항상 **"제안서"**이고, 시스템은 **"승인자 + 실행자"**입니다.

2. AI 위원회 역할 분담
PM 님 표에 있는 "Gemini → Opus → 시스템"은 좋은 흐름이지만, GPT의 RulePack 구조화 단계가 빠져 있습니다. 이걸 넣어야 Opus의 정성 판단이 안전한 JSON으로 변환됩니다.
Gemini (1차)  : 넓게 읽고 정리 — 뉴스, 미국장, 공시 요약
Opus   (2차)  : 깊게 판단 — 시장 톤, 유니버스 필터, 복기 해석
GPT    (3차)  : 실행 가능하게 변환 — RulePack JSON, 자연어 리포트
시스템 (최종): 검증 → 실행 → 모니터링 → 차단

3. PM 님 시간표 → 최종 기획 (고민 4건 답변 포함)
시간작업담당산출물다음 단계 트리거07:45KIS 토큰 갱신시스템token_status.json성공 시 08:00 스케줄러 활성화08:00야간 미국장 + 뉴스 요약Gemininight_brief_YYYYMMDD.md파일 생성 완료 시08:05시장 톤 최종 판단Opusmarket_tone_YYYYMMDD.md파일 생성 완료 시08:15유니버스 필터시스템universe_filtered.json종목 수 ≥ 최소값일 때08:30하이브리드 스크리닝Opus + 시스템screening_top_N.json08:45RulePack JSON 생성GPTrulepack_draft.json08:50RulePack 검증시스템 Validatorrulepack_active.json 또는 rulepack_rejected.log통과 시에만 09:00 매매 활성화09:00실시간 매매룰 엔진주문 로그11:30중간 스냅샷시스템midday_snapshot.md15:20당일매매 청산룰 엔진청산 로그16:00AI 복기 (학습 재료)Opus + Geminireview_YYYYMMDD.md16:30일일 리포트 작성GPTdaily_report_YYYYMMDD.md발송 안 함18:00데이터 백업시스템백업 완료 로그22:00야간 미국장 관찰Geminius_market_brief.md다음날 08:00 입력
PM 님 고민 4건에 대한 답
고민 ① "시스템은 어떻게 Gemini가 작업을 끝냈는지 알 수 있지?"
→ 파일 기반 트리거 방식을 권합니다. AI가 응답 스트리밍을 쓰니 "끝났는지" 직접 감지가 어렵습니다. 대신:
1. Python이 Gemini API 호출 (동기 요청)
2. Gemini가 응답 완료 → Python이 응답을 받음
3. Python이 `night_brief_20260501.md`를 디스크에 저장
4. 파일 저장 완료가 곧 "작업 끝남" 신호
5. Python이 다음 단계(Opus 호출)를 시작
CLI 호출이 아니라 API 호출이라면 Python이 응답을 받는 시점이 곧 종료 시점입니다. CLI를 쓰면 subprocess.run() 의 returncode == 0 으로 판단합니다. 절대 "AI가 알아서 다음 AI를 부르는" 구조는 만들지 마세요. 시스템이 모든 단계를 손에 쥐고 있어야 합니다.
고민 ② "AI 하이브리드 스크리닝이 구체적으로 어떤 작업인가?"
→ 두 단계로 나누세요.
[정량 단계 - 시스템]
유니버스 60종목 → 거래대금 / 변동성 / 호가스프레드 / 회전율
점수 계산 → 상위 30종목 후보

[정성 단계 - Opus]
30종목 후보 + 오늘 시장 톤 + 뉴스 요약을 입력
출력: 각 종목별 (사유, 위험요인, 신뢰도 0~1)
시스템이 다시 정량 점수 + 정성 신뢰도로 가중평균
→ 최종 Top 10~15
중요: Opus는 "이거 사라"가 아니라 "이 종목은 OO 이유로 적합도 0.7"이라고만 말합니다. 매수 결정은 시스템이 룰로 합니다.
고민 ③ "RulePack 잘못 작성되면? 보호장치를 어떻게 걸지?"
→ 이게 시스템의 핵심입니다. 3단 검증 게이트를 걸어야 합니다.
[게이트 1: Schema 검증]
- 필수 필드 존재 확인 (max_positions, stop_loss_rate 등)
- 타입 확인 (숫자/문자/배열)
- 값 범위 확인 (stop_loss_rate는 -10% ~ 0% 사이)
실패 → 즉시 reject, 어제 RulePack 사용

[게이트 2: Risk Guard]
- daily_loss_limit이 -3%보다 큰가? (이건 절대 변경 불가, 코드에 하드코딩)
- max_positions가 시스템 한도 20을 넘는가?
- stop_loss_rate가 -1%보다 느슨한가?
실패 → 위반 항목만 안전한 기본값으로 덮어씀, 경고 로그

[게이트 3: Sanity Check]
- 어제 RulePack과 비교해서 변동폭이 50% 넘는가?
- 백테스트 최근 5일 결과로 시뮬레이션 → 손실 -5% 넘으면 reject
실패 → reject, PM에게 알림 (텔레그램 등)
핵심: daily_loss_limit, max_positions, stop_loss_rate 같은 리스크 룰은 AI가 절대 변경 못 하는 상수로 코드에 박아두세요. RulePack에 있어도 무시.
고민 ④ "오늘의 복기 내용을 시스템이 학습하려면?"
→ "AI가 자동 학습"은 위험합니다. 대신 반복 가능한 피드백 루프를 만드세요.
1. Opus가 복기 리포트 작성 → review_20260501.md
   - 성공 패턴 / 실패 패턴 / 개선 후보 제안
   - 단, "내일부터 손절 -1%로 바꿔라" 같은 직접 변경 제안은 금지

2. GPT가 패턴을 구조화 → review_patterns.json
   - {"pattern": "갭상승 +3% 종목 추격매수 실패율 70%", "samples": 8}

3. 시스템이 누적 통계 DB에 저장 (review_stats.db)

4. 주 1회 PM이 직접 검토 → "이 패턴 충분히 쌓였네, RulePack 기본값에 반영"
   - PM이 settings.json 수동 업데이트
   - AI가 자동으로 룰을 바꾸는 일은 절대 없음
즉, 학습은 통계 누적까지만 자동, 룰 변경은 사람의 판단입니다.
고민 ⑤ "리포트는 발송 안 하고 결과만 작성하면 되겠다"
→ 좋습니다. 16:30 단계는 daily_report_YYYYMMDD.md를 디스크에만 저장하고, PM이 운영 콘솔(첨부 화면의 Review & Audit 탭)에서 확인하는 구조로 가세요.

4. 운영 콘솔(첨부 HTML)과 기획의 매핑
PM 님이 만든 9개 화면이 이 기획을 거의 그대로 받아냅니다.
화면시스템에서 보여줄 데이터작업 단계Today Control토큰 상태, 현재 단계, 활성 RulePack 요약전체 흐름 모니터링AI RulePack오늘 사용 중인 RulePack JSON, AI Source 표시(Gemini/Opus/GPT 누가 어디 기여), 검증 게이트 통과 여부08:00~08:50Funnel Monitor유니버스 → 필터 → 스크리닝 → Top N 단계별 종목 수08:15~08:30Live Decisions룰 엔진 실시간 판단 로그 (왜 매수/매도/스킵했는지)09:00~15:20Positions & Exit현재 포지션, 손절/익절 거리09:00~15:20Execution & RiskRisk Guard 상태, 일일 손실 잔여, Circuit Breaker 발동 여부상시Data & APIKIS/AI Provider 상태, Gemini Daily Usage 3/10 같은 quota 표시상시Review & Audit복기 리포트, AI Source별 기여 추적16:00~Settings리스크 한도값(읽기 전용 표시 + PM이 수동 변경)수시
특히 AI RulePack 화면에 "AI Source" 표시를 꼭 넣어주세요. 나중에 "왜 이런 룰이 나왔지?"를 추적할 때 필수입니다.

5. 무료 LLM 사용 전략 (다른 AI가 추천한 부분 재정리)
다른 AI 추천대로 가되, 자동매매 관점에서 보수적으로 좁혔습니다.
모델역할사용 시점일일 호출 예산Gemini (무료)장문 뉴스/미국장 요약08:00, 16:00, 22:005~10회Opus (유료)시장 톤, 복기08:05, 16:002~3회GPT (유료)RulePack 구조화, 일일 리포트08:45, 16:302~3회Groq/OpenRouter (무료)Gemini fallbackquota 초과 시만비상용
원칙: AI 호출 실패해도 시스템이 멈추지 않게 — 어제 결과 캐시 → 정량 룰만으로 진행 → PM에게 알림.