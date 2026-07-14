from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import fmean, pstdev
from typing import Dict, Iterable, List, Optional

from app.models import EquityPoint, PriceBar


@dataclass(frozen=True)
class PortfolioAnalytics:
    annualized_return: Optional[float]
    annualized_volatility: Optional[float]
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    calmar_ratio: Optional[float]
    benchmark_return_pct: Optional[float]
    excess_return_pct: Optional[float]


def periodic_returns(
    initial_equity: float,
    curve: Iterable[EquityPoint],
) -> List[float]:
    """Calculate returns with initial equity as the first-period baseline."""
    previous = initial_equity
    returns: List[float] = []
    for point in curve:
        if previous > 0:
            returns.append((point.equity / previous) - 1.0)
        previous = point.equity
    return returns


def equal_weight_buy_and_hold_return(
    symbols: Iterable[str],
    bars_by_symbol: Dict[str, List[PriceBar]],
) -> Optional[float]:
    """Return a frictionless equal-weight buy-and-hold universe benchmark."""
    constituent_returns: List[float] = []
    for symbol in symbols:
        rows = sorted(
            bars_by_symbol.get(symbol.upper(), []),
            key=lambda bar: bar.timestamp,
        )
        if not rows or rows[0].open <= 0:
            continue
        constituent_returns.append((rows[-1].close / rows[0].open) - 1.0)
    if not constituent_returns:
        return None
    return fmean(constituent_returns)


def portfolio_analytics(
    *,
    initial_equity: float,
    final_equity: float,
    curve: List[EquityPoint],
    max_drawdown: float,
    periods_per_year: int,
    annual_risk_free_rate: float,
    benchmark_return_pct: Optional[float],
) -> PortfolioAnalytics:
    returns = periodic_returns(initial_equity, curve)
    total_return = (final_equity / initial_equity) - 1.0

    annualized_return: Optional[float] = None
    if returns and initial_equity > 0 and final_equity > 0:
        annualized_return = (
            (final_equity / initial_equity)
            ** (periods_per_year / len(returns))
        ) - 1.0

    annualized_volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    if len(returns) >= 2:
        periodic_risk_free = (
            (1.0 + annual_risk_free_rate) ** (1.0 / periods_per_year)
        ) - 1.0
        excess_returns = [value - periodic_risk_free for value in returns]
        mean_excess = fmean(excess_returns)
        volatility = pstdev(returns)
        annualized_volatility = volatility * sqrt(periods_per_year)
        if volatility > 0:
            sharpe_ratio = mean_excess / volatility * sqrt(periods_per_year)

        downside_deviation = sqrt(
            fmean(min(0.0, value) ** 2 for value in excess_returns)
        )
        if downside_deviation > 0:
            sortino_ratio = (
                mean_excess / downside_deviation * sqrt(periods_per_year)
            )

    calmar_ratio = None
    if annualized_return is not None and max_drawdown < 0:
        calmar_ratio = annualized_return / abs(max_drawdown)

    excess_return_pct = None
    if benchmark_return_pct is not None:
        excess_return_pct = total_return - benchmark_return_pct

    return PortfolioAnalytics(
        annualized_return=_rounded(annualized_return),
        annualized_volatility=_rounded(annualized_volatility),
        sharpe_ratio=_rounded(sharpe_ratio),
        sortino_ratio=_rounded(sortino_ratio),
        calmar_ratio=_rounded(calmar_ratio),
        benchmark_return_pct=_rounded(benchmark_return_pct),
        excess_return_pct=_rounded(excess_return_pct),
    )


def _rounded(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 6)
