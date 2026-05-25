"""Multi asset walk forward backtest runner.

Grid bounds and any tunable parameters are set from a trailing in sample
lookback window only. The next calendar month is the out of sample test. The
window rolls forward across the full year. Reported metrics are aggregated
across all out of sample months, so no hindsight enters the numbers.

Regime gating: the grid opens no new positions when the classifier labels
a candle as trend_up or trend_down. The sell pass remains active so existing
positions can still close at a profit. Two exit variants are run per asset:

  hold   the bag is held through a trend_down regime; sells happen only if
         price rises back to the target level above a held lot.

  flip   when the regime transitions into trend_down, all open holdings are
         immediately closed at the candle close price, realizing the loss.

Realized and unrealized PnL are reported as per window averages (each window
normalised to its own starting capital), so they are directly comparable
across assets without distortion from summing over different numbers of
breaker events.
"""

import pandas as pd

from ..data.loader import fetch_ohlcv
from ..regime.classifier import classify
from . import metrics as M
from .grid_simulator import GridConfig, simulate_grid

TIMEFRAME_PERIODS = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}


def _bounds_from_lookback(close: pd.Series, low_pct: float = 0.1, high_pct: float = 0.9):
    """Derive grid bounds from in sample price history only."""
    return float(close.quantile(low_pct)), float(close.quantile(high_pct))


def _chain_equity(window_results: list, capital: float) -> pd.Series:
    """Chain per window equity curves into one continuous compounding curve.

    Each window is normalised to its own first equity value then scaled by
    the running equity level, so transitions between windows are smooth and
    the total return reflects compounding across the year.
    """
    chained: list[pd.Series] = []
    scale = capital
    for r in window_results:
        start = float(r.equity_curve.iloc[0])
        normed = r.equity_curve / start * scale
        chained.append(normed)
        scale = float(normed.iloc[-1])
    return pd.concat(chained)


def walk_forward_backtest(
    symbol: str,
    timeframe: str = "1h",
    since: str = "2025-05-25",
    num_grids: int = 20,
    capital: float = 1000.0,
    fee_rate: float = 0.001,
    slippage: float = 0.0005,
    exchange_id: str = "kucoin",
    lookback_months: int = 3,
    circuit_breaker_pct: float | None = None,
    invalidation_pct: float | None = None,
    use_gating: bool = True,
) -> dict:
    df = fetch_ohlcv(symbol, timeframe=timeframe, since=since, exchange_id=exchange_id)

    periods = df.index.tz_convert("UTC").tz_localize(None).to_period("M")
    months = sorted(periods.unique())

    if len(months) <= lookback_months:
        raise ValueError(
            f"{symbol}: only {len(months)} months of data, need more than {lookback_months}"
        )

    oos_months = months[lookback_months:]
    ppy = TIMEFRAME_PERIODS.get(timeframe, 365 * 24)

    hold_results: list = []
    flip_results: list = []
    gated_months = 0
    total_oos_candles = 0
    total_gated_candles = 0

    for oos_month in oos_months:
        oos_df = df[periods == oos_month]
        if len(oos_df) < 10:
            continue

        oos_start_ts = oos_df.index[0]
        lookback_start_ts = oos_start_ts - pd.DateOffset(months=lookback_months)
        lb_df = df[(df.index >= lookback_start_ts) & (df.index < oos_start_ts)]
        if len(lb_df) < 10:
            continue

        lower, upper = _bounds_from_lookback(lb_df["close"])
        if upper <= lower:
            continue

        regime_series = classify(oos_df) if use_gating else None

        cfg = GridConfig(
            lower=lower,
            upper=upper,
            num_grids=num_grids,
            capital=capital,
            fee_rate=fee_rate,
            slippage=slippage,
            circuit_breaker_pct=circuit_breaker_pct,
            invalidation_pct=invalidation_pct,
        )

        r_hold = simulate_grid(oos_df, cfg, regime_series=regime_series, exit_on_trend_down=False)
        r_flip = simulate_grid(oos_df, cfg, regime_series=regime_series, exit_on_trend_down=True)

        hold_results.append(r_hold)
        flip_results.append(r_flip)

        total_oos_candles += len(oos_df)
        total_gated_candles += r_hold.gated_candles
        if r_hold.gated_candles == len(oos_df):
            gated_months += 1

    if not hold_results:
        raise ValueError(f"{symbol}: no valid OOS windows produced")

    hold_curve = _chain_equity(hold_results, capital)
    flip_curve = _chain_equity(flip_results, capital)

    hold_return_pct = (hold_curve.iloc[-1] / capital - 1.0) * 100.0
    flip_return_pct = (flip_curve.iloc[-1] / capital - 1.0) * 100.0
    oos_max_dd = M.max_drawdown_pct(hold_curve)
    oos_sharpe = M.sharpe_ratio(hold_curve, ppy)

    total_round_trips = sum(r.round_trips for r in hold_results)
    total_winning = sum(r.winning_round_trips for r in hold_results)
    total_fees = sum(r.fees_paid for r in hold_results)
    halt_count = sum(1 for r in hold_results if r.breaker_tripped)
    true_win_rate = total_winning / total_round_trips if total_round_trips > 0 else 0.0

    # Per window averages: each window normalised to its own starting capital
    # so the denominator is consistent and values are directly comparable.
    n = len(hold_results)
    avg_realized_pct = sum(r.realized_profit / capital * 100 for r in hold_results) / n
    avg_unrealized_pct = sum(r.unrealized_profit / capital * 100 for r in hold_results) / n

    pct_gated = (total_gated_candles / total_oos_candles * 100) if total_oos_candles else 0.0

    regimes = classify(df)

    return {
        "symbol": symbol,
        "oos_months": n,
        "hold_return_pct": round(hold_return_pct, 2),
        "flip_return_pct": round(flip_return_pct, 2),
        "oos_max_dd_pct": round(oos_max_dd, 2),
        "oos_sharpe": round(oos_sharpe, 2),
        "round_trips": total_round_trips,
        "true_win_rate_pct": round(true_win_rate * 100, 1),
        "fees_paid": round(total_fees, 2),
        "avg_realized_pct": round(avg_realized_pct, 2),
        "avg_unrealized_pct": round(avg_unrealized_pct, 2),
        "halt_count": halt_count,
        "gated_months": gated_months,
        "pct_gated": round(pct_gated, 1),
        "pct_ranging": round((regimes == "ranging").mean() * 100, 1),
        "pct_trend_up": round((regimes == "trend_up").mean() * 100, 1),
        "pct_trend_down": round((regimes == "trend_down").mean() * 100, 1),
    }


def run_walk_forward_comparison(symbols: list[str], **kwargs) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        try:
            rows.append(walk_forward_backtest(symbol, **kwargs))
            print(f"  done: {symbol}")
        except Exception as exc:
            print(f"  skipped {symbol}: {exc}")
    if not rows:
        raise RuntimeError("No symbols produced results")
    return pd.DataFrame(rows).set_index("symbol")
