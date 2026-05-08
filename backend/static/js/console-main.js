  /* Bootstrap the console after all split classic scripts have loaded. */
  async function init() {
    initTheme();
    bindEvents();
    var isAuthenticated = await checkAuth();
    if (!isAuthenticated) {
      return;
    }
    renderTodayFeed();
    updateLastTime();
    loadConsoleData();

    var savedScreen = sessionStorage.getItem('currentScreen');
    if (savedScreen === 'missed-opportunity') {
      savedScreen = 'shadow-trading';
    }
    if (savedScreen && document.getElementById('screen-' + savedScreen)) {
      showScreen(savedScreen);
    }

    setInterval(function () {
      renderTodayFeed();
      updateLastTime();
    }, 1000);
  }

  document.addEventListener("DOMContentLoaded", init);
