"""Spot grid backtest simulator.

Models a spot grid bot over OHLC candles. The fill model is deterministic so
results are reproducible. It captures the two behaviors that decide whether a
grid is worth running:

1. Realized profit from buy low sell high cycles inside the range.
2. Unrealized exposure (the bag you hold) when price exits below the range.

Simplifications, flagged for refinement in later phases:
* Within one candle, a buy at a level and a sell at the level above can both
  fill. We assume the dip came before the rise. Smaller timeframes shrink this
  error, which is why Phase 0 runs on hourly candles.
* Every fill pays the configured fee plus a flat slippage fraction. Real grids
  rest as maker limit orders and often pay less, so this is a conservative
  cost assumption rather than an optimistic one.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class GridConfig:
    lower: float
    upper: float
    num_grids: int
    capital: float
    fee_rate: float = 0.001  # 0.10 percent spot, charged per side
    slippage: float = 0.0005  # 0.05 percent per fill
    geometric: bool = False  # arithmetic spacing by default


@dataclass
class GridResult:
    equity_curve: pd.Series
    realized_fills: int
    round_trips: int
    winning_round_trips: int
    final_cash: float
    final_inventory_value: float
    fees_paid: float
    config: GridConfig

    @property
    def final_equity(self) -> float:
        return self.final_cash + self.final_inventory_value

    @property
    def total_return_pct(self) -> float:
        return (self.final_equity / self.config.capital - 1.0) * 100.0

    @property
    def win_rate(self) -> float:
        if self.round_trips == 0:
            return 0.0
        return self.winning_round_trips / self.round_trips


def build_levels(cfg: GridConfig) -> np.ndarray:
    if cfg.geometric:
        return np.geomspace(cfg.lower, cfg.upper, cfg.num_grids)
    return np.linspace(cfg.lower, cfg.upper, cfg.num_grids)


def simulate_grid(candles: pd.DataFrame, cfg: GridConfig) -> GridResult:
    """Run the grid over candles with columns open, high, low, close."""
    required = {"open", "high", "low", "close"}
    if not required.issubset(candles.columns):
        raise ValueError(f"candles must contain columns {required}")

    levels = build_levels(cfg)
    capital_per_grid = cfg.capital / max(cfg.num_grids - 1, 1)

    cash = cfg.capital
    holdings: dict[int, float] = {}  # level index -> qty held, sells at level above
    fees_paid = 0.0
    realized_fills = 0
    round_trips = 0
    winning_round_trips = 0
    equity = []

    for _, candle in candles.iterrows():
        low = candle["low"]
        high = candle["high"]
        close = candle["close"]

        # Buy pass: a resting buy at any level the candle reached down to fills.
        for i in range(len(levels) - 1):  # top level is a sell target only
            level = levels[i]
            if i in holdings:
                continue
            if low <= level and cash >= capital_per_grid:
                qty = capital_per_grid / level
                fee = capital_per_grid * cfg.fee_rate
                slip = capital_per_grid * cfg.slippage
                cash -= capital_per_grid + fee + slip
                fees_paid += fee + slip
                holdings[i] = qty
                realized_fills += 1

        # Sell pass: a held lot sells when the candle reaches the level above it.
        for i in list(holdings.keys()):
            target = levels[i + 1]
            if high >= target:
                qty = holdings.pop(i)
                proceeds = qty * target
                fee = proceeds * cfg.fee_rate
                slip = proceeds * cfg.slippage
                net = proceeds - fee - slip
                cash += net
                fees_paid += fee + slip
                realized_fills += 1
                round_trips += 1
                if net > capital_per_grid:
                    winning_round_trips += 1

        inventory_value = sum(qty * close for qty in holdings.values())
        equity.append(cash + inventory_value)

    equity_curve = pd.Series(equity, index=candles.index, name="equity")
    last_close = candles.iloc[-1]["close"]
    final_inventory_value = sum(qty * last_close for qty in holdings.values())

    return GridResult(
        equity_curve=equity_curve,
        realized_fills=realized_fills,
        round_trips=round_trips,
        winning_round_trips=winning_round_trips,
        final_cash=cash,
        final_inventory_value=final_inventory_value,
        fees_paid=fees_paid,
        config=cfg,
    )
