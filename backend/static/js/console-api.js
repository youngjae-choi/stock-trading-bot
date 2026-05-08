  async function fetchJson(path, options) {
    var response = await fetch(API_BASE + path, options || {});
    if (response.status === 401) {
      showLogin("로그인이 필요합니다.");
      throw new Error(path + " 인증 필요");
    }
    if (!response.ok) {
      throw new Error(path + " 요청 실패: " + response.status);
    }

    var payload = await response.json();
    if (payload && payload.ok === false) {
      throw new Error(path + " 응답 오류: " + (payload.error || "unknown"));
    }
    return payload;
  }
