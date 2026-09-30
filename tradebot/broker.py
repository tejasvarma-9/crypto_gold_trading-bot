"""Simulated exchange account.

Every fill pays the configured fee and slippage, so paper results are not
rosier than a real account would be. Nothing in this module talks to an
exchange.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping


class InsufficientFunds(Exception):
    pass


@dataclass
class Position:
    qty: float
    entry_price: float  # fill price, slippage included
    cost: float  # cash spent, entry fee included
    stop_price: float
    opened_at: str


@dataclass
class Trade:
    time: str
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    pnl: float  # realised profit after both fees on sells, 0 on buys
    reason: str
    cash_after: float


@dataclass
class AccountState:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    peak_equity: float = 0.0
    day: str = ""  # UTC date the daily loss limit is measured from
    day_start_equity: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    last_bar: dict[str, int] = field(default_factory=dict)  # symbol -> last candle acted on (ms)

    @classmethod
    def new(cls, cash: float) -> "AccountState":
        return cls(cash=cash, peak_equity=cash, day_start_equity=cash)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "AccountState":
        raw = dict(raw)
        raw["positions"] = {s: Position(**p) for s, p in raw.get("positions", {}).items()}
        return cls(**raw)


def load_state(path: str | Path, starting_cash: float) -> AccountState:
    path = Path(path)
    if not path.exists():
        return AccountState.new(starting_cash)
    return AccountState.from_dict(json.loads(path.read_text()))


def save_state(state: AccountState, path: str | Path) -> None:
    """Write atomically so a crash mid-write cannot corrupt the account."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2))
    os.replace(tmp, path)


class PaperBroker:
    def __init__(
        self,
        state: AccountState,
        fee_rate: float,
        slippage_pct: float,
        trade_log: str | Path | None = None,
    ):
        self.state = state
        self.fee_rate = fee_rate
        self.slippage_pct = slippage_pct
        self.trade_log = Path(trade_log) if trade_log else None
        self.trades: list[Trade] = []

    def equity(self, prices: Mapping[str, float]) -> float:
        return self.state.cash + sum(p.qty * prices[s] for s, p in self.state.positions.items())

    def buy(self, symbol: str, qty: float, price: float, stop_loss_pct: float, time: str, reason: str = "signal") -> Trade:
        if symbol in self.state.positions:
            raise ValueError(f"already holding {symbol}")
        if qty <= 0:
            raise ValueError(f"quantity must be positive, got {qty}")
        fill = price * (1 + self.slippage_pct)
        notional = qty * fill
        fee = notional * self.fee_rate
        if notional + fee > self.state.cash + 1e-6:
            raise InsufficientFunds(f"need {notional + fee:.2f}, have {self.state.cash:.2f}")
        self.state.cash = max(0.0, self.state.cash - notional - fee)
        self.state.positions[symbol] = Position(qty, fill, notional + fee, fill * (1 - stop_loss_pct), time)
        return self._record(Trade(time, symbol, "buy", qty, fill, fee, 0.0, reason, self.state.cash))

    def sell(self, symbol: str, price: float, time: str, reason: str) -> Trade:
        if symbol not in self.state.positions:
            raise ValueError(f"no {symbol} position to sell")
        pos = self.state.positions.pop(symbol)
        fill = price * (1 - self.slippage_pct)
        notional = pos.qty * fill
        fee = notional * self.fee_rate
        self.state.cash += notional - fee
        pnl = notional - fee - pos.cost
        return self._record(Trade(time, symbol, "sell", pos.qty, fill, fee, pnl, reason, self.state.cash))

    def _record(self, trade: Trade) -> Trade:
        self.trades.append(trade)
        if self.trade_log is not None:
            self.trade_log.parent.mkdir(parents=True, exist_ok=True)
            new_file = not self.trade_log.exists() or self.trade_log.stat().st_size == 0
            with self.trade_log.open("a", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(asdict(trade)))
                if new_file:
                    writer.writeheader()
                writer.writerow(asdict(trade))
        return trade
