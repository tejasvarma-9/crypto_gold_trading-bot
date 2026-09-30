"""Replay historical candles through the same strategy, risk rules and paper
broker the live loop uses.

Timing rule: a signal is decided at a bar's close and filled at the next
bar's open. Stops are checked against each bar's low and fill at the stop
price, or at the open if the price gapped straight through it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .broker import AccountState, PaperBroker, Trade
from .config import Config
from .data import timeframe_seconds
from .risk import daily_loss_hit, drawdown_hit, position_size
from .strategy import Signal, signal_series


@dataclass
class BacktestResult:
    symbol: str
    equity: pd.Series
    trades: list[Trade]
    stats: dict


def run_backtest(candles: pd.DataFrame, cfg: Config, symbol: str = "ASSET") -> BacktestResult:
    strat, risk = cfg.strategy, cfg.risk
    if len(candles) < strat.slow + 2:
        raise ValueError(f"need at least {strat.slow + 2} candles, got {len(candles)}")

    signals = signal_series(candles["close"], strat.fast, strat.slow).to_numpy()
    opens, lows, closes = (candles[k].to_numpy() for k in ("open", "low", "close"))
    times = candles.index

    state = AccountState.new(cfg.starting_cash)
    broker = PaperBroker(state, cfg.fee_rate, cfg.slippage_pct)
    equity = np.empty(len(candles))
    pending = Signal.HOLD
    bars_in_market = 0

    for i in range(len(candles)):
        stamp = times[i].isoformat()
        day = times[i].strftime("%Y-%m-%d")
        if day != state.day:
            state.day = day
            state.day_start_equity = broker.equity({symbol: opens[i]})

        # 1. Fill the order decided at the previous close.
        if pending == Signal.BUY and not state.halted and symbol not in state.positions:
            open_equity = broker.equity({symbol: opens[i]})
            if not daily_loss_hit(open_equity, state.day_start_equity, risk):
                fill = opens[i] * (1 + cfg.slippage_pct)
                qty = position_size(open_equity, fill, state.cash, risk, cfg.fee_rate)
                if qty * fill >= cfg.min_order_value:
                    broker.buy(symbol, qty, opens[i], risk.stop_loss_pct, stamp)
        elif pending == Signal.EXIT and symbol in state.positions:
            broker.sell(symbol, opens[i], stamp, "signal")
        pending = Signal.HOLD

        # 2. Stop loss inside the bar.
        pos = state.positions.get(symbol)
        if pos is not None and lows[i] <= pos.stop_price:
            broker.sell(symbol, min(opens[i], pos.stop_price), stamp, "stop")

        if symbol in state.positions:
            bars_in_market += 1

        # 3. Mark to market and enforce the drawdown kill switch.
        eq = broker.equity({symbol: closes[i]})
        state.peak_equity = max(state.peak_equity, eq)
        if not state.halted and drawdown_hit(eq, state.peak_equity, risk):
            if symbol in state.positions:
                broker.sell(symbol, closes[i], stamp, "max drawdown")
            state.halted = True
            state.halt_reason = f"max drawdown hit at {stamp}"
            eq = broker.equity({symbol: closes[i]})
        equity[i] = eq

        # 4. Decide at the close; fill at the next open.
        if not state.halted:
            if signals[i] == Signal.BUY and symbol not in state.positions:
                pending = Signal.BUY
            elif signals[i] == Signal.EXIT and symbol in state.positions:
                pending = Signal.EXIT

    equity_series = pd.Series(equity, index=times, name="equity")
    stats = _stats(equity_series, broker.trades, candles, cfg, bars_in_market, state)
    return BacktestResult(symbol, equity_series, broker.trades, stats)


def _stats(equity: pd.Series, trades: list[Trade], candles: pd.DataFrame, cfg: Config, bars_in_market: int, state: AccountState) -> dict:
    returns = equity.pct_change().dropna()
    bars_per_year = 365 * 86_400 / timeframe_seconds(cfg.timeframe)  # crypto trades every day
    std = returns.std()
    sells = [t for t in trades if t.side == "sell"]
    first, last = candles["close"].iloc[0], candles["close"].iloc[-1]
    # The fair benchmark: hold the same slice of the account the strategy is
    # allowed to use, paying the same fees and slippage once in and once out.
    friction = (1 + cfg.slippage_pct) * (1 + cfg.fee_rate)
    held = last * (1 - cfg.slippage_pct) * (1 - cfg.fee_rate) / (first * friction) - 1
    return {
        "final_equity": float(equity.iloc[-1]),
        "total_return": float(equity.iloc[-1] / cfg.starting_cash - 1),
        "same_size_hold_return": float(cfg.risk.max_position_pct * held),
        "position_pct": cfg.risk.max_position_pct,
        "buy_and_hold_return": float(last / first - 1),
        "max_drawdown": float((1 - equity / equity.cummax()).max()),
        "sharpe": float(returns.mean() / std * math.sqrt(bars_per_year)) if std > 0 else 0.0,
        "round_trips": len(sells),
        "win_rate": sum(t.pnl > 0 for t in sells) / len(sells) if sells else 0.0,
        "fees_paid": float(sum(t.fee for t in trades)),
        "time_in_market": bars_in_market / len(equity),
        "halted": state.halted,
    }


def format_report(result: BacktestResult) -> str:
    s = result.stats
    first, last = result.equity.index[0], result.equity.index[-1]
    lines = [
        f"{result.symbol}: {first:%Y-%m-%d} to {last:%Y-%m-%d} ({len(result.equity)} bars)",
        f"  strategy return        {s['total_return']:+8.2%}   (final equity {s['final_equity']:,.2f})",
        f"  hold, same size        {s['same_size_hold_return']:+8.2%}   ({s['position_pct']:.0%} of equity, after fees; the fair benchmark)",
        f"  hold, all in           {s['buy_and_hold_return']:+8.2%}   (100% of equity, no fees; not comparable)",
        f"  max drawdown           {s['max_drawdown']:8.2%}",
        f"  sharpe (annual)        {s['sharpe']:8.2f}",
        f"  round trips            {s['round_trips']:8d}   win rate {s['win_rate']:.0%}",
        f"  fees paid              {s['fees_paid']:8.2f}",
        f"  time in market         {s['time_in_market']:8.0%}",
    ]
    if s["halted"]:
        lines.append("  HALTED by the max-drawdown kill switch")
    return "\n".join(lines)
