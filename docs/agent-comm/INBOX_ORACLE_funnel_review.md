# INBOX_ORACLE_funnel_review

## 역할
너는 Oracle이다. 아래 변경을 코드 리뷰하라.
코드 수정은 하지 말고, 결과를 `docs/agent-comm/OUTBOX_ORACLE_funnel_review.md`에 작성하라.

## 리뷰 대상
- `backend/api/routes/funnel.py`
- `backend/main.py`의 `funnel_router` import/include
- `backend/services/db.py`의 `_seed_system_settings()` 신규 schedule/risk seed
- `backend/static/console.html`의 settings API 경로, OPS_STEPS, funnel summary 연동 수정

## 확인할 것
- 인증 의존성 누락 여부
- DB 테이블/컬럼 존재 여부에 따른 500 위험
- 기존 settings API 응답 형식과 프론트 사용 방식 일치 여부
- Funnel Monitor/Today Control 숫자 하드코딩 제거 여부
- 기존 기능 파괴 가능성

## 이미 확인된 검증
```bash
.venv/bin/python -m py_compile backend/api/routes/funnel.py backend/main.py backend/services/db.py
python HTMLParser parse OK
curl /health 200
인증 후 curl /api/v1/funnel/summary ok true
```

## 출력 형식
- Critical / Major / Minor findings
- 수정 필요 여부
- 추가 테스트 권고
