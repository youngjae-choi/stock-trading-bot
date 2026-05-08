  /* Bind authentication, theme, halt, navigation, and delegated action handlers. */
  function bindEvents() {
    if (loginForm) {
      loginForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        try {
          if (mfaState && (mfaState.mode === "login" || mfaState.mode === "enroll_verify")) {
            await verifyMfaCode();
          } else if (mfaState && mfaState.mode === "enroll") {
            await startMfaEnrollment();
          } else {
            await submitLogin();
          }
        } catch (error) {
          if (mfaState) {
            if (mfaStartBtn && mfaState.mode === "enroll") {
              mfaStartBtn.disabled = false;
              mfaStartBtn.textContent = "선택한 수단 등록";
            }
            if (loginStatus) {
              loginStatus.textContent = "2차 인증 처리 실패: " + error.message;
              loginStatus.classList.add("error");
            }
          } else {
            showLogin(error.message);
          }
        }
      });
    }

    if (mfaStartBtn) {
      mfaStartBtn.addEventListener("click", async function () {
        try {
          await startMfaEnrollment();
        } catch (error) {
          if (mfaStartBtn) {
            mfaStartBtn.disabled = false;
            mfaStartBtn.textContent = "선택한 수단 등록";
          }
          if (loginStatus) {
            loginStatus.textContent = "2차 인증 등록 시작 실패: " + error.message;
            loginStatus.classList.add("error");
          }
        }
      });
    }

    if (mfaVerifyBtn) {
      mfaVerifyBtn.addEventListener("click", async function () {
        try {
          await verifyMfaCode();
        } catch (error) {
          if (loginStatus) {
            loginStatus.textContent = "2차 인증 실패: 코드를 확인하세요.";
            loginStatus.classList.add("error");
          }
        }
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener("click", async function () {
        try {
          await logout();
        } catch (error) {
          showLogin("로그아웃 처리 중 오류가 발생했습니다.");
        }
      });
    }

    bindNavigationEvents();
    bindConsoleActionEvents();

    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        if (document.body.classList.contains("light")) {
          setTheme("dark");
        } else {
          setTheme("light");
        }
      });
    }

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
  }

  /* Apply the saved console theme before authenticated data loads. */
  function initTheme() {
    var savedTheme = localStorage.getItem("dantabot_theme");
    if (savedTheme === "light") {
      setTheme("light");
      return;
    }
    setTheme("dark");
  }
