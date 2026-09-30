import csv

import pytest

from tradebot.broker import AccountState, InsufficientFunds, PaperBroker, load_state, save_state


def test_round_trip_pays_fees_on_both_sides():
    broker = PaperBroker(AccountState.new(1_000), fee_rate=0.001, slippage_pct=0.0)
    broker.buy("BTC/USDT", 1, 100, stop_loss_pct=0.03, time="t0")
    assert broker.state.cash == pytest.approx(1_000 - 100 - 0.1)
    assert broker.state.positions["BTC/USDT"].stop_price == pytest.approx(97)

    trade = broker.sell("BTC/USDT", 110, time="t1", reason="signal")
    assert trade.pnl == pytest.approx(110 - 0.11 - 100.1)
    assert broker.state.cash == pytest.approx(1_000 + trade.pnl)
    assert broker.state.positions == {}


def test_slippage_always_hurts():
    broker = PaperBroker(AccountState.new(1_000), fee_rate=0.0, slippage_pct=0.01)
    buy = broker.buy("BTC/USDT", 1, 100, stop_loss_pct=0.03, time="t0")
    sell = broker.sell("BTC/USDT", 100, time="t1", reason="signal")
    assert buy.price == pytest.approx(101)
    assert sell.price == pytest.approx(99)
    assert sell.pnl == pytest.approx(-2)


def test_equity_marks_positions_to_market():
    broker = PaperBroker(AccountState.new(1_000), fee_rate=0.0, slippage_pct=0.0)
    broker.buy("BTC/USDT", 2, 100, stop_loss_pct=0.03, time="t0")
    assert broker.equity({"BTC/USDT": 150}) == pytest.approx(800 + 300)


def test_cannot_overspend_or_double_buy():
    broker = PaperBroker(AccountState.new(100), fee_rate=0.001, slippage_pct=0.0)
    with pytest.raises(InsufficientFunds):
        broker.buy("BTC/USDT", 1, 100, stop_loss_pct=0.03, time="t0")
    broker.buy("BTC/USDT", 0.5, 100, stop_loss_pct=0.03, time="t0")
    with pytest.raises(ValueError):
        broker.buy("BTC/USDT", 0.1, 100, stop_loss_pct=0.03, time="t1")
    with pytest.raises(ValueError):
        broker.sell("ETH/USDT", 100, time="t1", reason="signal")


def test_state_survives_restart(tmp_path):
    path = tmp_path / "state.json"
    broker = PaperBroker(AccountState.new(1_000), fee_rate=0.001, slippage_pct=0.0)
    broker.buy("PAXG/USDT", 0.1, 2_500, stop_loss_pct=0.03, time="t0")
    broker.state.last_bar["PAXG/USDT"] = 123
    save_state(broker.state, path)

    restored = load_state(path, starting_cash=999)
    assert restored == broker.state
    assert load_state(tmp_path / "missing.json", starting_cash=500).cash == 500


def test_trade_log_has_one_header(tmp_path):
    log = tmp_path / "trades.csv"
    broker = PaperBroker(AccountState.new(1_000), fee_rate=0.0, slippage_pct=0.0, trade_log=log)
    broker.buy("BTC/USDT", 1, 100, stop_loss_pct=0.03, time="t0")
    broker.sell("BTC/USDT", 105, time="t1", reason="signal")
    rows = list(csv.DictReader(log.open()))
    assert [r["side"] for r in rows] == ["buy", "sell"]
    assert float(rows[1]["pnl"]) == pytest.approx(5)
