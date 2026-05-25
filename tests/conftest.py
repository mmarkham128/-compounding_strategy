"""Synthetic market fixtures for offline, deterministic tests.

Real data downloads run on your machine. The test suite uses generated candles
so it passes anywhere with no network and no API keys.
"""

import numpy as np
import pandas as pd
import pytest


def _ohlc_from_close(close: np.ndarray, noise: float = 0.002, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=len(close), freq="h", tz="UTC")
    close_s = pd.Series(close, index=idx)
    open_s = close_s.shift(1).fillna(close_s.iloc[0])

    hi_base = pd.concat([open_s, close_s], axis=1).max(axis=1)
    lo_base = pd.concat([open_s, close_s], axis=1).min(axis=1)
    high = hi_base * (1 + rng.uniform(0, noise, len(close)))
    low = lo_base * (1 - rng.uniform(0, noise, len(close)))

    return pd.DataFrame({"open": open_s, "high": high, "low": low, "close": close_s})


@pytest.fixture
def ranging_market() -> pd.DataFrame:
    # Mean reverting whipsaw around 100. Frequent reversals keep ADX low, which
    # is the defining trait of a ranging market and the home turf of a grid.
    rng = np.random.default_rng(42)
    n = 2000
    close = np.empty(n)
    close[0] = 100.0
    for i in range(1, n):
        close[i] = close[i - 1] + 0.15 * (100 - close[i - 1]) + rng.normal(0, 0.8)
    return _ohlc_from_close(close)


@pytest.fixture
def uptrend_market() -> pd.DataFrame:
    t = np.arange(2000)
    close = 100 + t * 0.05 + 1.5 * np.sin(t / 15.0)
    return _ohlc_from_close(close)


@pytest.fixture
def downtrend_market() -> pd.DataFrame:
    t = np.arange(2000)
    close = 200 - t * 0.05 + 1.5 * np.sin(t / 15.0)
    return _ohlc_from_close(close)
