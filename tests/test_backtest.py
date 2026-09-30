import pytest

from tradebot.backtest import format_report, run_backtest
from tradebot.config import RiskConfig
from tradebot.data import synthetic_ohlcv

from .helpers import CROSS_UP, candles_from_closes


def test_signal_at_close_fills_at_next_open(cfg):
    closes = CROSS_UP + [11, 12]
    opens = [10, 10, 9, 8, 7, 10.5, 11]
    candles = candles_from_closes(closes, opens=opens)
    result = run_backtest(candles, cfg, "BTC/USDT")

    buy = result.trades[0]
    assert buy.side == "buy"
    assert buy.time == candles.index[5].isoformat()  # crossover was bar 4
    assert buy.price == pytest.approx(10.5)


def test_stop_fills_at_stop_price(cfg):
    closes = CROSS_UP + [10.4, 9]
    candles = candles_from_closes(closes)  # entry at bar 5 open = 10, stop 9.7
    result = run_backtest(candles, cfg, "BTC/USDT")

    sell = result.trades[-1]
    assert (sell.side, sell.reason) == ("sell", "stop")
    assert sell.price == pytest.approx(9.7)


def test_stop_fills_at_open_when_price_gaps_through_it(cfg):
    closes = CROSS_UP + [10.4, 8.8]
    opens = [10, 10, 9, 8, 7, 10, 9.0]
    candles = candles_from_closes(closes, opens=opens)
    sell = run_backtest(candles, cfg, "BTC/USDT").trades[-1]
    assert sell.reason == "stop"
    assert sell.price == pytest.approx(9.0)


def test_no_trades_means_flat_equity(cfg):
    candles = candles_from_closes(range(1, 30))  # steady uptrend, never a crossover
    result = run_backtest(candles, cfg, "BTC/USDT")
    assert result.trades == []
    assert (result.equity == cfg.starting_cash).all()


def test_drawdown_kill_switch_stops_all_trading(cfg):
    cfg.risk = RiskConfig(risk_per_trade=0.05, stop_loss_pct=0.05, max_position_pct=1.0, max_drawdown_pct=0.01)
    # Entry at 10 with the whole account, a 2% drop halts it, then a fresh
    # crossover later must be ignored.
    closes = CROSS_UP + [10, 9.8, 9, 8, 7, 12, 13]
    result = run_backtest(candles_from_closes(closes), cfg, "BTC/USDT")

    assert [(t.side, t.reason) for t in result.trades] == [("buy", "signal"), ("sell", "max drawdown")]
    assert result.stats["halted"]
    assert "HALTED" in format_report(result)


def test_synthetic_run_is_consistent(cfg):
    cfg.strategy.fast, cfg.strategy.slow = 20, 50
    candles = synthetic_ohlcv(bars=2_000, seed=1)
    result = run_backtest(candles, cfg, "SYN")

    assert len(result.equity) == len(candles)
    buys = sum(t.side == "buy" for t in result.trades)
    sells = sum(t.side == "sell" for t in result.trades)
    assert buys - sells in (0, 1)
    assert result.stats["round_trips"] == sells
    realised = sum(t.pnl for t in result.trades if t.side == "sell")
    if buys == sells:  # flat at the end: equity is starting cash plus realised P&L
        assert result.stats["final_equity"] == pytest.approx(cfg.starting_cash + realised)


def test_too_little_history_is_rejected(cfg):
    with pytest.raises(ValueError):
        run_backtest(candles_from_closes([1, 2, 3]), cfg)
