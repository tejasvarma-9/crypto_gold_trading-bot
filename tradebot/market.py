"""Read-only market data from a public exchange API.

This module never receives API keys and cannot place orders. Paper trading
only needs public prices.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import pandas as pd

from .data import drop_unclosed, frame_from_ohlcv, timeframe_seconds


class MarketData(Protocol):
    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame: ...

    def fetch_price(self, symbol: str) -> float: ...


class ExchangeMarketData:
    def __init__(self, exchange_id: str = "binance", exchange=None):
        if exchange is None:
            import ccxt

            if not hasattr(ccxt, exchange_id):
                raise ValueError(f"ccxt has no exchange called {exchange_id!r}")
            exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self.exchange = exchange

    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        return frame_from_ohlcv(self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit))

    def fetch_price(self, symbol: str) -> float:
        ticker = self.exchange.fetch_ticker(symbol)
        price = ticker.get("last") or ticker.get("close")
        if not price:
            raise RuntimeError(f"exchange returned no price for {symbol}")
        return float(price)

    def fetch_history(self, symbol: str, timeframe: str, since: datetime, until: datetime) -> pd.DataFrame:
        """Closed candles between ``since`` and ``until``, paging through the
        exchange's per-request limit."""
        step_ms = timeframe_seconds(timeframe) * 1000
        cursor = int(since.timestamp() * 1000)
        end = int(until.timestamp() * 1000)
        rows: list = []
        while cursor < end:
            batch = self.exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
            if not batch:
                break
            rows.extend(row for row in batch if row[0] < end)
            next_cursor = batch[-1][0] + step_ms
            if next_cursor <= cursor:
                break
            cursor = next_cursor
        candles = frame_from_ohlcv(rows)
        candles = candles[~candles.index.duplicated(keep="last")].sort_index()
        return drop_unclosed(candles, timeframe, until)
