from __future__ import annotations

import math
import random

import pytest

from app.statistical_validation import (
    STATISTICAL_VALIDATION_V1,
    STATISTICAL_VALIDATION_V2,
    StatisticalValidationCriteria,
    _bootstrap_annualized_mean_interval,
    _newey_west_standard_error,
    parse_statistical_validation_evidence,
    run_statistical_validation,
)
from tests.test_statistical_validation import _result


def _ar1_returns(
    *,
    phi: float,
    drift: float,
    count: int = 160,
    shock_scale: float = 0.0008,
) -> list[float]:
    rng = random.Random(2026)
    state = 0.0
    values: list[float] = []
    for _ in range(count):
        state = phi * state + rng.gauss(0.0, shock_scale)
        values.append(drift + state)
    return values


def _lenient_criteria(**overrides):
    values = {
        "min_observations": 30,
        "min_trades": 1,
        "max_adjusted_p_value": 1.0,
        "min_probabilistic_sharpe_ratio": 0.0,
        "min_deflated_sharpe_probability": 0.0,
        "min_bootstrap_annualized_return": -10.0,
        "min_hac_mean_positive_probability": 0.0,
        "bootstrap_method": "stationary",
        "bootstrap_block_size": 10,
        "bootstrap_simulations": 300,
        "bootstrap_seed": 123,
    }
    values.update(overrides)
    return StatisticalValidationCriteria(**values)


def test_positive_autocorrelation_reduces_effective_sample_size():
    returns = _ar1_returns(phi=0.90, drift=0.0012)

    evidence = run_statistical_validation(
        _result(returns),
        candidate_count=4,
        periods_per_year=252,
        criteria=_lenient_criteria(),
    )

    assert evidence.schema_version == STATISTICAL_VALIDATION_V2
    assert evidence.status == "completed"
    assert evidence.autocorrelation_lag1 is not None
    assert evidence.autocorrelation_lag1 > 0.50
    assert evidence.hac_standard_error is not None
    assert evidence.hac_standard_error > 0
    assert evidence.effective_sample_size is not None
    assert evidence.effective_sample_size < evidence.observation_count
    assert evidence.hac_mean_positive_probability is not None
    assert evidence.bootstrap_method == "stationary"
    assert evidence.bootstrap_block_size == 10
    assert evidence.block_bootstrap_annualized_return_lower is not None
    assert evidence.iid_bootstrap_annualized_return_lower is not None


def test_autocorrelated_negative_returns_fail_return_and_confidence_gates():
    returns = _ar1_returns(phi=0.85, drift=-0.0012)
    criteria = _lenient_criteria(
        max_adjusted_p_value=0.05,
        min_bootstrap_annualized_return=0.0,
        min_hac_mean_positive_probability=0.95,
    )

    evidence = run_statistical_validation(
        _result(returns),
        candidate_count=4,
        periods_per_year=252,
        criteria=criteria,
    )

    assert evidence.status == "completed"
    assert evidence.passed is False
    assert evidence.gates["adjusted_p_value"] is False
    assert evidence.gates["block_bootstrap_lower_bound"] is False
    assert evidence.gates["hac_mean_confidence"] is False
    assert evidence.block_bootstrap_annualized_return_lower is not None
    assert evidence.block_bootstrap_annualized_return_lower < 0


def test_iid_and_block_bootstrap_differ_for_clustered_time_series():
    returns = [0.004] * 20 + [-0.0035] * 20
    returns *= 4

    iid = _bootstrap_annualized_mean_interval(
        returns,
        periods_per_year=252,
        simulations=600,
        confidence=0.95,
        seed=99,
        method="iid",
        block_size=10,
    )
    moving = _bootstrap_annualized_mean_interval(
        returns,
        periods_per_year=252,
        simulations=600,
        confidence=0.95,
        seed=99,
        method="moving_block",
        block_size=10,
    )
    stationary = _bootstrap_annualized_mean_interval(
        returns,
        periods_per_year=252,
        simulations=600,
        confidence=0.95,
        seed=99,
        method="stationary",
        block_size=10,
    )

    assert moving != iid
    assert stationary != iid
    assert moving[1] - moving[0] > iid[1] - iid[0]


def test_moving_block_bootstrap_is_seed_deterministic():
    returns = _ar1_returns(phi=0.60, drift=0.0005, count=100)
    kwargs = {
        "periods_per_year": 252,
        "simulations": 250,
        "confidence": 0.95,
        "seed": 77,
        "method": "moving_block",
        "block_size": 8,
    }

    first = _bootstrap_annualized_mean_interval(returns, **kwargs)
    second = _bootstrap_annualized_mean_interval(returns, **kwargs)

    assert first == second


def test_insufficient_time_series_blocks_fail_closed_with_iid_diagnostic():
    returns = _ar1_returns(phi=0.5, drift=0.0005, count=30)
    evidence = run_statistical_validation(
        _result(returns),
        candidate_count=2,
        periods_per_year=252,
        criteria=_lenient_criteria(
            min_observations=10,
            bootstrap_block_size=20,
            bootstrap_simulations=100,
        ),
    )

    assert evidence.status == "insufficient_data"
    assert evidence.passed is False
    assert evidence.gates["block_bootstrap_lower_bound"] is False
    assert evidence.gates["hac_mean_confidence"] is False
    assert evidence.iid_bootstrap_annualized_return_lower is not None
    assert evidence.block_bootstrap_annualized_return_lower is None
    assert "two full expected blocks" in evidence.reasons[0]


def test_bootstrap_and_hac_reject_non_finite_values():
    bad_returns = [0.001, float("nan"), 0.002, float("inf")]

    with pytest.raises(ValueError, match="finite"):
        _bootstrap_annualized_mean_interval(
            bad_returns,
            periods_per_year=252,
            simulations=100,
            confidence=0.95,
            seed=1,
            method="iid",
            block_size=2,
        )

    with pytest.raises(ValueError, match="finite"):
        _newey_west_standard_error(
            bad_returns,
            average=0.0,
            max_lag=1,
        )


def test_zero_volatility_v2_evidence_remains_finite():
    evidence = run_statistical_validation(
        _result([0.001] * 80),
        candidate_count=4,
        periods_per_year=252,
        criteria=_lenient_criteria(),
    )

    assert evidence.period_volatility == 0.0
    assert evidence.hac_standard_error == 0.0
    assert evidence.effective_sample_size == 80.0
    assert evidence.periodic_sharpe_ratio is not None
    assert math.isfinite(evidence.periodic_sharpe_ratio)
    assert evidence.hac_mean_positive_probability == 1.0
    assert "Infinity" not in evidence.model_dump_json()
    assert "NaN" not in evidence.model_dump_json()


def test_strong_serial_correlation_has_less_effective_information_than_weak():
    strong = run_statistical_validation(
        _result(_ar1_returns(phi=0.92, drift=0.0010)),
        candidate_count=2,
        periods_per_year=252,
        criteria=_lenient_criteria(),
    )
    weak = run_statistical_validation(
        _result(_ar1_returns(phi=0.05, drift=0.0010)),
        candidate_count=2,
        periods_per_year=252,
        criteria=_lenient_criteria(),
    )

    assert strong.autocorrelation_lag1 is not None
    assert weak.autocorrelation_lag1 is not None
    assert strong.autocorrelation_lag1 > weak.autocorrelation_lag1
    assert strong.effective_sample_size is not None
    assert weak.effective_sample_size is not None
    assert strong.effective_sample_size < weak.effective_sample_size
    assert strong.hac_standard_error is not None
    assert weak.hac_standard_error is not None
    assert strong.hac_standard_error > weak.hac_standard_error


def test_iid_bootstrap_is_diagnostic_only_and_never_promotion_authority():
    returns = _ar1_returns(phi=0.4, drift=0.0010, count=120)
    evidence = run_statistical_validation(
        _result(returns),
        candidate_count=1,
        periods_per_year=252,
        criteria=_lenient_criteria(bootstrap_method="iid"),
    )

    assert evidence.status == "completed"
    assert evidence.bootstrap_method == "iid"
    assert evidence.iid_bootstrap_annualized_return_lower is not None
    assert evidence.block_bootstrap_annualized_return_lower is None
    assert evidence.gates["time_series_bootstrap_authority"] is False
    assert evidence.gates["bootstrap_lower_bound"] is False
    assert evidence.passed is False


def test_v1_evidence_can_be_read_but_remains_identified_as_v1():
    legacy = parse_statistical_validation_evidence(
        {
            "status": "completed",
            "passed": True,
            "observation_count": 100,
            "trade_count": 20,
            "candidate_count": 4,
            "bootstrap_annualized_return_lower": 0.05,
            "bootstrap_annualized_return_upper": 0.20,
            "gates": {"bootstrap_lower_bound": True},
        }
    )

    assert legacy.schema_version == STATISTICAL_VALIDATION_V1
    assert legacy.bootstrap_method is None
    assert legacy.hac_standard_error is None


def test_explicit_v2_evidence_round_trips_as_v2():
    evidence = run_statistical_validation(
        _result(_ar1_returns(phi=0.4, drift=0.0010, count=120)),
        candidate_count=2,
        periods_per_year=252,
        criteria=_lenient_criteria(),
    )

    parsed = parse_statistical_validation_evidence(evidence.model_dump())

    assert parsed.schema_version == STATISTICAL_VALIDATION_V2
    assert parsed.model_dump() == evidence.model_dump()
