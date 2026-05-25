"""Performance metrics computed from an equity curve."""

import numpy as np
import pandas as pd


def max_drawdown_pct(equity: pd.Series) -> float:
    """Largest peak to trough decline, as a negative percentage."""
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min() * 100.0)


def sharpe_ratio(equity: pd.Series, periods_per_year: int) -> float:
    """Annualized Sharpe from per candle returns, risk free rate assumed zero."""
    returns = equity.pct_change().dropna()
    if len(returns) == 0 or returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def annualized_return_pct(equity: pd.Series, periods_per_year: int) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    years = len(equity) / periods_per_year
    if years <= 0:
        return 0.0
    return float((total ** (1 / years) - 1) * 100.0)
