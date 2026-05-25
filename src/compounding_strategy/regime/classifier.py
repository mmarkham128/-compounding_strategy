"""Regime classifier.

Labels each candle as one of four regimes from a small, robust indicator set:
trend strength (ADX), trend direction (fast versus slow EMA), and volatility
(ATR as a fraction of price). A simple classifier that holds up out of sample
beats a complex one tuned to a single period, so the rule set stays compact
and the thresholds live in config for Phase 0 tuning.
"""

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from .indicators import adx, atr, ema


class Regime(str, Enum):
    RANGING = "ranging"
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    CHOP = "chop"


@dataclass
class RegimeConfig:
    adx_period: int = 14
    adx_trend_threshold: float = 25.0
    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    atr_chop_threshold: float = 0.04  # ATR as a fraction of price
    bb_period: int = 20


def classify(df: pd.DataFrame, cfg: RegimeConfig | None = None) -> pd.Series:
    """Return a series of regime labels aligned to the candle index."""
    cfg = cfg or RegimeConfig()
    close = df["close"]

    adx_vals = adx(df, cfg.adx_period)
    ema_fast = ema(close, cfg.ema_fast)
    ema_slow = ema(close, cfg.ema_slow)
    atr_pct = atr(df, cfg.atr_period) / close

    labels = []
    for i in range(len(df)):
        a = adx_vals.iloc[i]
        fast = ema_fast.iloc[i]
        slow = ema_slow.iloc[i]
        vol = atr_pct.iloc[i]

        if pd.isna(a) or pd.isna(slow):
            labels.append(Regime.RANGING.value)
            continue

        trending = a >= cfg.adx_trend_threshold
        if trending and fast > slow:
            labels.append(Regime.TREND_UP.value)
        elif trending and fast < slow:
            labels.append(Regime.TREND_DOWN.value)
        elif vol >= cfg.atr_chop_threshold:
            labels.append(Regime.CHOP.value)
        else:
            labels.append(Regime.RANGING.value)

    return pd.Series(labels, index=df.index, name="regime")
