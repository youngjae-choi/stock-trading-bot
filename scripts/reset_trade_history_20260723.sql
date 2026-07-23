-- 거래이력 리셋 (2026-07-23) — 새 KIS 모의계좌(50198548) 전환에 따른 백지화
-- 범위: 거래이력/실행/P&L/플랜/신호/시장스냅샷/알림/감사 삭제
-- 보존: users·설정·전략설정 + 학습/보정/성과통계 + 지식테이블
PRAGMA foreign_keys = OFF;
BEGIN;

-- 체결/주문/사전점검
DELETE FROM fills;
DELETE FROM orders;
DELETE FROM trading_orders;
DELETE FROM order_preflight_checks;

-- 신호/기술지표
DELETE FROM trading_signals;
DELETE FROM signals;
DELETE FROM signal_technical_indicators;

-- 일별 P&L/요약/복기/baseline
DELETE FROM daily_trade_summary;
DELETE FROM daily_review_reports;
DELETE FROM daily_capital_baseline;

-- 플랜/컨텍스트
DELETE FROM daily_trading_plans;
DELETE FROM daily_plan_run_history;
DELETE FROM daily_context_snapshot;
DELETE FROM morning_context;
DELETE FROM evening_briefing;

-- 포지션/원장/스톱상태/정합
DELETE FROM positions;
DELETE FROM position_cost_basis;
DELETE FROM position_stop_states;
DELETE FROM position_reconciliations;
DELETE FROM trade_entry_tags;

-- 섀도우 트레이드
DELETE FROM shadow_trades;
DELETE FROM shadow_trade_events;

-- 시장 데이터/스냅샷/스크리닝
DELETE FROM intraday_bars;
DELETE FROM intraday_plan_events;
DELETE FROM hybrid_screening_results;
DELETE FROM universe_filter_results;
DELETE FROM market_tone_results;
DELETE FROM market_snapshots;
DELETE FROM overnight_market_snapshots;
DELETE FROM index_board_briefing_cache;

-- 레짐 적용이력(정의/피드백은 보존)
DELETE FROM regime_set_applications;
DELETE FROM sector_rotation_log;

-- 감사/파이프라인/알림
DELETE FROM pipeline_run_audit;
DELETE FROM audit_events;
DELETE FROM system_alerts;
DELETE FROM alert_summary_daily;

-- 교체신호/미진입사유/데이터품질
DELETE FROM replacement_signals;
DELETE FROM candidate_no_entry_reasons;
DELETE FROM no_trade_daily_reasons;
DELETE FROM data_quality_events;
DELETE FROM data_quality_snapshots;

-- 일별 생성 RulePack 이력(base_rulepacks/risk_profile_packs/regime_sets는 보존)
DELETE FROM rulepacks;

-- 승인 큐/로그(지식 승인로그는 보존)
DELETE FROM human_approval_queue;
DELETE FROM approval_decision_logs;

-- 배당 수령이력(계좌 P&L) — 배당 설정(dividend_accounts/dividend_stocks)은 보존
DELETE FROM dividends;
DELETE FROM dividend_stats_cache;

-- 오늘(7/23) baseline 시딩: 새 계좌 원금 1억
INSERT OR REPLACE INTO daily_capital_baseline (trade_date, deposit_krw, total_eval_krw, captured_at)
VALUES ('2026-07-23', 100000000.0, 100000000.0, '2026-07-23T10:40:00+09:00');

COMMIT;
PRAGMA foreign_keys = ON;
