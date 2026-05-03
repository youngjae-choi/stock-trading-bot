# INBOX_EXECUTOR_halt_resume_and_health

## 작업 목적

1. **긴급정지 후 복귀 기능 추가** — 현재 긴급정지 후 복귀할 방법이 없음
2. **`/api/v1/bot/data-health` 실 데이터로 개선** — KIS 토큰 유효성 실제 확인, WebSocket "미구현" 명시

---

## Task 1 — 긴급정지 복귀 (Resume) 기능

### 1-A. `backend/services/console_state.py`

`trigger_emergency_halt()` 함수 바로 아래에 `trigger_resume()` 함수를 추가한다.

```python
def trigger_resume() -> dict[str, Any]:
    """Clear the halted state and return to running mode."""
    logger.info("START: console_state.trigger_resume")
    _CONSOLE_STATE["mode"] = "AUTO"
    _CONSOLE_STATE["engine_status"] = "running"
    _CONSOLE_STATE["emergency_halt"] = False
    _CONSOLE_STATE["overview"]["health"]["risk_guard"] = {
        "status": "ok",
        "detail": "운영 재개. 신규 주문 허용.",
    }
    now = datetime.now(timezone.utc).astimezone()
    _CONSOLE_STATE["overview"]["logs"].insert(
        0,
        {
            "time": now.strftime("%H:%M"),
            "text": "운영 재개. 자동 주문 차단이 해제되었습니다.",
        },
    )
    logger.info("SUCCESS: console_state.trigger_resume")
    return {
        "halted": False,
        "mode": _CONSOLE_STATE["mode"],
        "engine_status": _CONSOLE_STATE["engine_status"],
        "updated_at": _utc_now_iso(),
        "live": False,
        "source": "backend",
        "message": "Resume applied. Console state returned to running.",
    }
```

### 1-B. `backend/api/routes/bot.py`

`trigger_emergency_halt` import에 `trigger_resume`도 추가한다.

`halt_bot_control()` 함수 바로 아래에 resume 엔드포인트를 추가한다:

```python
@router.post("/control/resume")
async def resume_bot_control():
    """Clear the emergency halt state and resume auto operation."""
    endpoint = "/api/v1/bot/control/resume"
    try:
        logger.info("START: %s", endpoint)
        payload = trigger_resume()
        logger.info("SUCCESS: %s", endpoint)
        return _build_logged_success_response(
            endpoint=endpoint,
            method="POST",
            payload=payload,
            source="backend",
            message="Resume request recorded. Bot control state returned to running.",
            feature_name="운영 재개",
            purpose="긴급정지 후 자동 주문 차단을 해제하고 정상 운영 상태로 복귀",
            result_summary="성공 긴급정지 해제, 엔진 상태를 AUTO로 전환",
            mock=True,
        )
    except Exception as exc:
        return _build_logged_error_response(endpoint=endpoint, method="POST", error_message=f"Failed to resume bot control: {str(exc)}")
```

### 1-C. `backend/static/console.html`

#### ① `applyHaltState()` 함수 수정

현재 (약 2461-2466줄):
```javascript
    if (haltBtn) {
      haltBtn.textContent = "중단됨";
      haltBtn.disabled = true;
      haltBtn.style.opacity = "0.75";
      haltBtn.style.cursor = "not-allowed";
    }
```

아래로 변경:
```javascript
    if (haltBtn) {
      haltBtn.textContent = "운영재개";
      haltBtn.classList.remove("danger");
      haltBtn.classList.add("warn");
      haltBtn.disabled = false;
      haltBtn.style.opacity = "1";
      haltBtn.style.cursor = "pointer";
    }
```

#### ② `applyResumeState()` 함수 추가

`applyHaltState()` 함수 바로 뒤에 추가:

```javascript
  function applyResumeState(payload) {
    isHalted = false;
    if (engineText) {
      engineText.textContent = "Auto Engine RUNNING";
    }
    setDotStatus(engineDot, "ok");
    if (modeMetric) {
      modeMetric.textContent = payload && payload.mode ? payload.mode : "AUTO";
      modeMetric.classList.remove("bad");
      modeMetric.classList.add("good");
    }
    if (modeDetail) {
      modeDetail.textContent = "운영 재개됨";
    }
    setStatusChip(riskStatus, "ok", "정상");
    if (riskDetail) {
      riskDetail.textContent = "신규 주문 허용";
    }
    if (haltBtn) {
      haltBtn.textContent = "긴급정지";
      haltBtn.classList.remove("warn");
      haltBtn.classList.add("danger");
    }
  }
```

#### ③ `emergencyResume()` 함수 추가

`emergencyHalt()` 함수 바로 뒤에 추가:

```javascript
  async function emergencyResume() {
    var result = await fetchJson("/api/v1/bot/control/resume", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      }
    });
    applyResumeState(result.payload);
    await loadConsoleData();
  }
```

#### ④ `haltBtn` 이벤트 리스너 수정

현재 (약 2662-2678줄):
```javascript
    if (haltBtn) {
      haltBtn.addEventListener("click", async function () {
        if (isHalted) {
          return;
        }

        if (!confirm("긴급정지를 실행할까요? 신규 자동 주문이 즉시 차단됩니다.")) {
          return;
        }

        try {
          await emergencyHalt();
        } catch (error) {
          alert("긴급정지 호출에 실패했습니다: " + error.message);
        }
      });
    }
```

아래로 변경:
```javascript
    if (haltBtn) {
      haltBtn.addEventListener("click", async function () {
        if (isHalted) {
          if (!confirm("긴급정지를 해제하고 운영을 재개할까요?")) {
            return;
          }
          try {
            await emergencyResume();
          } catch (error) {
            alert("운영재개 호출에 실패했습니다: " + error.message);
          }
          return;
        }

        if (!confirm("긴급정지를 실행할까요? 신규 자동 주문이 즉시 차단됩니다.")) {
          return;
        }

        try {
          await emergencyHalt();
        } catch (error) {
          alert("긴급정지 호출에 실패했습니다: " + error.message);
        }
      });
    }
```

---

## Task 2 — `/api/v1/bot/data-health` 실 데이터 개선

### 2-A. `backend/services/console_state.py`

`get_data_health()` 함수를 수정해서 KIS 토큰 실제 상태를 반환한다.

현재 `get_data_health()` 함수를 찾아서 아래로 교체한다:

```python
def get_data_health() -> dict[str, Any]:
    """Return backend data-health with real KIS token status."""
    logger.info("START: console_state.get_data_health")

    # KIS 토큰 실제 유효성 확인
    try:
        from .kis.common.client import _kis_client  # noqa: PLC0415
        kis_token_ok = _kis_client._token_is_valid() if _kis_client is not None else False
        kis_status = "ok" if kis_token_ok else "warn"
        kis_detail = "토큰 유효" if kis_token_ok else "토큰 없음 또는 만료"
    except Exception:
        kis_status = "warn"
        kis_detail = "상태 확인 불가"

    # SQLite DB 파일 존재 여부 확인
    try:
        import os
        from ..config import settings
        db_path = settings.APP_DB_PATH
        db_ok = os.path.exists(db_path) and os.path.getsize(db_path) > 0
        db_status = "ok" if db_ok else "warn"
        db_detail = f"{db_path} 정상" if db_ok else "DB 파일 없음"
    except Exception:
        db_status = "warn"
        db_detail = "DB 상태 확인 불가"

    payload = {
        "emergency_halt": _CONSOLE_STATE["emergency_halt"],
        "updated_at": _utc_now_iso(),
        "metrics": {
            "kis_rest": {"status": kis_status, "detail": kis_detail},
            "kis_ws": {"status": "info", "detail": "KIS WebSocket 미구현 (향후 S-step 예정)"},
            "llm_router": {"status": "ok", "detail": "LLM Router 활성화 (/api/v1/market-tone/providers 참조)"},
            "db": {"status": db_status, "detail": db_detail},
        },
    }
    logger.info("SUCCESS: console_state.get_data_health kis=%s db=%s", kis_status, db_status)
    return payload
```

### 2-B. `backend/static/console.html`

`loadDataHealth()` 함수에서 `dh-kisWs` 카드를 업데이트하는 부분을 수정한다.

현재 `loadDataHealth()` 함수를 찾아서 `dh-kisWs` 관련 처리를 아래와 같이 수정:

`loadDataHealth()` 함수 안에서 `/api/v1/bot/data-health` 응답을 처리하는 부분에서
`metrics` 필드가 있으면 각 카드에 적용한다.

`loadDataHealth()` 함수 전체를 찾아서 다음으로 교체한다:

```javascript
  async function loadDataHealth() {
    try {
      var r = await fetchJson("/api/v1/bot/data-health");
      var m = (r.payload && r.payload.metrics) ? r.payload.metrics : {};

      function applyMetricCard(idVal, idDetail, key) {
        var s = m[key] || {};
        var el = document.getElementById(idVal);
        var eld = document.getElementById(idDetail);
        if (el) el.textContent = s.status === "ok" ? "정상" : s.status === "warn" ? "주의" : "미구현";
        if (eld) eld.textContent = s.detail || "-";
      }

      applyMetricCard("dh-kisRest", "dh-kisRestDetail", "kis_rest");
      applyMetricCard("dh-kisWs", "dh-kisWsDetail", "kis_ws");
      applyMetricCard("dh-llm", "dh-llmDetail", "llm_router");
      applyMetricCard("dh-db", "dh-dbDetail", "db");
    } catch(e) {
      console.warn("loadDataHealth error", e);
    }

    // LLM Provider 테이블
    try {
      var r2 = await fetchJson("/api/v1/market-tone/providers");
      var providers = (r2.payload && r2.payload.providers) ? r2.payload.providers : [];
      var tbody = document.getElementById("llmProvidersTableBody");
      if (tbody) {
        if (providers.length === 0) {
          tbody.innerHTML = "<tr><td colspan='4' class='muted'>Provider 없음</td></tr>";
        } else {
          tbody.innerHTML = providers.map(function(p) {
            var statusCls = p.enabled ? "ok" : "warn";
            var statusTxt = p.enabled ? "활성" : "비활성";
            return "<tr>"
              + "<td>" + (p.name || "-") + "</td>"
              + "<td>" + (p.role || "-") + "</td>"
              + "<td>" + (p.model || "-") + "</td>"
              + "<td><span class='status " + statusCls + "'>" + statusTxt + "</span></td>"
              + "</tr>";
          }).join("");
        }
      }
    } catch(e) {
      console.warn("loadDataHealth providers error", e);
    }
  }
```

`loadDataHealth()` 함수 안에서 각 metric 카드에 detail id가 있는지 확인한다.
현재 console.html의 Data & API 화면에서 `dh-kisRest`, `dh-kisWs`, `dh-llm`, `dh-db` 카드의 muted 텍스트 id가 없으면
각각 `dh-kisRestDetail`, `dh-kisWsDetail`, `dh-llmDetail`, `dh-dbDetail` id를 추가한다.

예: 현재 `<div class="muted" id="dh-kisWsDetail">확인중</div>` 형태가 있으면 그대로, 없으면 각 카드 `.muted` div에 해당 id 추가.

---

## KIS 클라이언트 singleton 접근 방법 확인

`backend/services/kis/common/client.py`를 먼저 읽어서 singleton 변수명을 확인한다.
파일에 `_kis_client` 또는 다른 이름으로 모듈 레벨 singleton이 있는지 확인 후,
`get_data_health()`의 import 경로와 변수명을 맞게 수정한다.

만약 singleton 접근이 어려우면 (예: `_kis_client`가 없는 경우),
`kis_rest` metric을 단순히 `{"status": "info", "detail": "KIS 토큰 상태 확인 불가 — KIS System Test S1으로 확인"}` 로 반환한다.

---

## 완료 기준

```bash
python -m py_compile backend/services/console_state.py && echo "console_state OK"
python -m py_compile backend/api/routes/bot.py && echo "bot OK"
python3 -c "
import re
content = open('backend/static/console.html').read()
checks = [
    ('control/resume endpoint in HTML', 'control/resume'),
    ('emergencyResume function', 'emergencyResume'),
    ('applyResumeState function', 'applyResumeState'),
    ('운영재개 confirm text', '운영을 재개할까요'),
    ('loadDataHealth with metrics', 'applyMetricCard'),
]
for name, pattern in checks:
    found = pattern in content
    print(f'{name}: {\"OK\" if found else \"MISSING\"}')
"
```

OUTBOX 결과는 `docs/agent-comm/OUTBOX_EXECUTOR_halt_resume_and_health.md` 에 작성하라.
