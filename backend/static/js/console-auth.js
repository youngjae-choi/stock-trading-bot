  function showLogin(message, options) {
    var opts = options || {};
    document.body.classList.add("auth-required");
    currentUser = null;
    resetMfaPanel();
    if (loginStatus) {
      loginStatus.textContent = message || "로그인이 필요합니다.";
      loginStatus.classList.toggle("error", Boolean(message));
    }
    if (loginPassword && opts.clearPassword) {
      loginPassword.value = "";
    }
    if (loginPassword && opts.focusPassword) {
      loginPassword.focus();
    }
  }

  function resetMfaPanel() {
    mfaState = null;
    if (mfaPanel) mfaPanel.style.display = "none";
    if (mfaMethodField) mfaMethodField.style.display = "none";
    if (mfaStartBtn) mfaStartBtn.style.display = "none";
    if (mfaSetupBox) {
      mfaSetupBox.style.display = "none";
      mfaSetupBox.innerHTML = "";
    }
    if (mfaCodeField) mfaCodeField.style.display = "none";
    if (mfaVerifyBtn) mfaVerifyBtn.style.display = "none";
    if (mfaCode) mfaCode.value = "";
    if (loginSubmitBtn) {
      loginSubmitBtn.style.display = "";
      loginSubmitBtn.textContent = "로그인";
      loginSubmitBtn.disabled = false;
    }
  }

  function showMfaEnrollment(payload) {
    mfaState = { mode: "enroll", challengeId: payload.challenge_id };
    if (loginSubmitBtn) loginSubmitBtn.style.display = "none";
    if (mfaPanel) mfaPanel.style.display = "";
    if (mfaMethodField) mfaMethodField.style.display = "";
    if (mfaStartBtn) {
      mfaStartBtn.style.display = "";
      mfaStartBtn.textContent = "선택한 수단 등록";
      mfaStartBtn.disabled = false;
    }
    if (mfaSetupBox) {
      mfaSetupBox.style.display = "";
      mfaSetupBox.textContent = "원하는 2차 인증 수단을 선택해 등록하세요.";
    }
    if (mfaCodeField) mfaCodeField.style.display = "none";
    if (mfaVerifyBtn) mfaVerifyBtn.style.display = "none";
    if (loginStatus) {
      loginStatus.textContent = "비밀번호 확인 완료. 2차 인증 수단을 등록하세요.";
      loginStatus.classList.remove("error");
    }
  }

  function showMfaLogin(payload) {
    mfaState = { mode: "login", challengeId: payload.challenge_id };
    if (loginSubmitBtn) loginSubmitBtn.style.display = "none";
    if (mfaPanel) mfaPanel.style.display = "";
    if (mfaMethodField) mfaMethodField.style.display = "none";
    if (mfaStartBtn) mfaStartBtn.style.display = "none";
    if (mfaSetupBox) {
      var labels = (payload.methods || []).map(function(m) { return m.label || m.method_type; }).join(", ");
      mfaSetupBox.style.display = "";
      mfaSetupBox.textContent = "비밀번호 확인 완료. 기존에 등록한 인증 앱의 6자리 코드를 입력하세요. 등록된 수단: " + (labels || "인증 앱");
    }
    if (mfaCodeField) mfaCodeField.style.display = "";
    if (mfaVerifyBtn) {
      mfaVerifyBtn.style.display = "";
      mfaVerifyBtn.textContent = "2차 인증 확인";
      mfaVerifyBtn.disabled = false;
    }
    if (loginStatus) {
      loginStatus.textContent = "2차 인증 코드를 입력하세요.";
      loginStatus.classList.remove("error");
    }
    if (mfaCode) mfaCode.focus();
  }

  async function startMfaEnrollment() {
    if (!mfaState || mfaState.mode !== "enroll") return;
    var method = mfaMethodSelect ? mfaMethodSelect.value : "totp";
    if (mfaStartBtn) {
      mfaStartBtn.disabled = true;
      mfaStartBtn.textContent = "등록 준비 중...";
    }
    var data = await fetchJson("/api/v1/auth/mfa/enroll/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge_id: mfaState.challengeId, method_type: method })
    });
    mfaState = { mode: "enroll_verify", method: method, challengeId: data.payload.challenge_id };
    if (mfaStartBtn) mfaStartBtn.style.display = "none";
    if (mfaCodeField) mfaCodeField.style.display = "";
    if (mfaVerifyBtn) {
      mfaVerifyBtn.style.display = "";
      mfaVerifyBtn.textContent = "등록 완료";
    }
    if (method === "totp") {
      if (mfaSetupBox) {
        mfaSetupBox.style.display = "";
        var qrSrc = data.payload.qr_svg_data_uri || "";
        mfaSetupBox.innerHTML = ""
          + "<div style=\"display:flex; gap:12px; align-items:flex-start; flex-wrap:wrap;\">"
          + (qrSrc ? "<img alt=\"2차 인증 QR 코드\" src=\"" + escapeHtml(qrSrc) + "\" style=\"width:160px; height:160px; padding:10px; border:1px solid var(--line); border-radius:6px; background:#fff;\">" : "")
          + "<div style=\"min-width:180px; flex:1;\">"
          + "<div>인증 앱에서 QR 코드를 스캔한 뒤 6자리 코드를 입력하세요.</div>"
          + "<div style=\"margin-top:8px; font-weight:700; word-break:break-all; color:var(--text);\">"
          + escapeHtml(data.payload.secret)
          + "</div>"
          + "<div style=\"margin-top:6px; font-size:11px; word-break:break-all;\">QR 스캔이 안 되면 위 키를 직접 입력하세요.</div>"
          + "</div></div>";
      }
      if (mfaCode) {
        mfaCode.placeholder = "6자리 인증 앱 코드";
        mfaCode.value = "";
        mfaCode.focus();
      }
    } else {
      if (mfaSetupBox) {
        mfaSetupBox.style.display = "";
        mfaSetupBox.innerHTML = "아래 백업 코드를 안전한 곳에 보관하세요. 등록 확인을 위해 코드 하나를 입력하세요.<br><pre style=\"white-space:pre-wrap; margin:8px 0 0;\">"
          + escapeHtml((data.payload.codes || []).join("\n"))
          + "</pre>";
      }
      if (mfaCode) {
        mfaCode.placeholder = "백업 코드 하나 입력";
        mfaCode.value = "";
        mfaCode.focus();
      }
    }
  }

  async function verifyMfaCode() {
    if (!mfaState) return;
    var endpoint = mfaState.mode === "login" ? "/api/v1/auth/mfa/verify" : "/api/v1/auth/mfa/enroll/verify";
    var data = await fetchJson(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge_id: mfaState.challengeId, code: mfaCode ? mfaCode.value : "" })
    });
    if (loginStatus) {
      loginStatus.textContent = mfaState.mode === "login" ? "2차 인증 완료. 콘솔을 여는 중입니다." : "2차 인증 수단 등록 완료. 콘솔을 여는 중입니다.";
      loginStatus.classList.remove("error");
    }
    resetMfaPanel();
    showConsole(data.payload.user);
    await loadConsoleData();
  }

  function showConsole(user) {
    currentUser = user || null;
    document.body.classList.remove("auth-required");
    resetMfaPanel();
    if (loginStatus) {
      loginStatus.textContent = "";
      loginStatus.classList.remove("error");
    }
  }

  async function checkAuth() {
    try {
      var result = await fetchJson("/api/v1/auth/me");
      showConsole(result.payload.user);
      return true;
    } catch (error) {
      showLogin("로그인이 필요합니다.");
      return false;
    }
  }

  async function submitLogin() {
    if (loginStatus) {
      loginStatus.textContent = "로그인 확인 중입니다.";
      loginStatus.classList.remove("error");
    }
    var response = await fetch(API_BASE + "/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: loginUsername ? loginUsername.value : "",
        password: loginPassword ? loginPassword.value : ""
      })
    });
    if (!response.ok) {
      throw new Error("아이디 또는 비밀번호를 확인하세요.");
    }
    var result = await response.json();
    if (result.payload && result.payload.status === "mfa_enrollment_required") {
      showMfaEnrollment(result.payload);
      return;
    }
    if (result.payload && result.payload.status === "mfa_required") {
      showMfaLogin(result.payload);
      return;
    }
    showConsole(result.payload.user);
    await loadConsoleData();
  }

  async function logout() {
    await fetch(API_BASE + "/api/v1/auth/logout", { method: "POST" });
    showLogin("로그아웃되었습니다.", { clearPassword: true, focusPassword: true });
  }

	  async function loadConsoleData() {
    var results = await Promise.allSettled([
      fetchJson("/api/v1/bot/overview"),
      fetchJson("/api/v1/bot/data-health")
    ]);
    var apiLogError = null;

    var overviewResult = results[0];
    var dataHealthResult = results[1];
    var failedEndpoints = [];

    if (overviewResult.status === "fulfilled") {
      renderOverview(overviewResult.value.payload);
    } else {
      failedEndpoints.push("overview");
      renderFallbackOverview("overview API 실패");
      console.error("Overview bootstrap failed:", overviewResult.reason);
    }

    if (dataHealthResult.status === "fulfilled") {
      renderDataHealth(dataHealthResult.value.payload);
    } else {
      failedEndpoints.push("data-health");
      console.error("Data health bootstrap failed:", dataHealthResult.reason);
    }

	    try {
	      await loadApiLogs();
	    } catch (error) {
	      apiLogError = error;
	      console.error("API logs bootstrap failed:", error);
	    }

	    try {
	      await loadTodayOrders();
	    } catch (error) {
	      console.error("Today orders bootstrap failed:", error);
	    }

    if (failedEndpoints.length > 0) {
      var warningMessage = "일부 백엔드 API 연결 실패: " + failedEndpoints.join(", ") + " · 정적 mock 상태를 표시 중입니다.";
      if (apiLogError) {
        warningMessage += " 관리 로그 조회도 실패했습니다.";
      }
      if (consoleFooterNote) {
        consoleFooterNote.textContent = "API 일부 실패 · 실거래 엔진 미구현 · fallback mock 표시중";
      }
      return;
    }

    if (consoleFooterNote && dataHealthResult.value && dataHealthResult.value.payload && dataHealthResult.value.payload.note) {
      consoleFooterNote.textContent = dataHealthResult.value.payload.note;
    }
  }

  async function emergencyHalt() {
    var result = await fetchJson("/api/v1/bot/control/halt", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      }
    });
    applyHaltState(result.payload);
    await loadConsoleData();
  }

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
