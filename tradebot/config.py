"""Bot configuration, loaded from YAML and validated before anything runs."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from .data import timeframe_seconds

# Only simulated trading exists in this codebase. Trading real money should be
# a deliberate code change reviewed by a human, never a config flag.
SUPPORTED_MODES = ("paper",)


class ConfigError(ValueError):
    pass


@dataclass
class StrategyConfig:
    fast: int = 20  # bars in the fast moving average
    slow: int = 50  # bars in the slow moving average


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01  # equity lost if a stop is hit (before fees/gaps)
    stop_loss_pct: float = 0.03  # exit when price falls this far below entry
    max_position_pct: float = 0.25  # cap on one symbol's value as a share of equity
    daily_loss_limit_pct: float = 0.03  # no new entries after losing this much today
    max_drawdown_pct: float = 0.15  # flatten everything and halt at this drawdown


@dataclass
class Config:
    mode: str = "paper"
    exchange: str = "binance"
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT", "PAXG/USDT"])
    timeframe: str = "1h"
    starting_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_pct: float = 0.0005
    min_order_value: float = 10.0
    poll_seconds: int = 60
    state_file: str = "state/paper_account.json"
    trade_log: str = "state/trades.csv"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    def validate(self) -> None:
        errors: list[str] = []
        if self.mode not in SUPPORTED_MODES:
            errors.append(
                f"mode {self.mode!r} is not supported. Only 'paper' exists: "
                "real-money trading is deliberately not implemented (see README)."
            )
        if not self.symbols or not all(isinstance(s, str) and "/" in s for s in self.symbols):
            errors.append(f"symbols must be a non-empty list like ['BTC/USDT'], got {self.symbols!r}")
        try:
            timeframe_seconds(self.timeframe)
        except ValueError as exc:
            errors.append(str(exc))

        _number(errors, "starting_cash", self.starting_cash, 0, float("inf"))
        _number(errors, "fee_rate", self.fee_rate, 0, 0.01, allow_low=True)
        _number(errors, "slippage_pct", self.slippage_pct, 0, 0.01, allow_low=True)
        _number(errors, "min_order_value", self.min_order_value, 0, float("inf"), allow_low=True)
        _number(errors, "poll_seconds", self.poll_seconds, 5, 86_400, allow_low=True)

        s = self.strategy
        if not (isinstance(s.fast, int) and isinstance(s.slow, int) and 1 <= s.fast < s.slow):
            errors.append(f"strategy needs integers with 1 <= fast < slow, got fast={s.fast!r} slow={s.slow!r}")

        r = self.risk
        _number(errors, "risk.risk_per_trade", r.risk_per_trade, 0, 0.05)
        _number(errors, "risk.stop_loss_pct", r.stop_loss_pct, 0, 0.5)
        _number(errors, "risk.max_position_pct", r.max_position_pct, 0, 1)
        _number(errors, "risk.daily_loss_limit_pct", r.daily_loss_limit_pct, 0, 1)
        _number(errors, "risk.max_drawdown_pct", r.max_drawdown_pct, 0, 1)

        if errors:
            raise ConfigError("invalid config:\n  " + "\n  ".join(errors))


def _number(errors: list[str], name: str, value, low, high, allow_low: bool = False) -> None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if ok:
        ok = (low <= value if allow_low else low < value) and value <= high
    if not ok:
        bracket = "[" if allow_low else "("
        errors.append(f"{name} must be a number in {bracket}{low}, {high}], got {value!r}")


def _known_keys(cls, raw, where: str) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping, got {type(raw).__name__}")
    unknown = set(raw) - {f.name for f in fields(cls)}
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(sorted(unknown))}")
    return raw


def load_config(path: str | Path | None = None) -> Config:
    """Load and validate a config file; ``None`` gives the defaults."""
    raw: dict = {}
    if path is not None:
        raw = _known_keys(Config, yaml.safe_load(Path(path).read_text()), "config")
        raw = dict(raw)
    strategy = StrategyConfig(**_known_keys(StrategyConfig, raw.pop("strategy", None), "strategy"))
    risk = RiskConfig(**_known_keys(RiskConfig, raw.pop("risk", None), "risk"))
    cfg = Config(**raw, strategy=strategy, risk=risk)
    cfg.validate()
    return cfg
