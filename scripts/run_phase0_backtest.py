"""Phase 0 entry point.

Runs the hardened walk forward backtest across the configured asset set and
prints the comparison matrix. All parameters come from config/config.yaml.
Grid bounds are set from in sample lookback only. The risk overlay circuit
breaker is active. Win rate counts true round trip profit after all costs.
Return is split into realized grid income and unrealized inventory appreciation.

Usage:
    python scripts/run_phase0_backtest.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compounding_strategy.config import load_config  # noqa: E402
from compounding_strategy.backtest.runner import run_walk_forward_comparison  # noqa: E402
from compounding_strategy.persistence.db import init_db, record_backtest  # noqa: E402


def main() -> None:
    cfg = load_config()
    symbols = cfg["assets"]["symbols"]

    print("Running Phase 0 walk forward backtest (out of sample metrics only)...")
    table = run_walk_forward_comparison(
        symbols,
        timeframe=cfg["backtest"]["timeframe"],
        since=cfg["backtest"]["since"],
        num_grids=cfg["grid"]["num_grids"],
        capital=cfg["backtest"]["capital"],
        fee_rate=cfg["fees"]["spot_rate"],
        slippage=cfg["fees"]["slippage"],
        exchange_id=cfg["backtest"]["exchange"],
        lookback_months=cfg["backtest"]["lookback_months"],
        circuit_breaker_pct=cfg["risk"]["max_strategy_drawdown_pct"],
    )

    print("\nPhase 0 regime gated comparison matrix (out of sample only)\n")
    print(table.to_string())

    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    out_csv = results_dir / "phase0_gated.csv"
    table.to_csv(out_csv)

    db_path = str(ROOT / "compounding_strategy.db")
    init_db(db_path)
    for symbol, row in table.iterrows():
        record_backtest(
            db_path,
            {
                "symbol": symbol,
                "timeframe": cfg["backtest"]["timeframe"],
                "return_pct": float(row["hold_return_pct"]),
                "max_drawdown_pct": float(row["oos_max_dd_pct"]),
                "sharpe": float(row["oos_sharpe"]),
                "round_trips": int(row["round_trips"]),
                "win_rate_pct": float(row["true_win_rate_pct"]),
                "params": (
                    f"grids={cfg['grid']['num_grids']},"
                    f"fee={cfg['fees']['spot_rate']},"
                    f"lookback={cfg['backtest']['lookback_months']}mo,"
                    f"cb={cfg['risk']['max_strategy_drawdown_pct']}pct,"
                    f"gated_hold"
                ),
            },
        )

    print(f"\nSaved to {out_csv}")
    print(f"Recorded in {db_path}")
    print("\nColumn guide:")
    print("  hold_return_pct    OOS return, bag held through trend_down candles")
    print("  flip_return_pct    OOS return, bag closed at close on trend_down flip")
    print("  avg_realized_pct   per window average realized PnL as pct of window capital")
    print("  avg_unrealized_pct per window average unrealized PnL as pct of window capital")
    print("  pct_gated          pct of OOS candles where no new buys were opened")


if __name__ == "__main__":
    main()
