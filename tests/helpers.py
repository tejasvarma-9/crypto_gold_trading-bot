from __future__ import annotations

import pandas as pd


def candles_from_closes(closes, start="2025-01-01", opens=None, lows=None, highs=None) -> pd.DataFrame:
    """Hourly candles. Opens default to the previous close."""
    closes = [float(c) for c in closes]
    opens = opens or [closes[0], *closes[:-1]]
    lows = lows or [min(o, c) for o, c in zip(opens, closes)]
    highs = highs or [max(o, c) for o, c in zip(opens, closes)]
    index = pd.date_range(start, periods=len(closes), freq="1h", tz="UTC", name="time")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 1.0},
        index=index,
    )


# fast=2, slow=3: bars 0-3 trend down, bar 4 is the first bar where the fast
# average crosses above the slow one.
CROSS_UP = [10, 9, 8, 7, 10]
