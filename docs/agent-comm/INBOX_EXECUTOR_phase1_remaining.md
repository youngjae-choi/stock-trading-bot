# INBOX_EXECUTOR_phase1_remaining

## 역할
너는 Executor(Codex)다. 아래 작업을 수행하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_phase1_remaining.md`에 결과를 작성하라.

Gemini가 quota 소진 상태라 프론트도 Codex가 담당한다.
수정 대상: `backend/static/console.html` (단일 파일)

---

## 작업 1 — Positions 화면의 "오늘 주문내역" 새로고침 버튼 제거

### 위치 확인
아래 패턴을 찾는다:
```html
<div class="card-title">
  <span>오늘 주문내역</span>
  <button class="btn" onclick="loadTodayOrders()">새로고침</button>
</div>
```

이 블록에서 `<button class="btn" onclick="loadTodayOrders()">새로고침</button>`만 제거한다.
`<span>오늘 주문내역</span>`은 유지한다.

---

## 작업 2 — loadTradingPositions() 깜빡임 완화

현재 `loadTradingPositions()` 함수를 찾아서 `tbody.innerHTML = html`로 전체 교체하는 방식을
row-by-row 업데이트로 교체한다.

참고: `loadTradingCandidates()`가 이미 올바른 패턴으로 구현되어 있다 (data-code 속성, 기존 row 유지).

`loadTradingPositions()`도 동일 패턴으로:
1. 포지션 목록에서 각 종목을 `data-code` (또는 `data-symbol`) 속성으로 식별
2. 사라진 종목 row 제거
3. 기존 종목은 HTML이 바뀐 경우만 업데이트
4. 신규 종목 추가

구체적인 컨테이너 id와 렌더 함수는 파일에서 직접 확인해서 적용한다.
`tm-sell-list` 컨테이너와 그 안의 position row들이 대상이다.

---

## 검증

```bash
python3 -c "
from html.parser import HTMLParser
with open('backend/static/console.html', encoding='utf-8') as f:
    HTMLParser().feed(f.read())
print('HTML parse OK')
"
```

grep 확인:
```bash
# 오늘 주문내역 새로고침 버튼 제거 확인 (0개여야 함)
grep -c "오늘 주문내역.*새로고침\|새로고침.*오늘 주문내역" backend/static/console.html || echo "0"
```

---

## 완료 체크리스트

- [ ] "오늘 주문내역" 카드 새로고침 버튼 제거
- [ ] loadTradingPositions() row-by-row 업데이트 적용
- [ ] HTML parse OK

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_phase1_remaining.md`에 작성하라.
