"""OHLCV data loading via ccxt with a local CSV cache.

This module reaches an exchange API to download candles, so it runs on your
machine rather than inside a restricted sandbox. Binance is the default source
for clean history. Execution later happens on Blofin, but price history is
effectively identical across venues, so the data source and the execution
venue do not need to match for backtesting.
"""

import time
from pathlib import Path

import pandas as pd

try:
    import ccxt
except ImportError:  # ccxt is only needed for live downloads, not for tests
    ccxt = None

CACHE_DIR = Path("data_cache")


def _ms(dt: str) -> int:
    return int(pd.Timestamp(dt, tz="UTC").timestamp() * 1000)


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    since: str = "2025-05-25",
    until: str | None = None,
    exchange_id: str = "binance",
    use_cache: bool = True,
) -> pd.DataFrame:
    """Download candles and return a frame indexed by UTC timestamp.

    Columns: open, high, low, close, volume.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    safe = symbol.replace("/", "_")
    cache_file = CACHE_DIR / f"{exchange_id}_{safe}_{timeframe}_{since}.csv"

    if use_cache and cache_file.exists():
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)

    if ccxt is None:
        raise ImportError("ccxt is required to download data. Run: pip install ccxt")

    exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    since_ms = _ms(since)
    until_ms = _ms(until) if until else int(time.time() * 1000)

    rows = []
    while since_ms < until_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < 1000:
            break

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")

    if use_cache:
        df.to_csv(cache_file)
    return df
