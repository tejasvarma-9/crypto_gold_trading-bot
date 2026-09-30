import csv
from datetime import datetime, timezone

import pytest

from tradebot.broker import AccountState, save_state
from tradebot.config import RiskConfig
from tradebot.runner import PaperTrader

from .helpers import CROSS_UP, candles_from_closes


class FakeMarket:
    def __init__(self, closes, price):
        self.set_candles(closes)
        self.price = price

    def set_candles(self, closes):
        self.candles = candles_from_closes(closes)

    def fetch_candles(self, symbol, timeframe, limit):
        return self.candles.iloc[-limit:]

    def fetch_price(self, symbol):
        return self.price


class Clock:
    def __init__(self, hour, minute=30):
        self.now = datetime(2025, 1, 1, hour, minute, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def trade_rows(cfg):
    try:
        with open(cfg.trade_log) as fh:
            return list(csv.DictReader(fh))
    except FileNotFoundError:
        return []


# Candles 00:00-04:00 are closed; the 05:00 candle is still forming at 05:30.
# Its close of 1 would trigger an exit if the bot wrongly acted on it.
FORMING_CRASH = CROSS_UP + [1]


def test_buys_on_closed_crossover_and_ignores_forming_candle(cfg):
    trader = PaperTrader(cfg, FakeMarket(FORMING_CRASH, price=10), Clock(5))
    trader.step()

    pos = trader.state.positions["BTC/USDT"]
    assert pos.qty == pytest.approx(250)  # capped at 25% of 10,000 at price 10
    assert pos.stop_price == pytest.approx(9.7)
    assert len(trade_rows(cfg)) == 1


def test_acts_once_per_candle_and_survives_restart(cfg):
    market, clock = FakeMarket(FORMING_CRASH, price=10), Clock(5)
    PaperTrader(cfg, market, clock).step()

    restarted = PaperTrader(cfg, market, clock)
    assert "BTC/USDT" in restarted.state.positions
    restarted.step()
    restarted.step()
    assert len(trade_rows(cfg)) == 1


def test_stop_loss_exit(cfg):
    market = FakeMarket(FORMING_CRASH, price=10)
    trader = PaperTrader(cfg, market, Clock(5))
    trader.step()
    market.price = 9.6
    trader.step()

    assert trader.state.positions == {}
    assert trade_rows(cfg)[-1]["reason"] == "stop"


def test_exit_signal_on_next_closed_candle(cfg):
    market, clock = FakeMarket(FORMING_CRASH, price=10), Clock(5)
    trader = PaperTrader(cfg, market, clock)
    trader.step()

    market.set_candles(CROSS_UP + [4, 20])  # 05:00 closes at 4 -> fast drops below slow
    market.price = 9.9  # above the 9.7 stop, so only the signal can close it
    clock.now = clock.now.replace(hour=6)
    trader.step()

    assert trader.state.positions == {}
    assert trade_rows(cfg)[-1]["reason"] == "signal"


def test_kill_switch_flattens_and_stays_halted(cfg):
    cfg.risk = RiskConfig(risk_per_trade=0.05, stop_loss_pct=0.05, max_position_pct=1.0, max_drawdown_pct=0.01)
    market, clock = FakeMarket(FORMING_CRASH, price=10), Clock(5)
    trader = PaperTrader(cfg, market, clock)
    trader.step()
    market.price = 9.8
    trader.step()

    assert trader.state.halted
    assert trader.state.positions == {}
    assert trade_rows(cfg)[-1]["reason"] == "max drawdown"

    # A restart with a fresh crossover must not trade.
    market.set_candles([10, 9, 8, 7, 6, 5, 9, 1])
    market.price = 9
    clock.now = clock.now.replace(hour=7)
    restarted = PaperTrader(cfg, market, clock)
    restarted.step()
    assert restarted.state.halted
    assert restarted.state.positions == {}


def test_daily_loss_limit_blocks_new_entries(cfg):
    state = AccountState.new(10_000)
    state.day, state.day_start_equity = "2025-01-01", 20_000  # already down 50% today
    save_state(state, cfg.state_file)

    trader = PaperTrader(cfg, FakeMarket(FORMING_CRASH, price=10), Clock(5))
    trader.step()
    assert trader.state.positions == {}
    assert trade_rows(cfg) == []
