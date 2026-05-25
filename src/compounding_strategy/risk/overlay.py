"""Risk overlay.

Sits between signals and execution and can veto any order. Always on, in every
phase. Three guards:

* Per strategy drawdown circuit breaker, halts one bot that has bled past its
  allocation limit.
* Account level kill switch, halts everything when total equity falls too far
  from its peak.
* Equity based fractional sizing, the mechanism that lets gains compound while
  exposure shrinks automatically during a drawdown.

Leverage is capped here too. It stays at 1 (spot only) until the edge is proven
in shadow mode, then rises toward the 10 to 15 band, always reversible.
"""

from dataclasses import dataclass


@dataclass
class RiskConfig:
    max_strategy_drawdown_pct: float = 20.0
    account_kill_switch_pct: float = 30.0
    leverage_cap: float = 1.0
    risk_fraction: float = 0.02  # fraction of equity deployed per new position


class RiskOverlay:
    def __init__(self, cfg: RiskConfig, starting_equity: float):
        self.cfg = cfg
        self.starting_equity = starting_equity
        self.peak_equity = starting_equity
        self.killed = False

    def update_equity(self, equity: float) -> None:
        self.peak_equity = max(self.peak_equity, equity)
        drawdown = (equity / self.peak_equity - 1.0) * 100.0
        if drawdown <= -self.cfg.account_kill_switch_pct:
            self.killed = True

    def strategy_halted(self, allocated: float, current: float) -> bool:
        if allocated <= 0:
            return False
        drawdown = (current / allocated - 1.0) * 100.0
        return drawdown <= -self.cfg.max_strategy_drawdown_pct

    def position_size(self, equity: float) -> float:
        return equity * self.cfg.risk_fraction

    def leverage_allowed(self, requested: float) -> float:
        return min(requested, self.cfg.leverage_cap)

    def can_trade(self) -> bool:
        return not self.killed
