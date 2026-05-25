CREATE TABLE IF NOT EXISTS replacement_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    slot TEXT NOT NULL,
    current_symbol TEXT NOT NULL,
    current_score REAL NOT NULL,
    current_pnl_pct REAL,
    new_symbol TEXT NOT NULL,
    new_score REAL NOT NULL,
    score_gap REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_replacement_signals_date ON replacement_signals(trade_date);
