"""Tests for the spot grid simulator."""

from compounding_strategy.backtest import metrics as M
from compounding_strategy.backtest.grid_simulator import (
    GridConfig,
    build_levels,
    simulate_grid,
)


def test_levels_span_range():
    cfg = GridConfig(lower=90, upper=110, num_grids=11, capital=1000)
    levels = build_levels(cfg)
    assert levels[0] == 90
    assert levels[-1] == 110
    assert len(levels) == 11


def test_grid_profits_in_ranging_market(ranging_market):
    cfg = GridConfig(lower=92, upper=108, num_grids=17, capital=1000, fee_rate=0.001)
    result = simulate_grid(ranging_market, cfg)
    assert result.round_trips > 0
    assert result.final_equity > cfg.capital


def test_grid_holds_bag_in_downtrend(downtrend_market):
    cfg = GridConfig(lower=150, upper=200, num_grids=21, capital=1000, fee_rate=0.001)
    result = simulate_grid(downtrend_market, cfg)
    assert result.final_inventory_value > 0
    assert result.final_equity < cfg.capital


def test_fees_reduce_equity(ranging_market):
    no_fee = simulate_grid(
        ranging_market, GridConfig(92, 108, 17, 1000, fee_rate=0.0, slippage=0.0)
    )
    with_fee = simulate_grid(
        ranging_market, GridConfig(92, 108, 17, 1000, fee_rate=0.005, slippage=0.0)
    )
    assert with_fee.final_equity < no_fee.final_equity


def test_win_rate_in_range():
    cfg = GridConfig(92, 108, 17, 1000)
    result = simulate_grid(_flat_then_up(), cfg)
    assert 0.0 <= result.win_rate <= 1.0


def test_max_drawdown_non_positive(ranging_market):
    result = simulate_grid(ranging_market, GridConfig(92, 108, 17, 1000))
    assert M.max_drawdown_pct(result.equity_curve) <= 0


def _flat_then_up():
    import numpy as np
    import pandas as pd

    close = np.concatenate([np.full(200, 100.0), np.linspace(100, 108, 200)])
    idx = pd.date_range("2025-01-01", periods=len(close), freq="h", tz="UTC")
    s = pd.Series(close, index=idx)
    return pd.DataFrame({"open": s, "high": s * 1.001, "low": s * 0.999, "close": s})
