# OUTBOX_EXECUTOR_learning_risk_hardening

## Changed Files

- `backend/services/engine/order_preflight.py`
- `backend/services/engine/decision_engine.py`
- `backend/services/engine/confidence_calibration.py`
- `backend/services/engine/learning_memory.py`
- `backend/services/engine/rule_resolver.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_learning_risk_hardening.md`

## Implementation Summary

- Added a daily-loss preflight guard for new BUY orders.
  - Reads the resolved final rule first, including `daily_loss_limit`, `daily_loss_limit_rate`, and `daily_loss_limit_pct` aliases, then falls back to `risk.daily_loss_limit_percent`.
  - Normalizes rate inputs such as `-0.02` and `-0.03` to `-2.0` and `-3.0` percent while preserving percent inputs such as `-2`; explicit positive `daily_loss_limit_pct` schema values are treated as loss magnitude.
  - Prefers the latest `account_snapshots.day_pnl/equity` account-level percent for the trade date.
  - No longer treats `daily_trade_summary.realized_pnl_pct` as account loss percent because it is an average trade return metric.
  - Uses `daily_trade_summary.realized_pnl` or `trading_signals.realized_pnl` only when account equity is known; otherwise it fails open and logs WARN evidence.
- Extended S6 Layer3 rule evaluation without inventing indicators.
  - Evaluates RSI, VWAP position, MA5/MA20, and spread only when common candidate/tick keys are present.
  - For `spread_max_pct`, prefers explicit percent/rate keys: `spread_pct`, `spread_percent`, `bid_ask_spread_pct`, `spread_rate`.
  - Raw `spread` is treated as KRW and converted to percent only when current price is available; if price is missing, the spread condition is recorded as unavailable.
  - Keeps `unavailable_conditions` behavior when raw data is absent.
  - Records evaluated indicator values and source keys in `observed_values`.
- Added recommendation-only confidence learning.
  - Builds S11 `learning_memories` rows from confidence calibration bins when sampled bins materially underperform or overperform.
  - Recommendations target `engine.min_ai_confidence` or `engine.min_confidence_floor`.
  - Does not update Settings and does not alter live signals directly.
- Preserved SQLite schema compatibility. No network packages were added.
- Fixed the remaining Oracle blocker in Rule Resolver.
  - Active RulePack `machine_rules.risk_limits` is now flattened into the active RulePack layer used by `resolve_symbol_rule()`.
  - Existing `layer3_entry` / legacy `entry_rules` behavior is preserved: `layer3_entry` is merged first and `entry_rules` overrides it for duplicate entry keys.
  - Within the active RulePack layer, `risk_limits` is merged after entry rules so risk-limit keys such as `daily_loss_limit_rate` and `daily_loss_limit_pct` reach `final_rule`.
  - Resolver-level precedence remains: `base_rulepack -> active RulePack machine_rules -> profile -> symbol_override -> Global Risk Guard`.
  - Existing Global Risk Guard hard overrides still run last, so `max_positions`, `max_position_rate`, force-exit time, entry cutoff time, take-profit disablement, and stop-price monotonicity are not weakened by RulePack risk limits.

## Tests Run

- `python -m py_compile backend/services/engine/order_preflight.py backend/services/engine/decision_engine.py`
- `python -m py_compile backend/services/engine/rule_resolver.py backend/services/engine/order_preflight.py backend/services/engine/decision_engine.py backend/services/engine/confidence_calibration.py backend/services/engine/learning_memory.py`
- `.venv/bin/python -m py_compile backend/services/engine/rule_resolver.py backend/services/engine/order_preflight.py backend/services/engine/decision_engine.py backend/services/engine/confidence_calibration.py backend/services/engine/learning_memory.py`
- `APP_DB_PATH=/tmp/rulepack_risk_smoke.sqlite3 .venv/bin/python - <<'PY' ...`
- `. .venv/bin/activate && APP_DB_PATH=/tmp/preflight_smoke.sqlite3 python - <<'PY' ...`
- Targeted smoke with temp SQLite DB:
  - Active RulePack `machine_rules.risk_limits.daily_loss_limit_rate=-0.03` resolves into `final_rule["daily_loss_limit_rate"]`.
  - `order_preflight._daily_loss_limit_percent(final_rule)` normalizes that rate to `-3.0`.
  - Legacy precedence is preserved: duplicate `min_ai_confidence` from `entry_rules` overrides `layer3_entry`.
  - Global Risk Guard remains last: RulePack `max_positions=7` is forced back to global `max_positions=5`, and base `max_position_rate=0.20` is capped to global `0.10`.
  - `daily_loss_limit=-0.02`, `daily_loss_limit_rate=-0.03`, `daily_loss_limit_pct=-2`, and `daily_loss_limit_pct=2` normalize to `-2.0`, `-3.0`, `-2`, and `-2`.
  - Latest `account_snapshots.day_pnl/equity` is preferred and `daily_trade_summary.realized_pnl_pct=-99` is ignored as account-loss evidence.
  - `daily_trade_summary.realized_pnl_pct` without account equity fails open with `observed_percent=None`.
  - KRW `trading_signals.realized_pnl` without account equity fails open with WARN evidence.
  - Explicit `spread_rate=0.003` evaluates as `0.3%`.
  - Raw KRW `spread=100` with `price=10000` evaluates as `1.0%`.
  - Raw KRW `spread=100` without price is marked unavailable and does not compare KRW directly to percent.

## Remaining Risks

- Intraday realized PnL depends on available local data. If no percent source or account equity exists, the guard logs and does not block by design.
- `daily_trade_summary.realized_pnl_pct` remains available for trade-quality analytics, but it is intentionally excluded from account-level daily loss blocking.
- Layer3 gating only activates for indicators actually present in candidate/tick payloads; upstream collectors still need to provide reliable raw fields for broader coverage.
