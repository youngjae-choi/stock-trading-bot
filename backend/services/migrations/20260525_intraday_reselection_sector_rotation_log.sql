CREATE TABLE IF NOT EXISTS sector_rotation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    slot TEXT NOT NULL,
    top_sectors TEXT NOT NULL,
    bottom_sectors TEXT NOT NULL,
    gap_pct REAL NOT NULL,
    triggered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sector_rotation_log_date ON sector_rotation_log(trade_date);
