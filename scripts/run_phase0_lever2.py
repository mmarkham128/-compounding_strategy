"""Phase 0 lever 2: range breakout invalidation.

Replaces the 20% equity drawdown circuit breaker with range breakout
invalidation as the exit primitive. The grid holds inventory through
equity drawdowns and exits only when price closes decisively below the
grid floor, defined as more than invalidation_pct_below_lower percent
beneath the lower bound derived from the lookback window.

Threshold choice: 3% below lower bound. The lower bound is the 10th
percentile of the lookback close prices. A 3% close below that level
represents a confirmed breakdown past historical support, not an
intraday noise wick (we use close, not low). It is tight enough to
limit losses on a true trend break while loose enough to avoid false
triggers from routine volatility within the range.

Regime gating is OFF for this run. Track A showed gating removes
round-trip income proportionally more than it reduces inventory risk,
so it is excluded here to isolate the breaker swap as a single lever.

Usage:
    python scripts/run_phase0_lever2.py
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
    invalidation_pct = cfg["risk"]["invalidation_pct_below_lower"]

    print("Phase 0 lever 2: range breakout invalidation (regime gating OFF)")
    print(f"Invalidation threshold: {invalidation_pct}% below lower bound (close price)")
    print("Circuit breaker: DISABLED")
    print("Regime gating: OFF\n")

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
        circuit_breaker_pct=None,
        invalidation_pct=invalidation_pct,
        use_gating=False,
    )

    print("\nPhase 0 lever 2 OOS comparison matrix\n")
    print(table.to_string())

    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    out_csv = results_dir / "phase0_lever2.csv"
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
                    f"invalidation={invalidation_pct}pct_below_lower,"
                    f"gating=off"
                ),
            },
        )

    print(f"\nSaved to {out_csv}")
    print(f"Recorded in {db_path}")
    print("\nColumn guide:")
    print("  hold_return_pct    OOS return on chained equity (gating off = no flip variant)")
    print("  avg_realized_pct   per window average realized PnL as pct of window capital")
    print("  avg_unrealized_pct per window average unrealized PnL as pct of window capital")
    print("  halt_count         OOS windows where range breakout invalidation fired")
    print("\nCompare hold_return_pct against phase0_hardened.csv for the same 10 assets.")
    print("If invalidation is better: the circuit breaker was the dominant loss driver.")
    print("If invalidation is similar or worse: the grid thesis itself is broken.")


if __name__ == "__main__":
    main()
