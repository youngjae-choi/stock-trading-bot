# [폴백] 전체 AI 실패 — 시스템 단독 운영 모드

## 이 문서는 프롬프트가 아니라 시스템 동작 정의서

이 문서는 모든 AI 호출이 실패했을 때 시스템이 따라야 할 폴백 정책을 정의한다.
Python 코드(`fallback_handler.py`)가 이 정책을 구현한다.

---

## 트리거 조건

다음 중 하나라도 발생하면 "AI 실패 모드" 진입:
- Gemini 호출 실패 + Groq 호출 실패 + OpenRouter 호출 실패 (3중 폴백 모두 실패)
- Opus 호출 3회 재시도 모두 실패
- GPT 호출 3회 재시도 모두 실패
- AI 출력이 검증 게이트를 3회 연속 통과하지 못함

---

## 폴백 우선순위 (위에서부터 시도)

### 1순위: 어제 산출물 캐시 사용
- `data/ai_outputs/YYYY-MM-DD-1/` 디렉토리에서 같은 단계의 어제 산출물 로드
- 파일명 패턴 매칭으로 찾음 (예: `news_summary_*.json`)
- 사용 시 출력 파일에 `_from_yesterday` 접미어 추가
- 시스템 로그에 "어제 산출물 사용" 명시

### 2순위: 정량 룰 단독 운영
어제 산출물도 없으면, AI 입력 없이 시스템이 자체적으로 판단:

```python
# 의사 코드
default_market_tone = {
    "tone_score": 0.0,
    "tone_label": "neutral",
    "preferred_sectors": [],  # 비워둠
    "avoid_sectors": [],
    "confidence": 0.0,
    "fallback_reason": "all_ai_failed"
}

default_universe = load_default_universe_60()  # 정적 60종목 리스트

default_rulepack = {
    "risk_limits": {
        # 평소보다 30% 보수적
        "daily_loss_limit_rate": -0.02,  # 평소 -0.03보다 타이트
        "max_positions": 5,               # 평소 10에서 절반
        "stop_loss_rate": -0.015,         # 평소 -0.02보다 타이트
        "take_profit_rate": 0.03,         # 평소보다 작게
        "max_position_size_rate": 0.05,   # 평소 0.10에서 절반
    },
    "candidates": []  # 정량 점수 상위 5개만 시스템이 직접 선정
}
```

### 3순위: 당일 매매 전체 스킵
모든 폴백이 실패하면:
- 당일 매매 활성화하지 않음
- 기존 보유 포지션은 정상 청산 룰(15:20)만 적용
- PM에게 텔레그램 알림 발송 ("AI 시스템 장애, 매매 스킵")
- 다음날 정상 운영 재개 시도

---

## 단계별 폴백 매핑

| 단계 | 1순위 폴백 | 2순위 폴백 | 3순위 폴백 |
|---|---|---|---|
| 08:00 뉴스 요약 | Groq → OpenRouter | 어제 캐시 | tone_score=0 |
| 08:05 시장 톤 | (Opus 재시도) | 어제 캐시 | neutral 고정 |
| 08:30 스크리닝 | (Opus 재시도) | 어제 캐시 | 정량 점수 단독 |
| 08:45 RulePack | (GPT 재시도) | 어제 RulePack | 보수적 기본값 |
| 16:00 복기 | (Opus 재시도) | 스킵 | 자동 통계만 누적 |
| 16:30 일일 리포트 | (GPT 재시도) | 템플릿 | 텍스트 미생성 |
| 22:00 미국장 | Groq → OpenRouter | 스킵 | 다음날 08:00 자체 처리 |

---

## 알림 정책

### 즉시 알림 (텔레그램)
- KIS 토큰 갱신 실패
- Risk Circuit Breaker 발동
- 당일 매매 스킵 결정

### 일일 요약 알림 (콘솔에 표시)
- AI 호출 실패 카운트
- 폴백 사용 횟수
- Validator reject 카운트

### 알림 안 함
- AI 출력 confidence가 낮음 (단순히 보수적으로 운영)
- 단일 종목 손절 발생
- 어제 산출물 사용 (정상 폴백)

---

## 운영 콘솔 표시 (System Status 화면)

폴백 모드 진입 시 운영 콘솔에 명확히 표시:

```
[ALERT] System running in FALLBACK MODE
- Trigger: gemini_quota_exceeded + opus_api_error
- Active fallback: yesterday_cache (08:00 stage)
- Risk limits: REDUCED (max_positions 10 → 5)
- Recovery attempt: next at 09:30
```

---

## 복구 정책

### 자동 복구
- 폴백 진입 후 30분마다 정상 AI 호출 재시도
- 정상 응답 받으면 자동으로 정상 모드 복귀
- 단, 이미 그 단계 결과를 사용해 후속 단계가 실행됐다면 당일은 폴백 모드 유지 (혼용 금지)

### 수동 복구
- PM이 운영 콘솔에서 "Force Resume Normal Mode" 버튼 클릭 시
- 단, 다음 거래일부터 적용 (당일 혼용 위험)

---

## 폴백 이력 기록

모든 폴백 사용은 `logs/fallback_log.jsonl`에 1줄 1건으로 기록:

```json
{"timestamp":"2026-05-01T08:03:21+09:00","stage":"news_summary","reason":"gemini_quota_exceeded","fallback_used":"groq","success":true}
```

PM이 주간 검토 시 이 로그를 보고 어느 AI가 자주 실패하는지 파악.

---

## 이 문서의 위상

이 폴백 정책은 ADR-007의 구현 명세다. 변경 시 ADR도 함께 갱신.
프롬프트가 아니라 코드 동작 정의이므로 LLM에 직접 입력하지 않는다.
