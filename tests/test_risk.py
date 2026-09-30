import pytest

from tradebot.config import RiskConfig
from tradebot.risk import daily_loss_hit, drawdown_hit, position_size

RISK = RiskConfig(risk_per_trade=0.01, stop_loss_pct=0.03, max_position_pct=0.25, daily_loss_limit_pct=0.03, max_drawdown_pct=0.15)


def test_size_capped_by_max_position():
    # Risk alone would allow 10000*0.01/(100*0.03) = 33.3 units; the 25% cap is 25.
    assert position_size(10_000, 100, 10_000, RISK, 0.001) == pytest.approx(25)


def test_size_limited_by_risk_when_stop_is_wide():
    wide = RiskConfig(risk_per_trade=0.01, stop_loss_pct=0.10, max_position_pct=1.0)
    assert position_size(10_000, 100, 10_000, wide, 0.0) == pytest.approx(10)  # 100 / (100 * 0.10)


def test_size_limited_by_cash():
    assert position_size(10_000, 100, 500, RISK, 0.0) == pytest.approx(5)


def test_zero_size_without_cash():
    assert position_size(10_000, 100, 0, RISK, 0.001) == 0


def test_daily_loss_limit():
    assert not daily_loss_hit(9_701, 10_000, RISK)
    assert daily_loss_hit(9_700, 10_000, RISK)


def test_drawdown_kill_switch():
    assert not drawdown_hit(8_501, 10_000, RISK)
    assert drawdown_hit(8_500, 10_000, RISK)
