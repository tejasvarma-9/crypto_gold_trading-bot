"""Candle data helpers: frames, CSV files, synthetic prices and timeframes."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3_600, "d": 86_400, "w": 604_800}


def timeframe_seconds(timeframe: str) -> int:
    """'15m' -> 900, '1h' -> 3600, '1d' -> 86400."""
    match = re.fullmatch(r"(\d+)([smhdw])", str(timeframe))
    if not match or int(match.group(1)) == 0:
        raise ValueError(f"timeframe must look like '15m', '1h' or '1d', got {timeframe!r}")
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def frame_from_ohlcv(rows) -> pd.DataFrame:
    """Turn exchange rows ``[ms, open, high, low, close, volume]`` into a frame
    indexed by candle open time (UTC)."""
    df = pd.DataFrame(rows, columns=["timestamp", *COLUMNS])
    index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
    df.index = pd.DatetimeIndex(index, name="time")
    return df.astype(float)


def drop_unclosed(candles: pd.DataFrame, timeframe: str, now: datetime) -> pd.DataFrame:
    """Remove candles that have not closed yet.

    Exchanges return the still-forming candle last. Its close keeps changing
    until the period ends, so acting on it would trade on a price the backtest
    never saw.
    """
    if candles.empty:
        return candles
    closes_at = candles.index + pd.Timedelta(seconds=timeframe_seconds(timeframe))
    return candles[closes_at <= pd.Timestamp(now)]


def load_csv(path: str | Path) -> pd.DataFrame:
    """Read candles written by :func:`save_csv` (or any CSV with a ``time`` or
    millisecond ``timestamp`` column plus open/high/low/close/volume)."""
    df = pd.read_csv(path)
    if "time" in df.columns:
        index = pd.to_datetime(df.pop("time"), utc=True)
    elif "timestamp" in df.columns:
        index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
    else:
        raise ValueError(f"{path}: needs a 'time' or 'timestamp' column")
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing column(s) {', '.join(missing)}")
    df = df[COLUMNS].astype(float)
    df.index = pd.DatetimeIndex(index, name="time")
    return df.sort_index()


def save_csv(candles: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    candles.to_csv(path, index_label="time")


def synthetic_ohlcv(
    bars: int = 3_000,
    timeframe: str = "1h",
    start_price: float = 100.0,
    seed: int = 0,
    start: str = "2024-01-01",
) -> pd.DataFrame:
    """Random-walk prices with alternating up/down/sideways regimes.

    Only useful for checking that the pipeline runs end to end. Results on
    synthetic data say nothing about whether a strategy makes money.
    """
    rng = np.random.default_rng(seed)
    drifts = np.empty(bars)
    i = 0
    while i < bars:
        length = int(rng.integers(100, 400))
        drifts[i : i + length] = rng.choice([-0.0015, 0.0, 0.0015])
        i += length
    returns = drifts + rng.normal(0.0, 0.01, bars)
    close = start_price * np.exp(np.cumsum(returns))
    open_ = np.concatenate([[start_price], close[:-1]])
    wick = np.abs(rng.normal(0.0, 0.004, (2, bars)))
    high = np.maximum(open_, close) * (1 + wick[0])
    low = np.minimum(open_, close) * (1 - wick[1])
    volume = rng.uniform(10, 100, bars)
    index = pd.date_range(start, periods=bars, freq=pd.Timedelta(seconds=timeframe_seconds(timeframe)), tz="UTC", name="time")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index)
