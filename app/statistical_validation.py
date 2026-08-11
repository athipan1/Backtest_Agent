from __future__ import annotations

import math
import random
from statistics import NormalDist, mean, stdev
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models import BacktestRunResult


_NORMAL = NormalDist()
_EULER_MASCHERONI = 0.5772156649015329
_MAX_ABS_PERIODIC_SHARPE = 10.0
STATISTICAL_VALIDATION_V1 = "statistical-validation.v1"
STATISTICAL_VALIDATION_V2 = "statistical-validation.v2"
BootstrapMethod = Literal["iid", "moving_block", "stationary"]
_TIME_SERIES_BOOTSTRAP_METHODS = frozenset({"moving_block", "stationary"})


class StatisticalValidationCriteria(BaseModel):
    """Conservative time-series-aware evidence gates for strategy selection."""

    enabled: bool = True
    min_observations: int = Field(default=30, ge=10)
    min_trades: int = Field(default=10, ge=1)
    max_adjusted_p_value: float = Field(default=0.05, gt=0, le=1)
    min_probabilistic_sharpe_ratio: float = Field(default=0.95, ge=0, le=1)
    min_deflated_sharpe_probability: float = Field(default=0.90, ge=0, le=1)
    min_bootstrap_annualized_return: float = 0.0
    min_hac_mean_positive_probability: float = Field(default=0.95, ge=0, le=1)
    bootstrap_method: BootstrapMethod = "stationary"
    bootstrap_block_size: int = Field(default=10, ge=2, le=10000)
    bootstrap_confidence: float = Field(default=0.95, gt=0.5, lt=1)
    bootstrap_simulations: int = Field(default=500, ge=100, le=10000)
    bootstrap_seed: int = 42


class StatisticalValidationResult(BaseModel):
    schema_version: Literal[
        "statistical-validation.v1",
        "statistical-validation.v2",
    ] = STATISTICAL_VALIDATION_V2
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
    autocorrelation_lag1: Optional[float] = None
    hac_standard_error: Optional[float] = None
    hac_lag_count: Optional[int] = None
    effective_sample_size: Optional[float] = None
    hac_mean_positive_probability: Optional[float] = None
    sharpe_standard_error: Optional[float] = None
    raw_one_sided_p_value: Optional[float] = None
    adjusted_p_value: Optional[float] = None
    probabilistic_sharpe_ratio: Optional[float] = None
    expected_max_sharpe_ratio: Optional[float] = None
    deflated_sharpe_probability: Optional[float] = None
    bootstrap_method: Optional[BootstrapMethod] = None
    bootstrap_block_size: Optional[int] = None
    bootstrap_confidence: Optional[float] = None
    bootstrap_annualized_return_lower: Optional[float] = None
    bootstrap_annualized_return_upper: Optional[float] = None
    block_bootstrap_annualized_return_lower: Optional[float] = None
    block_bootstrap_annualized_return_upper: Optional[float] = None
    iid_bootstrap_annualized_return_lower: Optional[float] = None
    iid_bootstrap_annualized_return_upper: Optional[float] = None
    gates: dict[str, bool] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    method: str = "bonferroni_psr_dsr_hac_and_time_series_bootstrap"


def parse_statistical_validation_evidence(
    payload: dict[str, Any],
) -> StatisticalValidationResult:
    """Read historical v1 evidence without treating it as new v2 authority."""

    normalized = dict(payload)
    normalized.setdefault("schema_version", STATISTICAL_VALIDATION_V1)
    return StatisticalValidationResult.model_validate(normalized)


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


def _require_finite_returns(values: list[float]) -> None:
    if not values:
        raise ValueError("returns must not be empty")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("returns must contain only finite values")


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


def _lag1_autocorrelation(values: list[float], average: float) -> float:
    if len(values) < 2:
        return 0.0
    denominator = sum((value - average) ** 2 for value in values)
    if denominator <= 0:
        return 0.0
    numerator = sum(
        (values[index] - average) * (values[index - 1] - average)
        for index in range(1, len(values))
    )
    return max(-1.0, min(1.0, numerator / denominator))


def _newey_west_standard_error(
    values: list[float],
    *,
    average: float,
    max_lag: int,
) -> float:
    """Return Newey-West HAC standard error of the sample mean."""

    _require_finite_returns(values)
    size = len(values)
    if size < 2:
        return 0.0
    lag_count = max(0, min(max_lag, size - 1))
    demeaned = [value - average for value in values]
    gamma_zero = sum(value * value for value in demeaned) / size
    long_run_variance = gamma_zero
    for lag in range(1, lag_count + 1):
        covariance = sum(
            demeaned[index] * demeaned[index - lag]
            for index in range(lag, size)
        ) / size
        bartlett_weight = 1.0 - lag / (lag_count + 1.0)
        long_run_variance += 2.0 * bartlett_weight * covariance
    return math.sqrt(max(long_run_variance, 0.0) / size)


def _effective_sample_size(
    *,
    sigma: float,
    hac_standard_error: float,
    observations: int,
) -> float:
    if observations <= 1:
        return float(observations)
    if sigma <= 0 or hac_standard_error <= 0:
        return float(observations)
    implied = (sigma**2) / (hac_standard_error**2)
    return max(1.0, min(float(observations), implied))


def _sharpe_standard_error(
    *,
    sharpe_ratio: float,
    skewness: float,
    kurtosis: float,
    observations: float,
) -> float:
    variance_term = max(
        1e-12,
        1.0
        - skewness * sharpe_ratio
        + ((kurtosis - 1.0) / 4.0) * sharpe_ratio**2,
    )
    return math.sqrt(variance_term / max(observations - 1.0, 1.0))


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


def _bootstrap_sample(
    returns: list[float],
    *,
    method: BootstrapMethod,
    block_size: int,
    rng: random.Random,
) -> list[float]:
    size = len(returns)
    if method == "iid":
        return [rng.choice(returns) for _ in range(size)]

    if method == "moving_block":
        sample: list[float] = []
        maximum_start = size - block_size
        while len(sample) < size:
            start = rng.randint(0, maximum_start)
            sample.extend(returns[start : start + block_size])
        return sample[:size]

    restart_probability = 1.0 / block_size
    index = rng.randrange(size)
    sample = []
    for _ in range(size):
        sample.append(returns[index])
        if rng.random() < restart_probability:
            index = rng.randrange(size)
        else:
            index = (index + 1) % size
    return sample


def _bootstrap_annualized_mean_interval(
    returns: list[float],
    *,
    periods_per_year: int,
    simulations: int,
    confidence: float,
    seed: int,
    method: BootstrapMethod = "iid",
    block_size: int = 2,
) -> tuple[float, float]:
    _require_finite_returns(returns)
    if method in _TIME_SERIES_BOOTSTRAP_METHODS:
        if block_size < 2:
            raise ValueError("time-series bootstrap block_size must be at least 2")
        if len(returns) < 2 * block_size:
            raise ValueError(
                "time-series bootstrap requires at least two full expected blocks"
            )
    rng = random.Random(seed)
    size = len(returns)
    samples = []
    for _ in range(simulations):
        sampled = _bootstrap_sample(
            returns,
            method=method,
            block_size=block_size,
            rng=rng,
        )
        samples.append((sum(sampled) / size) * periods_per_year)
    samples.sort()
    tail = (1.0 - confidence) / 2.0
    lower_index = max(0, min(simulations - 1, int(math.floor(tail * simulations))))
    upper_index = max(
        0,
        min(simulations - 1, int(math.ceil((1.0 - tail) * simulations)) - 1),
    )
    return samples[lower_index], samples[upper_index]


def _finite_periodic_sharpe(average: float, sigma: float) -> float:
    if sigma <= 0:
        if average > 0:
            return _MAX_ABS_PERIODIC_SHARPE
        if average < 0:
            return -_MAX_ABS_PERIODIC_SHARPE
        return 0.0
    return max(
        -_MAX_ABS_PERIODIC_SHARPE,
        min(_MAX_ABS_PERIODIC_SHARPE, average / sigma),
    )


def _disabled_result(
    *,
    observation_count: int,
    trade_count: int,
    candidate_count: int,
    criteria: StatisticalValidationCriteria,
) -> StatisticalValidationResult:
    return StatisticalValidationResult(
        status="disabled",
        passed=True,
        observation_count=observation_count,
        trade_count=trade_count,
        candidate_count=candidate_count,
        bootstrap_method=criteria.bootstrap_method,
        bootstrap_block_size=(
            criteria.bootstrap_block_size
            if criteria.bootstrap_method in _TIME_SERIES_BOOTSTRAP_METHODS
            else None
        ),
        bootstrap_confidence=criteria.bootstrap_confidence,
        gates={"enabled": True},
    )


def _insufficient_result(
    *,
    observation_count: int,
    trade_count: int,
    candidate_count: int,
    criteria: StatisticalValidationCriteria,
    sample_gate: bool,
    trade_gate: bool,
    reason: str,
    iid_interval: tuple[float, float] | None = None,
) -> StatisticalValidationResult:
    time_series_authority = criteria.bootstrap_method in _TIME_SERIES_BOOTSTRAP_METHODS
    gates = {
        "observation_count": sample_gate,
        "trade_count": trade_gate,
        "adjusted_p_value": False,
        "probabilistic_sharpe_ratio": False,
        "deflated_sharpe_probability": False,
        "bootstrap_lower_bound": False,
        "block_bootstrap_lower_bound": False,
        "hac_mean_confidence": False,
        "time_series_bootstrap_authority": time_series_authority,
    }
    return StatisticalValidationResult(
        status="insufficient_data",
        passed=False,
        observation_count=observation_count,
        trade_count=trade_count,
        candidate_count=candidate_count,
        bootstrap_method=criteria.bootstrap_method,
        bootstrap_block_size=(
            criteria.bootstrap_block_size if time_series_authority else None
        ),
        bootstrap_confidence=criteria.bootstrap_confidence,
        iid_bootstrap_annualized_return_lower=(
            round(iid_interval[0], 8) if iid_interval is not None else None
        ),
        iid_bootstrap_annualized_return_upper=(
            round(iid_interval[1], 8) if iid_interval is not None else None
        ),
        gates=gates,
        reasons=[reason],
    )


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
        return _disabled_result(
            observation_count=observation_count,
            trade_count=trade_count,
            candidate_count=normalized_candidate_count,
            criteria=criteria,
        )

    sample_gate = observation_count >= criteria.min_observations
    trade_gate = trade_count >= criteria.min_trades
    if observation_count < 2:
        return _insufficient_result(
            observation_count=observation_count,
            trade_count=trade_count,
            candidate_count=normalized_candidate_count,
            criteria=criteria,
            sample_gate=sample_gate,
            trade_gate=trade_gate,
            reason="statistical validation requires at least two finite equity returns",
        )

    iid_interval = _bootstrap_annualized_mean_interval(
        returns,
        periods_per_year=periods_per_year,
        simulations=criteria.bootstrap_simulations,
        confidence=criteria.bootstrap_confidence,
        seed=criteria.bootstrap_seed,
        method="iid",
    )
    time_series_authority = criteria.bootstrap_method in _TIME_SERIES_BOOTSTRAP_METHODS
    if time_series_authority and observation_count < 2 * criteria.bootstrap_block_size:
        return _insufficient_result(
            observation_count=observation_count,
            trade_count=trade_count,
            candidate_count=normalized_candidate_count,
            criteria=criteria,
            sample_gate=sample_gate,
            trade_gate=trade_gate,
            reason=(
                "time-series bootstrap requires at least two full expected blocks "
                f"(observations={observation_count}, "
                f"block_size={criteria.bootstrap_block_size})"
            ),
            iid_interval=iid_interval,
        )

    average = mean(returns)
    sigma = stdev(returns)
    annualized_mean = average * periods_per_year
    skewness = _sample_skewness(returns, average, sigma)
    kurtosis = _sample_kurtosis(returns, average, sigma)
    periodic_sharpe = _finite_periodic_sharpe(average, sigma)
    autocorrelation_lag1 = _lag1_autocorrelation(returns, average)
    hac_lag_count = min(
        max(criteria.bootstrap_block_size - 1, 1),
        observation_count - 1,
    )
    hac_standard_error = _newey_west_standard_error(
        returns,
        average=average,
        max_lag=hac_lag_count,
    )
    effective_sample_size = _effective_sample_size(
        sigma=sigma,
        hac_standard_error=hac_standard_error,
        observations=observation_count,
    )
    if hac_standard_error <= 0:
        hac_mean_probability = 1.0 if average > 0 else 0.0
    else:
        hac_mean_probability = _NORMAL.cdf(average / hac_standard_error)
    raw_p_value = 1.0 - hac_mean_probability

    sharpe_standard_error = (
        0.0
        if sigma <= 0
        else _sharpe_standard_error(
            sharpe_ratio=periodic_sharpe,
            skewness=skewness,
            kurtosis=kurtosis,
            observations=effective_sample_size,
        )
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
        method=criteria.bootstrap_method,
        block_size=criteria.bootstrap_block_size,
    )
    block_lower = bootstrap_lower if time_series_authority else None
    block_upper = bootstrap_upper if time_series_authority else None

    bootstrap_gate = (
        bootstrap_lower > criteria.min_bootstrap_annualized_return
        if time_series_authority
        else False
    )
    gates = {
        "observation_count": sample_gate,
        "trade_count": trade_gate,
        "adjusted_p_value": adjusted_p_value <= criteria.max_adjusted_p_value,
        "probabilistic_sharpe_ratio": (
            probabilistic_sharpe >= criteria.min_probabilistic_sharpe_ratio
        ),
        "deflated_sharpe_probability": (
            deflated_sharpe_probability >= criteria.min_deflated_sharpe_probability
        ),
        "bootstrap_lower_bound": bootstrap_gate,
        "block_bootstrap_lower_bound": bootstrap_gate,
        "hac_mean_confidence": (
            hac_mean_probability >= criteria.min_hac_mean_positive_probability
        ),
        "time_series_bootstrap_authority": time_series_authority,
    }
    observations = {
        "observation_count": observation_count,
        "trade_count": trade_count,
        "adjusted_p_value": round(adjusted_p_value, 8),
        "probabilistic_sharpe_ratio": round(probabilistic_sharpe, 8),
        "deflated_sharpe_probability": round(deflated_sharpe_probability, 8),
        "bootstrap_lower_bound": round(bootstrap_lower, 8),
        "block_bootstrap_lower_bound": (
            round(block_lower, 8) if block_lower is not None else None
        ),
        "hac_mean_confidence": round(hac_mean_probability, 8),
        "time_series_bootstrap_authority": criteria.bootstrap_method,
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
        periodic_sharpe_ratio=round(periodic_sharpe, 8),
        skewness=round(skewness, 8),
        kurtosis=round(kurtosis, 8),
        autocorrelation_lag1=round(autocorrelation_lag1, 8),
        hac_standard_error=round(hac_standard_error, 10),
        hac_lag_count=hac_lag_count,
        effective_sample_size=round(effective_sample_size, 6),
        hac_mean_positive_probability=round(hac_mean_probability, 8),
        sharpe_standard_error=round(sharpe_standard_error, 10),
        raw_one_sided_p_value=round(raw_p_value, 8),
        adjusted_p_value=round(adjusted_p_value, 8),
        probabilistic_sharpe_ratio=round(probabilistic_sharpe, 8),
        expected_max_sharpe_ratio=round(expected_max_sharpe, 8),
        deflated_sharpe_probability=round(deflated_sharpe_probability, 8),
        bootstrap_method=criteria.bootstrap_method,
        bootstrap_block_size=(
            criteria.bootstrap_block_size if time_series_authority else None
        ),
        bootstrap_confidence=criteria.bootstrap_confidence,
        bootstrap_annualized_return_lower=round(bootstrap_lower, 8),
        bootstrap_annualized_return_upper=round(bootstrap_upper, 8),
        block_bootstrap_annualized_return_lower=(
            round(block_lower, 8) if block_lower is not None else None
        ),
        block_bootstrap_annualized_return_upper=(
            round(block_upper, 8) if block_upper is not None else None
        ),
        iid_bootstrap_annualized_return_lower=round(iid_interval[0], 8),
        iid_bootstrap_annualized_return_upper=round(iid_interval[1], 8),
        gates=gates,
        reasons=reasons,
    )
