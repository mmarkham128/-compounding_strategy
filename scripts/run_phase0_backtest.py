"""Phase 0 entry point.

Runs the spot grid plus regime backtest across the configured asset set and
prints a comparison matrix, then saves it to results and to SQLite.

Usage:
    python scripts/run_phase0_backtest.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compounding_strategy.config import load_config  # noqa: E402
from compounding_strategy.backtest.runner import run_comparison  # noqa: E402
from compounding_strategy.persistence.db import init_db, record_backtest  # noqa: E402


def main() -> None:
    cfg = load_config()
    symbols = cfg["assets"]["symbols"]

    table = run_comparison(
        symbols,
        timeframe=cfg["backtest"]["timeframe"],
        since=cfg["backtest"]["since"],
        num_grids=cfg["grid"]["num_grids"],
        capital=cfg["backtest"]["capital"],
        fee_rate=cfg["fees"]["spot_rate"],
    )

    print("\nPhase 0 comparison matrix\n")
    print(table.to_string())

    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    out_csv = results_dir / "phase0_comparison.csv"
    table.to_csv(out_csv)

    db_path = str(ROOT / "compounding_strategy.db")
    init_db(db_path)
    for symbol, row in table.iterrows():
        record_backtest(
            db_path,
            {
                "symbol": symbol,
                "timeframe": cfg["backtest"]["timeframe"],
                "return_pct": float(row["return_pct"]),
                "max_drawdown_pct": float(row["max_drawdown_pct"]),
                "sharpe": float(row["sharpe"]),
                "round_trips": int(row["round_trips"]),
                "win_rate_pct": float(row["win_rate_pct"]),
                "params": f"grids={cfg['grid']['num_grids']},fee={cfg['fees']['spot_rate']}",
            },
        )

    print(f"\nSaved comparison to {out_csv}")
    print(f"Recorded runs in {db_path}")


if __name__ == "__main__":
    main()
