# OUTBOX — Oracle (S1 코드 리뷰 결과)

작성일: 2026-04-29  
검토자: Oracle (Sisyphus / Claude Sonnet 4.6)  
검토 대상 커밋: HEAD (574f37b 이후 신규 파일 기준)

---

## 종합 판정: ✅ 조건부 승인 (즉각 차단 이슈 없음, 경미한 개선 권고 3건)

---

## 항목별 검토 결과

### 1. APScheduler job 실패 시 서버 전체에 영향을 주지 않는가

**결과: ✅ 이상 없음**

- `job_refresh_kis_token`은 전체를 `try/except`로 감싸고 `logger.error`만 남긴 뒤 정상 반환 → job 예외가 서버 프로세스로 전파되지 않음.  
- APScheduler 자체도 job 함수에서 발생한 예외를 내부에서 캐치해 scheduler 루프를 유지하므로 이중 보호 구조.

**경미한 개선 권고 (P3)**:  
placeholder job 5개(`job_market_tone_analysis` 등)에는 `try/except`가 없다.  
현재 단계에서는 실제 예외가 발생할 코드가 없어 무해하지만, S2~S13 실 구현 시 개발자가 try/except 추가를 누락할 위험이 있다.  
→ 각 placeholder에 최소한 skeleton try/except를 미리 삽입하거나, 공통 래퍼 데코레이터를 도입할 것을 권고.

---

### 2. KIS 토큰 갱신 job이 중복 실행되지 않는가 (lock/singleton 확인)

**결과: ✅ 이상 없음 (구조적 보호 확인됨)**

- `scheduler_instance`는 모듈 레벨 전역 싱글턴으로 FastAPI 프로세스당 1개 보장.  
- `add_job(..., replace_existing=True)` 로 등록 — 동일 `id` 중복 등록 불가.  
- CronTrigger는 하루 1회(07:45 KST) 발화하므로 실질적 중복 실행 가능성 없음.

**경미한 개선 권고 (P3)**:  
`job_refresh_kis_token` 내부에서 `kis_client.token = None` / `kis_client.token_expires_at = 0.0`을 직접 수정한다.  
이는 `kis_client` 내부 상태를 외부에서 직접 건드리는 것으로, 캡슐화 위반이다.  
→ `kis_client`에 `invalidate_token()` 또는 `force_refresh()` 메서드를 추가해 scheduler가 내부 구현에 의존하지 않도록 리팩터링 권고.

---

### 3. scheduler lifespan이 FastAPI shutdown 시 정상 종료되는가

**결과: ✅ 이상 없음**

`main.py:53`의 `scheduler_instance.shutdown(wait=False)` 는 `yield` 이후 블록에 위치 → FastAPI shutdown hook에서 정상 호출됨.

**경미한 개선 권고 (P3)**:  
`wait=False` 는 실행 중인 job을 기다리지 않고 즉시 종료한다.  
S1 단계의 placeholder job들은 I/O 없이 즉시 반환하므로 무해하지만,  
S9(당일 청산) / S12(데이터 백업) 같이 실제 I/O가 포함되는 단계에서는 `wait=True` 혹은 timeout 방식으로 변경이 필요하다.  
→ S9 구현 시점 이전에 `wait=True`로 변경할 것을 권고.

---

### 4. 기존 lifespan 코드(initialize_database, initialize_auth)가 깨지지 않는가

**결과: ✅ 이상 없음**

`main.py:44-54` lifespan 순서:
```
validate_config()       # 기존
initialize_database()   # 기존
initialize_auth()       # 기존
scheduler_instance.start()  # 신규 — 기존 초기화 완료 후 추가
yield
scheduler_instance.shutdown(wait=False)  # 신규
```

- 기존 초기화 함수 3개의 호출 순서·시그니처가 변경되지 않음.  
- scheduler start가 마지막에 위치해 DB/Auth 의존성이 모두 준비된 후 job이 등록됨.  
- 라우터 등록 순서(`app.include_router(scheduler_router)`)도 기존 router 뒤에 위치 — 충돌 없음.

---

### 5. /api/v1/scheduler/status 가 auth guard를 올바르게 적용했는가

**결과: ✅ 이상 없음**

```python
# routes/scheduler.py:23-25
@router.get("/status")
async def get_scheduler_status(
    _user: Annotated[dict, Depends(require_console_user)],
```

- `require_console_user` → `SESSION_COOKIE_NAME` 쿠키 검증 → 미인증 시 `HTTP 401 LOGIN_REQUIRED` 반환.  
- `_user` 언더스코어 표기는 "의존성은 실행하되 결과는 사용 안 함" 의도를 명확히 표현 — 올바른 패턴.  
- 엔드포인트가 스케줄러 내부 상태(job 목록, next_run_time)를 노출하므로 인증 적용 필수인데 올바르게 처리됨.

---

## 수정 필요 항목 요약

| 우선순위 | 항목 | 파일 | 조치 |
|----------|------|------|------|
| P3 (권고) | placeholder job들에 try/except skeleton 추가 | `services/scheduler.py` | S2 구현 전 선제 추가 권고 |
| P3 (권고) | `kis_client` 내부 상태 직접 수정 → 캡슐화 메서드로 교체 | `services/scheduler.py`, `services/kis/common/client.py` | S1 이후 리팩터링 시 처리 |
| P3 (권고) | `shutdown(wait=False)` → S9 구현 전 `wait=True` 검토 | `main.py:53` | S9 착수 시점에 재검토 |

즉각 차단(P1), 수정 필요(P2) 항목 없음.

---

## 결론

S1 Scheduler 구현은 아키텍처·보안·기존 기능 파괴 관점에서 모두 안전하다.  
세 가지 P3 권고는 현재 단계에서 블로커가 아니며 이후 단계 구현 시점에 처리하면 된다.  
**S1 머지 승인.**
