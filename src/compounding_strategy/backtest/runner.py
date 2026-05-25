"""Multi asset backtest runner.

Runs the spot grid plus regime classifier across the configured asset set and
returns a comparison matrix. Phase 0 uses a straightforward auto sized grid
(range drawn from price percentiles) so every asset is judged on the same
footing. Parameter optimization per asset comes in a later phase once the raw
comparison shows which markets are worth the effort.
"""

import pandas as pd

from ..data.loader import fetch_ohlcv
from ..regime.classifier import classify
from . import metrics as M
from .grid_simulator import GridConfig, simulate_grid

# Approximate number of candles per year for annualizing metrics.
TIMEFRAME_PERIODS = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}


def auto_grid_range(close: pd.Series, low_pct: float = 0.1, high_pct: float = 0.9):
    """Set the grid band from price percentiles so a few spikes do not stretch it."""
    return float(close.quantile(low_pct)), float(close.quantile(high_pct))


def backtest_asset(
    symbol: str,
    timeframe: str = "1h",
    since: str = "2025-05-25",
    num_grids: int = 20,
    capital: float = 1000.0,
    fee_rate: float = 0.001,
) -> dict:
    df = fetch_ohlcv(symbol, timeframe=timeframe, since=since)
    lower, upper = auto_grid_range(df["close"])
    cfg = GridConfig(
        lower=lower, upper=upper, num_grids=num_grids, capital=capital, fee_rate=fee_rate
    )
    result = simulate_grid(df, cfg)
    regimes = classify(df)
    ppy = TIMEFRAME_PERIODS.get(timeframe, 365)

    return {
        "symbol": symbol,
        "candles": len(df),
        "return_pct": round(result.total_return_pct, 2),
        "max_drawdown_pct": round(M.max_drawdown_pct(result.equity_curve), 2),
        "sharpe": round(M.sharpe_ratio(result.equity_curve, ppy), 2),
        "round_trips": result.round_trips,
        "win_rate_pct": round(result.win_rate * 100, 1),
        "fees_paid": round(result.fees_paid, 2),
        "final_inventory_pct": round(result.final_inventory_value / capital * 100, 1),
        "pct_ranging": round((regimes == "ranging").mean() * 100, 1),
        "pct_trend_up": round((regimes == "trend_up").mean() * 100, 1),
        "pct_trend_down": round((regimes == "trend_down").mean() * 100, 1),
        "pct_chop": round((regimes == "chop").mean() * 100, 1),
    }


def run_comparison(symbols: list[str], **kwargs) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        try:
            rows.append(backtest_asset(symbol, **kwargs))
        except Exception as exc:  # keep going if one symbol fails to load
            print(f"skipped {symbol}: {exc}")
    return pd.DataFrame(rows).set_index("symbol")
