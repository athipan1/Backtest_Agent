from app.models import RiskCheckPayload
from app.risk_adapter import LocalRiskAdapter


def test_local_risk_adapter_approves_safe_trade():
    decision = LocalRiskAdapter().evaluate(
        RiskCheckPayload(symbol="AAPL", side="buy", entry_price=100, protection_price=97, equity=100000, requested_quantity=50),
        max_position_pct=0.10,
        max_trades_per_day=5,
    )

    assert decision.approved is True
    assert decision.final_quantity == 50
    assert decision.violations == []


def test_local_risk_adapter_rejects_emergency_halt():
    decision = LocalRiskAdapter().evaluate(
        RiskCheckPayload(symbol="AAPL", side="buy", entry_price=100, protection_price=97, equity=100000, requested_quantity=50, emergency_halt=True),
        max_position_pct=0.10,
        max_trades_per_day=5,
    )

    assert decision.approved is False
    assert decision.kill_switch_active is True
    assert "emergency_halt_active" in decision.violations


def test_local_risk_adapter_clips_to_position_cap():
    decision = LocalRiskAdapter().evaluate(
        RiskCheckPayload(symbol="AAPL", side="buy", entry_price=100, protection_price=97, equity=100000, requested_quantity=500),
        max_position_pct=0.10,
        max_trades_per_day=5,
    )

    assert decision.approved is True
    assert decision.final_quantity == 100
    assert "quantity_clipped_to_position_cap" in decision.warnings
