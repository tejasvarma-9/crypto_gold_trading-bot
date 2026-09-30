from __future__ import annotations

import pytest

from tradebot.config import Config, RiskConfig, StrategyConfig


@pytest.fixture
def cfg(tmp_path) -> Config:
    config = Config(
        symbols=["BTC/USDT"],
        fee_rate=0.001,
        slippage_pct=0.0,
        min_order_value=1.0,
        state_file=str(tmp_path / "state.json"),
        trade_log=str(tmp_path / "trades.csv"),
        strategy=StrategyConfig(fast=2, slow=3),
        risk=RiskConfig(
            risk_per_trade=0.01,
            stop_loss_pct=0.03,
            max_position_pct=0.25,
            daily_loss_limit_pct=0.03,
            max_drawdown_pct=0.15,
        ),
    )
    config.validate()
    return config
