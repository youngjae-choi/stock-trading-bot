  /* Console bootstrap uses FastAPI mock endpoints until live trading is implemented. */
  var API_BASE = window.location.origin;
  var screens = document.querySelectorAll(".screen");
  var navButtons = document.querySelectorAll("#nav button");
  var mobileMenu = document.getElementById("mobileMenu");
  var loginForm = document.getElementById("loginForm");
  var loginUsername = document.getElementById("loginUsername");
  var loginPassword = document.getElementById("loginPassword");
  var loginStatus = document.getElementById("loginStatus");
  var loginSubmitBtn = document.getElementById("loginSubmitBtn");
  var mfaPanel = document.getElementById("mfaPanel");
  var mfaMethodField = document.getElementById("mfaMethodField");
  var mfaMethodSelect = document.getElementById("mfaMethodSelect");
  var mfaStartBtn = document.getElementById("mfaStartBtn");
  var mfaSetupBox = document.getElementById("mfaSetupBox");
  var mfaCodeField = document.getElementById("mfaCodeField");
  var mfaCode = document.getElementById("mfaCode");
  var mfaVerifyBtn = document.getElementById("mfaVerifyBtn");
  var themeBtn = document.getElementById("themeBtn");
  var logoutBtn = document.getElementById("logoutBtn");
  var haltBtn = document.getElementById("haltBtn");
  var engineDot = document.getElementById("engineDot");
  var engineText = document.getElementById("engineText");
  var dataBasisPill = document.getElementById("dataBasisPill");
  var dataBasisDate = document.getElementById("dataBasisDate");
  var dataBasisNote = document.getElementById("dataBasisNote");
  var restDot = document.getElementById("restDot");
  var restStatusText = document.getElementById("restStatusText");
  var socketDot = document.getElementById("socketDot");
  var socketStatusText = document.getElementById("socketStatusText");
  var modeMetric = document.getElementById("modeMetric");
  var modeDetail = document.getElementById("modeDetail");
  var pnlMetric = document.getElementById("pnlMetric");
  var pnlDetail = document.getElementById("pnlDetail");
  var positionsMetric = document.getElementById("positionsMetric");
  var positionsDetail = document.getElementById("positionsDetail");
  var phaseText = document.getElementById("phaseText");
  var nextJobMetric = document.getElementById("nextJobMetric");
  var nextJobText = document.getElementById("nextJobText");
  var lastUpdate = document.getElementById("lastUpdate");
  var todayOpsFeed = document.getElementById("today-ops-feed");
  var funnelProgress = document.getElementById("funnelProgress");
  var kisTokenStatus = document.getElementById("kisTokenStatus");
  var kisTokenDetail = document.getElementById("kisTokenDetail");
  var rulepackStatus = document.getElementById("rulepackStatus");
  var rulepackDetail = document.getElementById("rulepackDetail");
  var websocketStatus = document.getElementById("websocketStatus");
  var websocketDetail = document.getElementById("websocketDetail");
  var riskStatus = document.getElementById("riskStatus");
  var riskDetail = document.getElementById("riskDetail");
  var consoleFooterNote = document.getElementById("consoleFooterNote");
  var apiLogsCount = document.getElementById("apiLogsCount");
  var apiLogsMetric = document.getElementById("apiLogsMetric");
  var apiLogsLastUpdate = document.getElementById("apiLogsLastUpdate");
  var apiLogsMode = document.getElementById("apiLogsMode");
  var apiLogsNote = document.getElementById("apiLogsNote");
  var apiLogsTableBody = document.getElementById("apiLogsTableBody");

  var isHalted = false;
  var currentUser = null;
  var mfaState = null;
  var overviewData = null;
  var OPS_STEPS = [
    { id: 's1', label: 'S1 토큰 갱신', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · KIS token-refresh' },
    { id: 's2', label: 'S2 시장톤 분석', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · LLM -> market_tone_results' },
    { id: 's3', label: 'S3 유니버스 필터', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · KIS -> universe_filter_results' },
    { id: 's4', label: 'S4 하이브리드 스크리닝', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · LLM 정성 평가 -> hybrid_screening_results' },
    { id: 's5', label: 'S5 Daily Plan 생성', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · Scheduler -> daily_trading_plans' },
    { id: 's5v', label: 'S5-V Daily Plan 검증', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · Schema/Risk Guard 검증' },
    { id: 's5a', label: 'S5-A Daily Plan 활성화 확인', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · active plan 상태 확인' },
    { id: 's6', label: 'S6 Decision Engine 활성화', defaultTime: '09:45', settingKey: 'schedule_s6_time', detail: 'WS 연결 + RulePack + Risk Profile + Daily Plan 조건 감시' },
    { id: 's7', label: 'S7 주문 실행', defaultTime: '실시간', settingKey: 'schedule_s7_time', detail: '오늘 발행된 주문 내역 조회' },
    { id: 's8', label: 'S8 Position Manager', defaultTime: '실시간', settingKey: 'schedule_s8_time', detail: 'WS tick -> 손절/트레일링/강제청산 감시' },
    { id: 's9', label: 'S9 당일 청산', defaultTime: '15:20', settingKey: 'schedule_postprocess_time', detail: '후처리 프로세스 하위 단계 · 전량 시장가 청산' },
    { id: 's10', label: 'S10 Review & Audit', defaultTime: '15:20', settingKey: 'schedule_postprocess_time', detail: '후처리 프로세스 하위 단계 · review_audit -> daily_review_reports' },
    { id: 's11', label: 'S11 Learning Memory Builder', defaultTime: '22:00', settingKey: 'schedule_s11_time', detail: 'Trade Review -> Learning Memory' },
  ];
  var SCHEDULED_OPERATIONS = [
    { id: 'trade-prep', label: '거래준비 프로세스 시작 (S1~S5-A 순차 실행)', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time' },
    { id: 's6', label: 'S6 Decision Engine 시간', defaultTime: '09:45', settingKey: 'schedule_s6_time' },
    { id: 'postprocess', label: '후처리 프로세스 시작 (S9~S10 순차 실행)', defaultTime: '15:20', settingKey: 'schedule_postprocess_time' },
    { id: 's11', label: 'S11 Learning Memory 시간', defaultTime: '22:00', settingKey: 'schedule_s11_time' },
  ];
  var timeline = SCHEDULED_OPERATIONS
    .filter(function(step) { return /^\d{2}:\d{2}$/.test(step.defaultTime); })
    .map(function(step) { return { time: step.defaultTime, name: step.label }; });
  var sampleLogs = [
    ["07:45", "KIS 토큰 갱신 완료. Access token 유효성 확인."],
    ["08:00", "AI 시장 톤 분석 완료. 코스닥 상대 강세, 리스크 중간."],
    ["08:15", "Layer 1 Universe 생성 완료. 2,500개 중 200개 통과."]
  ];
