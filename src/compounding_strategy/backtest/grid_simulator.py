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

GATED_REGIMES = {"trend_up", "trend_down"}  # regimes where no new buys are opened


@dataclass
class GridConfig:
    lower: float
    upper: float
    num_grids: int
    capital: float
    fee_rate: float = 0.001
    slippage: float = 0.0005
    geometric: bool = False
    circuit_breaker_pct: float | None = None  # drawdown from peak that halts the grid
    invalidation_pct: float | None = None     # pct below lower bound that invalidates the range thesis


@dataclass
class GridResult:
    equity_curve: pd.Series
    realized_fills: int
    round_trips: int
    winning_round_trips: int
    final_cash: float
    final_inventory_value: float
    fees_paid: float
    realized_profit: float    # net PnL from completed round trips after all costs
    unrealized_profit: float  # mark to market of held inventory minus cost basis
    breaker_tripped: bool
    gated_candles: int        # candles where the buy pass was skipped due to regime
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


def simulate_grid(
    candles: pd.DataFrame,
    cfg: GridConfig,
    regime_series: pd.Series | None = None,
    exit_on_trend_down: bool = False,
) -> GridResult:
    """Run the grid over candles with columns open, high, low, close.

    regime_series, if provided, must share the same index as candles.
    When a candle's regime is trend_up or trend_down, the buy pass is skipped
    so no new grid positions are opened. The sell pass is always active.

    exit_on_trend_down: when the regime transitions INTO trend_down (was not
    trend_down on the previous candle), all open holdings are closed at the
    current candle's close price before the sell pass runs.
    """
    required = {"open", "high", "low", "close"}
    if not required.issubset(candles.columns):
        raise ValueError(f"candles must contain columns {required}")

    levels = build_levels(cfg)
    capital_per_grid = cfg.capital / max(cfg.num_grids - 1, 1)

    cash = cfg.capital
    # holdings: level index -> (qty, all_in_cost_basis)
    # cost_basis includes the spend on coin plus entry fee and slippage.
    holdings: dict[int, tuple[float, float]] = {}
    fees_paid = 0.0
    realized_fills = 0
    round_trips = 0
    winning_round_trips = 0
    cumulative_realized_pnl = 0.0
    equity: list[float] = []
    peak_equity = cfg.capital
    halted = False
    gated_candles = 0
    prev_regime: str | None = None

    for ts, candle in candles.iterrows():
        if halted:
            equity.append(cash)
            continue

        regime: str = regime_series.loc[ts] if regime_series is not None else "ranging"
        buying_allowed = regime not in GATED_REGIMES

        low = candle["low"]
        high = candle["high"]
        close = candle["close"]

        # If the regime just flipped into trend_down, liquidate all holdings.
        if (
            exit_on_trend_down
            and regime == "trend_down"
            and prev_regime != "trend_down"
            and holdings
        ):
            for i, (qty, cb) in list(holdings.items()):
                proceeds = qty * close
                fee = proceeds * cfg.fee_rate
                slip = proceeds * cfg.slippage
                net = proceeds - fee - slip
                cash += net
                fees_paid += fee + slip
                cumulative_realized_pnl += net - cb
                realized_fills += 1
            holdings.clear()

        # Buy pass: skipped when regime is gated.
        if not buying_allowed:
            gated_candles += 1
        else:
            for i in range(len(levels) - 1):
                if i in holdings:
                    continue
                level = levels[i]
                if low <= level and cash >= capital_per_grid:
                    qty = capital_per_grid / level
                    fee = capital_per_grid * cfg.fee_rate
                    slip = capital_per_grid * cfg.slippage
                    cost_basis = capital_per_grid + fee + slip
                    cash -= cost_basis
                    fees_paid += fee + slip
                    holdings[i] = (qty, cost_basis)
                    realized_fills += 1

        # Sell pass: always active regardless of regime.
        for i in list(holdings.keys()):
            target = levels[i + 1]
            if high >= target:
                qty, cost_basis = holdings.pop(i)
                proceeds = qty * target
                fee = proceeds * cfg.fee_rate
                slip = proceeds * cfg.slippage
                net = proceeds - fee - slip
                cash += net
                fees_paid += fee + slip
                realized_fills += 1
                round_trips += 1
                pnl = net - cost_basis
                cumulative_realized_pnl += pnl
                if pnl > 0:
                    winning_round_trips += 1

        inventory_value = sum(qty * close for qty, _ in holdings.values())
        current_equity = cash + inventory_value
        peak_equity = max(peak_equity, current_equity)

        # Circuit breaker: halt and liquidate if drawdown from peak exceeds threshold.
        if cfg.circuit_breaker_pct is not None:
            drawdown = (current_equity / peak_equity - 1.0) * 100.0
            if drawdown <= -cfg.circuit_breaker_pct:
                for i, (qty, cb) in list(holdings.items()):
                    proceeds = qty * close
                    fee = proceeds * cfg.fee_rate
                    slip = proceeds * cfg.slippage
                    net = proceeds - fee - slip
                    cash += net
                    fees_paid += fee + slip
                    pnl = net - cb
                    cumulative_realized_pnl += pnl
                    realized_fills += 1
                holdings.clear()
                halted = True
                current_equity = cash

        # Range breakout invalidation: halt if price closes decisively below the grid floor.
        # Uses the close price (not the intraday low) so brief wicks do not trigger it.
        # A close below lower * (1 - invalidation_pct/100) means the range thesis is broken.
        if not halted and cfg.invalidation_pct is not None:
            threshold = cfg.lower * (1.0 - cfg.invalidation_pct / 100.0)
            if close < threshold:
                for i, (qty, cb) in list(holdings.items()):
                    proceeds = qty * close
                    fee = proceeds * cfg.fee_rate
                    slip = proceeds * cfg.slippage
                    net = proceeds - fee - slip
                    cash += net
                    fees_paid += fee + slip
                    pnl = net - cb
                    cumulative_realized_pnl += pnl
                    realized_fills += 1
                holdings.clear()
                halted = True
                current_equity = cash

        equity.append(current_equity)
        prev_regime = regime

    equity_curve = pd.Series(equity, index=candles.index, name="equity")
    last_close = candles.iloc[-1]["close"]
    final_inventory_value = sum(qty * last_close for qty, _ in holdings.values())
    remaining_cost_basis = sum(cb for _, cb in holdings.values())
    unrealized_pnl = final_inventory_value - remaining_cost_basis

    return GridResult(
        equity_curve=equity_curve,
        realized_fills=realized_fills,
        round_trips=round_trips,
        winning_round_trips=winning_round_trips,
        final_cash=cash,
        final_inventory_value=final_inventory_value,
        fees_paid=fees_paid,
        realized_profit=cumulative_realized_pnl,
        unrealized_profit=unrealized_pnl,
        breaker_tripped=halted,
        gated_candles=gated_candles,
        config=cfg,
    )
