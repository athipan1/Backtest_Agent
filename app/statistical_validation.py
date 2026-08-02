from __future__ import annotations

import math
import random
from statistics import NormalDist, mean, stdev
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models import BacktestRunResult


_NORMAL = NormalDist()
_EULER_MASCHERONI = 0.5772156649015329


class StatisticalValidationCriteria(BaseModel):
    """Conservative evidence gates for strategy selection.

    The defaults require enough observations and trades, a positive bootstrap
    lower bound, and significance that survives the number of candidates tried.
    """

    enabled: bool = True
    min_observations: int = Field(default=30, ge=10)
    min_trades: int = Field(default=10, ge=1)
    max_adjusted_p_value: float = Field(default=0.05, gt=0, le=1)
    min_probabilistic_sharpe_ratio: float = Field(default=0.95, ge=0, le=1)
    min_deflated_sharpe_probability: float = Field(default=0.90, ge=0, le=1)
    min_bootstrap_annualized_return: float = 0.0
    bootstrap_confidence: float = Field(default=0.95, gt=0.5, lt=1)
    bootstrap_simulations: int = Field(default=500, ge=100, le=10000)
    bootstrap_seed: int = 42


class StatisticalValidationResult(BaseModel):
    status: Literal["completed", "insufficient_data", "disabled"]
    passed: bool
    observation_count: int
    trade_count: int
    candidate_count: int
    mean_period_return: Optional[float] = None
    annualized_mean_return: Optional[float] = None
    period_volatility: Optional[float] = None
    periodic_sharpe_ratio: Optional[float] = None
    skewness: Optional[float] = None
    kurtosis: Optional[float] = None
    raw_one_sided_p_value: Optional[float] = None
    adjusted_p_value: Optional[float] = None
    probabilistic_sharpe_ratio: Optional[float] = None
    expected_max_sharpe_ratio: Optional[float] = None
    deflated_sharpe_probability: Optional[float] = None
    bootstrap_confidence: Optional[float] = None
    bootstrap_annualized_return_lower: Optional[float] = None
    bootstrap_annualized_return_upper: Optional[float] = None
    gates: dict[str, bool] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    method: str = (
        "normal_mean_test_bonferroni_psr_dsr_and_iid_bootstrap"
    )


def equity_returns(result: BacktestRunResult) -> list[float]:
    points = sorted(result.equity_curve, key=lambda item: item.timestamp)
    returns: list[float] = []
    for previous, current in zip(points, points[1:]):
        if previous.equity <= 0:
            continue
        value = current.equity / previous.equity - 1.0
        if math.isfinite(value):
            returns.append(value)
    return returns


def _sample_skewness(values: list[float], average: float, sigma: float) -> float:
    size = len(values)
    if size < 3 or sigma <= 0:
        return 0.0
    standardized_sum = sum(((value - average) / sigma) ** 3 for value in values)
    return (size / ((size - 1) * (size - 2))) * standardized_sum


def _sample_kurtosis(values: list[float], average: float, sigma: float) -> float:
    """Return Pearson kurtosis, where a normal distribution is approximately 3."""

    size = len(values)
    if size < 4 or sigma <= 0:
        return 3.0
    fourth_sum = sum(((value - average) / sigma) ** 4 for value in values)
    excess = (
        (size * (size + 1) / ((size - 1) * (size - 2) * (size - 3)))
        * fourth_sum
        - (3 * (size - 1) ** 2 / ((size - 2) * (size - 3)))
    )
    return excess + 3.0


def _sharpe_standard_error(
    *,
    sharpe_ratio: float,
    skewness: float,
    kurtosis: float,
    observations: int,
) -> float:
    variance_term = max(
        1e-12,
        1.0
        - skewness * sharpe_ratio
        + ((kurtosis - 1.0) / 4.0) * sharpe_ratio**2,
    )
    return math.sqrt(variance_term / max(observations - 1, 1))


def _probabilistic_sharpe(
    *,
    sharpe_ratio: float,
    benchmark_sharpe: float,
    standard_error: float,
) -> float:
    if standard_error <= 0:
        return 1.0 if sharpe_ratio > benchmark_sharpe else 0.0
    return _NORMAL.cdf((sharpe_ratio - benchmark_sharpe) / standard_error)


def _expected_max_sharpe(
    *,
    candidate_count: int,
    sharpe_standard_error: float,
) -> float:
    if candidate_count <= 1:
        return 0.0
    first_probability = max(1e-12, min(1 - 1e-12, 1.0 - 1.0 / candidate_count))
    second_probability = max(
        1e-12,
        min(1 - 1e-12, 1.0 - 1.0 / (candidate_count * math.e)),
    )
    expected_standard_normal_max = (
        (1.0 - _EULER_MASCHERONI)
        * _NORMAL.inv_cdf(first_probability)
        + _EULER_MASCHERONI
        * _NORMAL.inv_cdf(second_probability)
    )
    return max(0.0, sharpe_standard_error * expected_standard_normal_max)


def _bootstrap_annualized_mean_interval(
    returns: list[float],
    *,
    periods_per_year: int,
    simulations: int,
    confidence: float,
    seed: int,
) -> tuple[float, float]:
    rng = random.Random(seed)
    size = len(returns)
    samples = []
    for _ in range(simulations):
        sampled_mean = sum(rng.choice(returns) for _ in range(size)) / size
        samples.append(sampled_mean * periods_per_year)
    samples.sort()
    tail = (1.0 - confidence) / 2.0
    lower_index = max(0, min(simulations - 1, int(math.floor(tail * simulations))))
    upper_index = max(
        0,
        min(simulations - 1, int(math.ceil((1.0 - tail) * simulations)) - 1),
    )
    return samples[lower_index], samples[upper_index]


def run_statistical_validation(
    result: BacktestRunResult,
    *,
    candidate_count: int,
    periods_per_year: int,
    criteria: StatisticalValidationCriteria,
) -> StatisticalValidationResult:
    returns = equity_returns(result)
    observation_count = len(returns)
    trade_count = result.metrics.trade_count
    normalized_candidate_count = max(1, candidate_count)

    if not criteria.enabled:
        return StatisticalValidationResult(
            status="disabled",
            passed=True,
            observation_count=observation_count,
            trade_count=trade_count,
            candidate_count=normalized_candidate_count,
            gates={"enabled": True},
        )

    sample_gate = observation_count >= criteria.min_observations
    trade_gate = trade_count >= criteria.min_trades
    if observation_count < 2:
        gates = {
            "observation_count": sample_gate,
            "trade_count": trade_gate,
            "adjusted_p_value": False,
            "probabilistic_sharpe_ratio": False,
            "deflated_sharpe_probability": False,
            "bootstrap_lower_bound": False,
        }
        return StatisticalValidationResult(
            status="insufficient_data",
            passed=False,
            observation_count=observation_count,
            trade_count=trade_count,
            candidate_count=normalized_candidate_count,
            gates=gates,
            reasons=[
                "statistical validation requires at least two finite equity returns"
            ],
        )

    average = mean(returns)
    sigma = stdev(returns)
    annualized_mean = average * periods_per_year
    skewness = _sample_skewness(returns, average, sigma)
    kurtosis = _sample_kurtosis(returns, average, sigma)

    if sigma <= 0:
        periodic_sharpe = 0.0 if average <= 0 else float("inf")
        raw_p_value = 1.0 if average <= 0 else 0.0
        sharpe_standard_error = 0.0
    else:
        periodic_sharpe = average / sigma
        z_score = average / (sigma / math.sqrt(observation_count))
        raw_p_value = 1.0 - _NORMAL.cdf(z_score)
        sharpe_standard_error = _sharpe_standard_error(
            sharpe_ratio=periodic_sharpe,
            skewness=skewness,
            kurtosis=kurtosis,
            observations=observation_count,
        )

    adjusted_p_value = min(1.0, raw_p_value * normalized_candidate_count)
    probabilistic_sharpe = _probabilistic_sharpe(
        sharpe_ratio=periodic_sharpe,
        benchmark_sharpe=0.0,
        standard_error=sharpe_standard_error,
    )
    expected_max_sharpe = _expected_max_sharpe(
        candidate_count=normalized_candidate_count,
        sharpe_standard_error=sharpe_standard_error,
    )
    deflated_sharpe_probability = _probabilistic_sharpe(
        sharpe_ratio=periodic_sharpe,
        benchmark_sharpe=expected_max_sharpe,
        standard_error=sharpe_standard_error,
    )
    bootstrap_lower, bootstrap_upper = _bootstrap_annualized_mean_interval(
        returns,
        periods_per_year=periods_per_year,
        simulations=criteria.bootstrap_simulations,
        confidence=criteria.bootstrap_confidence,
        seed=criteria.bootstrap_seed,
    )

    gates = {
        "observation_count": sample_gate,
        "trade_count": trade_gate,
        "adjusted_p_value": adjusted_p_value <= criteria.max_adjusted_p_value,
        "probabilistic_sharpe_ratio": (
            probabilistic_sharpe
            >= criteria.min_probabilistic_sharpe_ratio
        ),
        "deflated_sharpe_probability": (
            deflated_sharpe_probability
            >= criteria.min_deflated_sharpe_probability
        ),
        "bootstrap_lower_bound": (
            bootstrap_lower
            > criteria.min_bootstrap_annualized_return
        ),
    }
    observations = {
        "observation_count": observation_count,
        "trade_count": trade_count,
        "adjusted_p_value": round(adjusted_p_value, 8),
        "probabilistic_sharpe_ratio": round(probabilistic_sharpe, 8),
        "deflated_sharpe_probability": round(
            deflated_sharpe_probability,
            8,
        ),
        "bootstrap_lower_bound": round(bootstrap_lower, 8),
    }
    reasons = [
        f"statistical_{name} gate failed (observed={observations[name]!r})"
        for name, passed in gates.items()
        if not passed
    ]
    status: Literal["completed", "insufficient_data", "disabled"] = (
        "completed" if sample_gate else "insufficient_data"
    )
    return StatisticalValidationResult(
        status=status,
        passed=all(gates.values()),
        observation_count=observation_count,
        trade_count=trade_count,
        candidate_count=normalized_candidate_count,
        mean_period_return=round(average, 10),
        annualized_mean_return=round(annualized_mean, 8),
        period_volatility=round(sigma, 10),
        periodic_sharpe_ratio=(
            periodic_sharpe
            if math.isinf(periodic_sharpe)
            else round(periodic_sharpe, 8)
        ),
        skewness=round(skewness, 8),
        kurtosis=round(kurtosis, 8),
        raw_one_sided_p_value=round(raw_p_value, 8),
        adjusted_p_value=round(adjusted_p_value, 8),
        probabilistic_sharpe_ratio=round(probabilistic_sharpe, 8),
        expected_max_sharpe_ratio=round(expected_max_sharpe, 8),
        deflated_sharpe_probability=round(
            deflated_sharpe_probability,
            8,
        ),
        bootstrap_confidence=criteria.bootstrap_confidence,
        bootstrap_annualized_return_lower=round(bootstrap_lower, 8),
        bootstrap_annualized_return_upper=round(bootstrap_upper, 8),
        gates=gates,
        reasons=reasons,
    )
