"""The live paper-trading loop: real prices, simulated money.

Each step marks the account to market, enforces stops and loss limits, then
acts on any candle that has closed since the last step. State and every trade
are written to disk as they happen, so the bot can be stopped and restarted.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable

from .broker import PaperBroker, load_state, save_state
from .config import Config
from .data import drop_unclosed
from .market import MarketData
from .risk import daily_loss_hit, drawdown_hit, position_size
from .strategy import Signal, latest_signal

log = logging.getLogger("tradebot")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PaperTrader:
    def __init__(self, cfg: Config, market: MarketData, clock: Callable[[], datetime] = utc_now):
        self.cfg = cfg
        self.market = market
        self.clock = clock
        self.state = load_state(cfg.state_file, cfg.starting_cash)
        self.broker = PaperBroker(self.state, cfg.fee_rate, cfg.slippage_pct, trade_log=cfg.trade_log)

    def step(self) -> None:
        state, risk = self.state, self.cfg.risk
        if state.halted:
            log.warning(
                "halted (%s). Review %s, then `python -m tradebot reset --yes` to start over.",
                state.halt_reason,
                self.cfg.trade_log,
            )
            return

        now = self.clock()
        stamp = now.isoformat(timespec="seconds")
        symbols = list(dict.fromkeys([*self.cfg.symbols, *state.positions]))
        prices = {s: self.market.fetch_price(s) for s in symbols}

        today = now.strftime("%Y-%m-%d")
        if today != state.day:
            state.day = today
            state.day_start_equity = self.broker.equity(prices)

        for symbol, pos in list(state.positions.items()):
            if prices[symbol] <= pos.stop_price:
                self._sell(symbol, prices[symbol], stamp, "stop")

        equity = self.broker.equity(prices)
        state.peak_equity = max(state.peak_equity, equity)
        if drawdown_hit(equity, state.peak_equity, risk):
            for symbol in list(state.positions):
                self._sell(symbol, prices[symbol], stamp, "max drawdown")
            state.halted = True
            state.halt_reason = f"equity {equity:.2f} fell {risk.max_drawdown_pct:.0%} below peak {state.peak_equity:.2f} at {stamp}"
            save_state(state, self.cfg.state_file)
            log.error("KILL SWITCH: %s. Bot halted.", state.halt_reason)
            return

        for symbol in self.cfg.symbols:
            self._act_on_new_candle(symbol, prices, now, stamp)

        save_state(state, self.cfg.state_file)
        held = ", ".join(f"{s} {p.qty:.6g}" for s, p in state.positions.items()) or "none"
        log.info("equity %.2f | cash %.2f | positions: %s", self.broker.equity(prices), state.cash, held)

    def _act_on_new_candle(self, symbol: str, prices: dict[str, float], now: datetime, stamp: str) -> None:
        state, strat, risk = self.state, self.cfg.strategy, self.cfg.risk
        candles = self.market.fetch_candles(symbol, self.cfg.timeframe, limit=strat.slow + 5)
        candles = drop_unclosed(candles, self.cfg.timeframe, now)
        if len(candles) < strat.slow + 1:
            log.warning("%s: only %d closed candles, need %d", symbol, len(candles), strat.slow + 1)
            return
        bar_ms = int(candles.index[-1].timestamp() * 1000)
        if state.last_bar.get(symbol) == bar_ms:
            return  # already acted on this candle
        state.last_bar[symbol] = bar_ms

        signal = latest_signal(candles["close"], strat.fast, strat.slow)
        if signal == Signal.EXIT and symbol in state.positions:
            self._sell(symbol, prices[symbol], stamp, "signal")
        elif signal == Signal.BUY and symbol not in state.positions:
            equity = self.broker.equity(prices)
            if daily_loss_hit(equity, state.day_start_equity, risk):
                log.warning("%s: BUY skipped, daily loss limit reached", symbol)
                return
            fill = prices[symbol] * (1 + self.cfg.slippage_pct)
            qty = position_size(equity, fill, state.cash, risk, self.cfg.fee_rate)
            if qty * fill < self.cfg.min_order_value:
                log.info("%s: BUY skipped, order value %.2f below minimum", symbol, qty * fill)
                return
            trade = self.broker.buy(symbol, qty, prices[symbol], risk.stop_loss_pct, stamp)
            save_state(state, self.cfg.state_file)
            log.info("PAPER BUY  %s qty %.6g @ %.4f (stop %.4f)", symbol, qty, trade.price, state.positions[symbol].stop_price)

    def _sell(self, symbol: str, price: float, stamp: str, reason: str) -> None:
        trade = self.broker.sell(symbol, price, stamp, reason)
        save_state(self.state, self.cfg.state_file)
        log.info("PAPER SELL %s qty %.6g @ %.4f (%s) pnl %+.2f", symbol, trade.qty, trade.price, reason, trade.pnl)

    def run(self, max_steps: int | None = None) -> None:
        """Step every ``poll_seconds`` until interrupted. Network hiccups are
        logged and retried; anything else stops the bot so bugs stay visible."""
        import ccxt

        steps = 0
        while max_steps is None or steps < max_steps:
            try:
                self.step()
            except ccxt.NetworkError as exc:
                log.warning("network problem, retrying next poll: %s", exc)
            steps += 1
            if self.state.halted:
                break
            if max_steps is None or steps < max_steps:
                time.sleep(self.cfg.poll_seconds)
