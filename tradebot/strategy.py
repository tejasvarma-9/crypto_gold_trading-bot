"""Moving-average crossover: the simplest trend-following rule worth testing.

Every signal is computed from closed candles up to and including the bar it
belongs to, so the backtest and the live paper loop see the same information.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd


class Signal(str, Enum):
    BUY = "buy"  # fast average crossed above the slow one on this bar
    EXIT = "exit"  # fast average is at or below the slow one: be flat
    HOLD = "hold"  # nothing new (or not enough history yet)


def signal_series(close: pd.Series, fast: int, slow: int) -> pd.Series:
    """One signal per bar.

    A BUY needs a real crossover: both this bar and the previous one must have
    a full slow average. Entering only on the crossing bar (not whenever
    fast > slow) means a stop-loss exit is not immediately re-bought.
    """
    fast_ma = close.rolling(fast).mean()
    slow_ma = close.rolling(slow).mean()
    valid = slow_ma.notna()
    above = fast_ma > slow_ma
    prev_valid = valid.shift(1, fill_value=False)
    prev_above = above.shift(1, fill_value=False)

    signals = pd.Series(Signal.HOLD, index=close.index, dtype=object)
    signals[valid & ~above] = Signal.EXIT
    signals[valid & prev_valid & above & ~prev_above] = Signal.BUY
    return signals


def latest_signal(close: pd.Series, fast: int, slow: int) -> Signal:
    """Signal for the last bar of ``close``."""
    if len(close) < slow + 1:
        return Signal.HOLD
    return signal_series(close, fast, slow).iloc[-1]
