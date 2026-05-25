-- Compounding Strategy persistence schema.

CREATE TABLE IF NOT EXISTS bot_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    regime TEXT,
    leverage REAL DEFAULT 1.0,
    allocated REAL,
    status TEXT DEFAULT 'idle',
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    qty REAL NOT NULL,
    fee REAL DEFAULT 0,
    mode TEXT DEFAULT 'backtest',
    ts TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT,
    return_pct REAL,
    max_drawdown_pct REAL,
    sharpe REAL,
    round_trips INTEGER,
    win_rate_pct REAL,
    params TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS equity_curve (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    ts TEXT NOT NULL,
    equity REAL NOT NULL
);
