"""SQLite persistence helpers."""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect(db_path: str = "compounding_strategy.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = "compounding_strategy.db") -> None:
    conn = connect(db_path)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def record_backtest(db_path: str, row: dict) -> None:
    conn = connect(db_path)
    conn.execute(
        """
        INSERT INTO backtest_runs
            (symbol, timeframe, return_pct, max_drawdown_pct, sharpe,
             round_trips, win_rate_pct, params)
        VALUES (:symbol, :timeframe, :return_pct, :max_drawdown_pct, :sharpe,
                :round_trips, :win_rate_pct, :params)
        """,
        row,
    )
    conn.commit()
    conn.close()
