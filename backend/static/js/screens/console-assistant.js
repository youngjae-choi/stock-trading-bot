/* ── 콘솔 어시스턴트 패널 ──
 * 현재 화면 컨텍스트 + PM 입력을 날짜별 공유 MD에 기록(POST /api/v1/assistant/note)하고,
 * 같은 파일을 폴링(GET)해 대화를 표시한다. CLI의 Claude가 같은 MD를 읽고 답을 append한다.
 * Anthropic API 미사용 = 과금 0.
 */
(function () {
  var POLL_MS = 5000;
  var CTX_CAP = 4000; // 화면 컨텍스트 문자 상한(토큰/용량 가드)
  var _pollTimer = null;
  var _recognizing = false;
  var _recognition = null;

  function _activeScreenId() {
    try { return sessionStorage.getItem('currentScreen') || 'unknown'; } catch (e) { return 'unknown'; }
  }

  /* 활성 화면의 렌더된 텍스트를 compact하게 수집(범용 추출기). */
  function _collectScreenContext() {
    var id = _activeScreenId();
    var sec = document.getElementById('screen-' + id) ||
              document.querySelector('.screen:not([style*="display: none"])') ||
              document.querySelector('.screen');
    // sessionStorage가 비어 'unknown'이면 보이는 화면 요소 id(screen-XXX)에서 유도
    if (id === 'unknown' && sec && sec.id && sec.id.indexOf('screen-') === 0) {
      id = sec.id.slice('screen-'.length);
    }
    var text = '';
    if (sec) {
      text = (sec.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
      if (text.length > CTX_CAP) text = text.slice(0, CTX_CAP) + '\n…(생략)';
    }
    return { screen_id: id, context: text };
  }

  function _setStatus(msg) {
    var el = document.getElementById('assistant-status');
    if (el) el.textContent = msg || '';
  }

  function _render(content) {
    var box = document.getElementById('assistant-log');
    if (!box) return;
    if (!content) { box.textContent = '아직 대화가 없습니다. 화면을 보내고 CLI에서 Claude에게 말을 거세요.'; return; }
    box.textContent = content; // MD 원문 그대로(읽기 충분), 안전상 textContent
    box.scrollTop = box.scrollHeight;
  }

  async function _poll() {
    try {
      var r = await fetch('/api/v1/assistant/note');
      var j = await r.json();
      _render(j && j.payload ? j.payload.content : '');
    } catch (e) { /* 조용히 무시 */ }
  }

  async function sendAssistantNote(noteOverride) {
    var input = document.getElementById('assistant-input');
    var note = (noteOverride != null) ? noteOverride : (input ? input.value : '');
    var snap = _collectScreenContext();
    _setStatus('보내는 중…');
    try {
      var r = await fetch('/api/v1/assistant/note', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: note || '', screen_id: snap.screen_id, screen_context: snap.context }),
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      if (input) input.value = '';
      _setStatus('전송됨 · ' + snap.screen_id + ' 화면 첨부');
      _poll();
    } catch (e) {
      _setStatus('전송 실패: ' + (e.message || e));
    }
  }

  function sendScreenOnly() { sendAssistantNote('(화면 공유)'); }

  function toggleAssistant() {
    var panel = document.getElementById('assistant-panel');
    if (!panel) return;
    var open = panel.style.display !== 'none' && panel.style.display !== '';
    panel.style.display = open ? 'none' : 'flex';
    if (!open) {
      _poll();
      if (!_pollTimer) _pollTimer = setInterval(_poll, POLL_MS);
    } else if (_pollTimer) {
      clearInterval(_pollTimer); _pollTimer = null;
    }
  }

  /* 🎤 Web Speech API STT — 서버 부담 0 */
  function toggleAssistantMic() {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { _setStatus('이 브라우저는 음성 입력 미지원'); return; }
    if (_recognizing && _recognition) { _recognition.stop(); return; }
    _recognition = new SR();
    _recognition.lang = 'ko-KR';
    _recognition.interimResults = true;
    _recognition.onstart = function () { _recognizing = true; _setStatus('🎤 듣는 중…'); };
    _recognition.onend = function () { _recognizing = false; _setStatus(''); };
    _recognition.onerror = function (ev) { _recognizing = false; _setStatus('음성 오류: ' + ev.error); };
    _recognition.onresult = function (ev) {
      var t = '';
      for (var i = ev.resultIndex; i < ev.results.length; i++) t += ev.results[i][0].transcript;
      var input = document.getElementById('assistant-input');
      if (input) input.value = t;
    };
    _recognition.start();
  }

  window.toggleAssistant = toggleAssistant;
  window.toggleAssistantMic = toggleAssistantMic;
  window.sendAssistantNote = sendAssistantNote;
  window.sendScreenOnly = sendScreenOnly;
})();
