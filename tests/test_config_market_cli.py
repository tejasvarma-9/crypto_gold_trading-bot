from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from tradebot.__main__ import main
from tradebot.config import ConfigError, load_config
from tradebot.data import drop_unclosed, load_csv, save_csv, synthetic_ohlcv, timeframe_seconds
from tradebot.market import ExchangeMarketData

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


def test_repo_config_is_valid():
    cfg = load_config(REPO_CONFIG)
    assert cfg.mode == "paper"
    assert "PAXG/USDT" in cfg.symbols


@pytest.mark.parametrize(
    "text",
    [
        "mode: live",
        "mode: real",
        "leverage: 10",  # unknown keys are errors, not silently ignored
        "strategy: {fast: 50, slow: 20}",
        "risk: {stop_loss_pct: 0}",
        "risk: {risk_per_trade: 0.5}",
        "timeframe: 1x",
    ],
)
def test_bad_configs_are_rejected(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError):
        load_config(path)


def test_timeframes():
    assert timeframe_seconds("15m") == 900
    assert timeframe_seconds("4h") == 14_400
    with pytest.raises(ValueError):
        timeframe_seconds("0h")


def test_drop_unclosed_keeps_only_finished_candles():
    candles = synthetic_ohlcv(bars=5, timeframe="1h", start="2025-01-01")
    now = datetime(2025, 1, 1, 4, 59, tzinfo=timezone.utc)
    assert list(drop_unclosed(candles, "1h", now).index.hour) == [0, 1, 2, 3]


def test_csv_round_trip(tmp_path):
    candles = synthetic_ohlcv(bars=10)
    save_csv(candles, tmp_path / "c.csv")
    pd.testing.assert_frame_equal(load_csv(tmp_path / "c.csv"), candles, check_freq=False)


class FakeExchange:
    """Serves 2,500 hourly candles, at most 1,000 per request, like Binance."""

    def __init__(self):
        start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        self.rows = [[start + i * 3_600_000, 1, 2, 0.5, 1.5, 10] for i in range(2_500)]
        self.calls = 0

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls += 1
        return [r for r in self.rows if since is None or r[0] >= since][:limit]

    def fetch_ticker(self, symbol):
        return {"last": 42.0}


def test_fetch_history_pages_through_the_exchange_limit():
    exchange = FakeExchange()
    market = ExchangeMarketData(exchange=exchange)
    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    until = datetime(2025, 6, 1, tzinfo=timezone.utc)  # past the last candle (mid-April)
    candles = market.fetch_history("BTC/USDT", "1h", since, until)

    assert len(candles) == 2_500
    assert candles.index.is_monotonic_increasing and candles.index.is_unique
    assert exchange.calls >= 3
    assert market.fetch_price("BTC/USDT") == 42.0


def _write_config(tmp_path, extra=""):
    path = tmp_path / "config.yaml"
    path.write_text(f"state_file: {tmp_path / 'state.json'}\ntrade_log: {tmp_path / 'trades.csv'}\n{extra}")
    return str(path)


def test_cli_backtest_synthetic(tmp_path, capsys):
    assert main(["--config", _write_config(tmp_path), "backtest", "--synthetic"]) == 0
    assert "strategy return" in capsys.readouterr().out


def test_cli_refuses_live_mode(tmp_path):
    assert main(["--config", _write_config(tmp_path, "mode: live"), "status"]) == 2


def test_cli_reset_needs_confirmation(tmp_path):
    config = _write_config(tmp_path)
    (tmp_path / "state.json").write_text("{}")
    assert main(["--config", config, "reset"]) == 1
    assert (tmp_path / "state.json").exists()
    assert main(["--config", config, "reset", "--yes"]) == 0
    assert not (tmp_path / "state.json").exists()
