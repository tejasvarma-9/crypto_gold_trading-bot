import pandas as pd

from tradebot.data import synthetic_ohlcv
from tradebot.strategy import Signal, latest_signal, signal_series

from .helpers import CROSS_UP


def test_buy_fires_only_on_the_crossing_bar():
    signals = signal_series(pd.Series(CROSS_UP + [11, 12], dtype=float), fast=2, slow=3)
    assert list(signals) == [
        Signal.HOLD,  # not enough history
        Signal.HOLD,
        Signal.EXIT,  # first full slow average, downtrend
        Signal.EXIT,
        Signal.BUY,  # the crossover
        Signal.HOLD,  # still above, no new entry
        Signal.HOLD,
    ]


def test_no_buy_on_first_valid_bar_of_an_uptrend():
    # fast > slow as soon as the slow average exists, but there was no cross.
    signals = signal_series(pd.Series([1, 2, 3, 4, 5], dtype=float), fast=2, slow=3)
    assert Signal.BUY not in list(signals)


def test_exit_when_fast_drops_below_slow():
    signals = signal_series(pd.Series(CROSS_UP + [4], dtype=float), fast=2, slow=3)
    assert signals.iloc[-1] == Signal.EXIT


def test_signals_never_use_future_bars():
    close = synthetic_ohlcv(bars=400, seed=3)["close"]
    full = signal_series(close, fast=5, slow=20)
    for end in range(21, len(close), 17):
        assert latest_signal(close.iloc[: end + 1], fast=5, slow=20) == full.iloc[end]


def test_latest_signal_needs_enough_history():
    assert latest_signal(pd.Series([10, 9, 8], dtype=float), fast=2, slow=3) == Signal.HOLD
