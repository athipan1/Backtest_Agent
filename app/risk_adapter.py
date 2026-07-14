from __future__ import annotations

from app.models import RiskCheckPayload, RiskDecision


class LocalRiskAdapter:
    """Deterministic Risk_Agent-compatible adapter for backtest simulations.

    This local adapter mirrors the most important safety semantics used in live
    risk checks: emergency halt, trade count circuit breaker, positive quantity,
    per-trade loss budget, and max position allocation. A future adapter can
    call the real Risk_Agent over HTTP using the same payload/decision contract.
    """

    def evaluate(
        self,
        payload: RiskCheckPayload,
        *,
        max_position_pct: float,
        max_trades_per_day: int,
        risk_per_trade: float | None = None,
    ) -> RiskDecision:
        violations: list[str] = []
        warnings: list[str] = []
        kill_switch_active = False

        if payload.emergency_halt:
            violations.append("emergency_halt_active")
            kill_switch_active = True
        if payload.trades_today >= max_trades_per_day:
            violations.append("max_trades_per_day_exceeded")
            kill_switch_active = True
        if payload.requested_quantity <= 0:
            violations.append("quantity_must_be_positive")
        if payload.entry_price <= 0:
            violations.append("entry_price_must_be_positive")

        risk_per_share = (
            payload.entry_price - payload.protection_price
            if payload.side == "buy"
            else payload.protection_price - payload.entry_price
        )
        if risk_per_share <= 0:
            violations.append("invalid_protection_price")

        max_position_value = payload.equity * max_position_pct
        requested_value = payload.entry_price * payload.requested_quantity
        final_quantity = payload.requested_quantity
        if requested_value > max_position_value and payload.entry_price > 0:
            final_quantity = int(max_position_value / payload.entry_price)
            warnings.append("quantity_clipped_to_position_cap")

        if risk_per_trade is not None and risk_per_share > 0:
            risk_quantity = int(
                (payload.equity * risk_per_trade) / risk_per_share
            )
            if final_quantity > risk_quantity:
                final_quantity = risk_quantity
                warnings.append("quantity_clipped_to_risk_budget")

        approved = not violations and final_quantity > 0
        return RiskDecision(
            approved=approved,
            final_quantity=final_quantity if approved else 0.0,
            violations=violations,
            warnings=warnings,
            kill_switch_active=kill_switch_active,
            source="local_backtest_risk",
        )
