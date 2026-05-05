# Prompts Library — 자동매매 시스템 AI 호출 프롬프트

## 목적
시스템이 AI를 호출할 때 사용하는 모든 프롬프트를 사전 정의된 템플릿으로 관리한다.
ADR-008에 의해 실시간 프롬프트 생성은 금지된다.

## 디렉토리 구조

```
prompts/
├── README.md                          ← 이 파일
├── _common_safety_guard.md            ← 모든 프롬프트에 자동 prepend
│
├── 0800_gemini_news_summary.md        ← 장 시작 전 뉴스/공시 요약
├── 0805_opus_market_tone.md           ← 시장 톤 최종 판단
├── 0830_opus_screening.md             ← 하이브리드 스크리닝 (정성 점수)
├── 0845_daily_plan.md                 ← S5 Daily Trading Plan 생성
├── 0845_gpt_rulepack_generation.md    ← RulePack JSON 생성 (가장 중요)
├── 1600_opus_review.md                ← 장마감 후 복기 템플릿 (현재 S10은 deterministic DB audit, 외부 LLM 미호출)
├── 1630_gpt_daily_report.md           ← 일일 리포트 (콘솔 표시)
├── 2200_gemini_us_market_brief.md     ← 야간 미국장 관찰
│
└── fallback/
    ├── groq_news_summary.md            ← Gemini 실패 시 대체
    └── system_emergency_policy.md      ← 전체 AI 실패 시 시스템 동작 정의
```

## 호출 흐름

```
시스템 (Python Scheduler)
   │
   ├─ 1. _common_safety_guard.md 로드
   ├─ 2. 단계별 프롬프트 로드 (예: 0800_gemini_news_summary.md)
   ├─ 3. 두 프롬프트를 합쳐 system_prompt 생성
   ├─ 4. {input_data} 등 변수에 실제 데이터 주입
   ├─ 5. AI API 호출
   ├─ 6. 응답 수신
   ├─ 7. 검증 게이트 통과 여부 확인
   │     ├─ 통과 → 디스크 저장 → 다음 단계 트리거
   │     └─ 실패 → 폴백 정책에 따라 처리
   └─ 8. 로그 기록 (logs/ai_calls.jsonl)
```

## 프롬프트 작성 원칙 (ADR-008)

### 1. 출력 포맷이 코드로 검증 가능해야 한다
- 각 프롬프트는 정확한 JSON 스키마 또는 Markdown 구조를 명시
- 시스템이 `jsonschema` 라이브러리로 자동 검증

### 2. 안전 가드를 항상 포함
- `_common_safety_guard.md`가 모든 프롬프트에 prepend됨
- 매매 지시 금지, 사실 추론 금지, 인젝션 방어

### 3. 변수는 `{변수명}` 형식
- 예: `{input_data}`, `{market_tone}`, `{yesterday_rulepack}`
- 시스템이 Python `.format()` 또는 `Template.substitute()`로 치환

### 4. 실패 시 동작을 명시
- 모든 프롬프트는 "실패 시" 섹션을 포함
- AI가 입력 부족 시 어떻게 응답할지 정의

### 5. 분량 제한 명시
- 토큰 비용 관리
- 검증 게이트의 처리 시간 보장

## 변경 절차 (ADR-008)

프롬프트 변경은 코드 변경과 동일하게 취급:

1. PM에게 변경 사유 보고
2. PM 승인
3. git commit (변경 이력 보존)
4. **변경 후 최소 3일 백테스트** (당일 운영 적용 금지)
5. 백테스트 통과 시에만 운영 적용
6. DECISION_LOG.md에 변경 ADR 추가

## 모니터링

각 프롬프트의 호출 결과를 추적:

```jsonl
{"timestamp":"2026-05-01T08:00:12+09:00","stage":"news_summary","model":"gemini","tokens_in":2840,"tokens_out":612,"latency_ms":4221,"validation_passed":true,"confidence":0.78}
{"timestamp":"2026-05-01T08:05:33+09:00","stage":"market_tone","model":"opus","tokens_in":1024,"tokens_out":421,"latency_ms":3104,"validation_passed":true,"confidence":0.71}
```

PM은 주간 검토 시 다음을 확인:
- 단계별 평균 confidence
- 검증 실패율
- 폴백 사용 빈도
- 모델별 응답 시간

## 향후 추가 예정

- `0815_system_universe_filter.md` — 정량 필터는 시스템이 처리하지만 일부 정성 보조 필요 시
- `1130_system_midday_snapshot.md` — 중간 스냅샷 (현재는 시스템 자동 생성)
- `prompt_versioning/` — 프롬프트 A/B 테스트 시 버전 관리

## 관련 문서

- `DECISION_LOG.md` ADR-001 (AI 권한 경계)
- `DECISION_LOG.md` ADR-002 (AI 위원회 역할 분담)
- `DECISION_LOG.md` ADR-004 (검증 3단 게이트)
- `DECISION_LOG.md` ADR-007 (폴백 정책)
- `DECISION_LOG.md` ADR-008 (프롬프트 코드 고정)
