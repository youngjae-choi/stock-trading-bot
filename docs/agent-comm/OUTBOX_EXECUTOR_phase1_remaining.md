# OUTBOX_EXECUTOR_phase1_remaining

## 수행 결과

- `backend/static/console.html`의 Positions 화면 `오늘 주문내역` 카드에서 `loadTodayOrders()` 새로고침 버튼을 제거했습니다.
- `loadTradingPositions()`는 `tm-sell-list` 내부 포지션 row를 `data-symbol` 기준으로 유지/삭제/갱신/추가하는 row-by-row 업데이트 방식으로 적용되어 있음을 확인했고, 빈 상태 안내가 남아 있는 상태에서 포지션 row가 추가될 때 기존 안내가 제거되도록 보강했습니다.

## 변경 파일

- `backend/static/console.html`
- `docs/agent-comm/OUTBOX_EXECUTOR_phase1_remaining.md`

## 검증 결과

### HTML parse

```bash
python3 -c "
from html.parser import HTMLParser
with open('backend/static/console.html', encoding='utf-8') as f:
    HTMLParser().feed(f.read())
print('HTML parse OK')
"
```

결과:

```text
HTML parse OK
```

### 오늘 주문내역 새로고침 버튼 제거 확인

```bash
grep -c "오늘 주문내역.*새로고침\|새로고침.*오늘 주문내역" backend/static/console.html || echo "0"
```

결과:

```text
0
0
```

참고: `grep -c`가 매치 0개를 출력한 뒤 종료 코드 1을 반환하여 `|| echo "0"`도 실행되었습니다. 매치 개수는 0개입니다.

## 완료 체크리스트

- [x] "오늘 주문내역" 카드 새로고침 버튼 제거
- [x] `loadTradingPositions()` row-by-row 업데이트 적용
- [x] HTML parse OK

## 잔여 리스크 / 확인 필요

- 브라우저 수동 확인과 E2E 전체 회귀 테스트는 이번 지시의 검증 명령 범위 밖이라 실행하지 않았습니다.
- 작업 시작 전부터 `backend/static/console.html`에는 다른 Today Control/Trading Monitor 관련 미커밋 변경이 존재했습니다. 해당 변경은 되돌리지 않았고, 이번 지시 범위의 변경만 추가했습니다.
