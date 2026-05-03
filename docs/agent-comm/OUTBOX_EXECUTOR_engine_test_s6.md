# OUTBOX_EXECUTOR_engine_test_s6

## 작업 결과

- `backend/static/console.html`의 `screen-engine-test` 단계별 카드 그리드에 S6 카드를 추가했습니다.
- S6 버튼은 `engineTestRun('s6')`을 호출하며, `STEP_URLS.s6`는 `/api/v1/decision/activate`로 연결했습니다.
- `전체 결과 지우기` 동작에서 S6 배지와 결과 영역도 함께 초기화되도록 `engineTestClearAll()` 대상에 `s6`를 추가했습니다.

## 변경 파일

- `backend/static/console.html`

## 검증 결과

```bash
$ python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
HTML OK

$ grep -n "et-card-s6\|decision/activate" backend/static/console.html
1618:            <div class="card" id="et-card-s6">
2526:        s6: "/api/v1/decision/activate"
2761:      await fetchJson("/api/v1/decision/activate", { method: "POST" });
```

## 참고

- `decision/activate`의 2761행은 기존 Live Decisions 수동 활성화 버튼용 호출입니다.
- 브라우저 수동 확인은 실행하지 않았습니다.
