from __future__ import annotations

from math import floor

from app.execution_policy import current_execution_policy, quantize_quantity


def volume_capacity(volume: float, max_participation_pct: float) -> int:
    if volume <= 0 or max_participation_pct <= 0:
        return 0
    return quantize_quantity(max(0, floor(volume * max_participation_pct)))


def participation_rate(quantity: float, volume: float) -> float:
    if quantity <= 0 or volume <= 0:
        return 0.0
    return min(1.0, quantity / volume)


def linear_market_impact_bps(
    quantity: float,
    volume: float,
    market_impact_bps: float,
) -> float:
    return market_impact_bps * participation_rate(quantity, volume)


def buy_execution_price(
    reference_price: float,
    *,
    slippage_bps: float,
    market_impact_bps: float,
    quantity: float,
    volume: float,
) -> float:
    policy = current_execution_policy()
    impact = linear_market_impact_bps(quantity, volume, market_impact_bps)
    half_spread = policy.bid_ask_spread_bps / 2.0
    return reference_price * (
        1.0 + (slippage_bps + impact + half_spread) / 10000.0
    )


def sell_execution_price(
    reference_price: float,
    *,
    slippage_bps: float,
    market_impact_bps: float,
    quantity: float,
    volume: float,
) -> float:
    policy = current_execution_policy()
    impact = linear_market_impact_bps(quantity, volume, market_impact_bps)
    half_spread = policy.bid_ask_spread_bps / 2.0
    return reference_price * (
        1.0 - (slippage_bps + impact + half_spread) / 10000.0
    )


def max_entry_quantity(
    requested_quantity: int,
    *,
    available_volume_quantity: int,
    reference_price: float,
    bar_volume: float,
    slippage_bps: float,
    market_impact_bps: float,
    fee_bps: float,
    remaining_cash: float,
    remaining_exposure: float,
    portfolio_equity: float,
    risk_per_trade: float,
    max_position_pct: float,
    stop_loss_pct: float,
) -> int:
    """Find the largest increment-aligned fill satisfying every constraint."""

    policy = current_execution_policy()
    increment = policy.quantity_increment
    upper = quantize_quantity(
        max(0, min(requested_quantity, available_volume_quantity))
    )

    def allowed(quantity: int) -> bool:
        price = buy_execution_price(
            reference_price,
            slippage_bps=slippage_bps,
            market_impact_bps=market_impact_bps,
            quantity=quantity,
            volume=bar_volume,
        )
        value = price * quantity
        fees = value * fee_bps / 10000.0
        return (
            value + fees <= remaining_cash
            and value <= remaining_exposure
            and value <= portfolio_equity * max_position_pct
            and value * stop_loss_pct <= portfolio_equity * risk_per_trade
        )

    low_steps = 0
    high_steps = upper // increment
    while low_steps < high_steps:
        middle_steps = (low_steps + high_steps + 1) // 2
        quantity = middle_steps * increment
        if allowed(quantity):
            low_steps = middle_steps
        else:
            high_steps = middle_steps - 1
    return low_steps * increment
