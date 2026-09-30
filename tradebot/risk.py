"""Position sizing and account-level loss limits."""

from __future__ import annotations

from .config import RiskConfig


def position_size(equity: float, fill_price: float, cash: float, risk: RiskConfig, fee_rate: float) -> float:
    """Quantity to buy so that hitting the stop loses about ``risk_per_trade``
    of equity, capped by ``max_position_pct`` and by the cash available.

    Fees, slippage and price gaps through the stop can make the real loss a
    little larger than the target.
    """
    if equity <= 0 or fill_price <= 0 or cash <= 0:
        return 0.0
    by_risk = equity * risk.risk_per_trade / (fill_price * risk.stop_loss_pct)
    by_cap = equity * risk.max_position_pct / fill_price
    by_cash = cash / (fill_price * (1 + fee_rate))
    return min(by_risk, by_cap, by_cash)


def daily_loss_hit(equity: float, day_start_equity: float, risk: RiskConfig) -> bool:
    return equity <= day_start_equity * (1 - risk.daily_loss_limit_pct)


def drawdown_hit(equity: float, peak_equity: float, risk: RiskConfig) -> bool:
    return equity <= peak_equity * (1 - risk.max_drawdown_pct)
