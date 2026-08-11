from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import hourly_promotion_runner as hourly
from app.statistical_validation import STATISTICAL_VALIDATION_V1, STATISTICAL_VALIDATION_V2


class _Dumpable:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, mode="python"):
        return self.payload


def test_hourly_statistical_config_prefers_phase3_bootstrap_environment(monkeypatch):
    monkeypatch.setenv("BACKTEST_BOOTSTRAP_METHOD", "moving_block")
    monkeypatch.setenv("BACKTEST_BOOTSTRAP_BLOCK_SIZE", "12")
    monkeypatch.setenv("BACKTEST_BOOTSTRAP_SIMULATIONS", "700")
    monkeypatch.setenv("BACKTEST_BOOTSTRAP_CONFIDENCE", "0.975")
    monkeypatch.setenv("BACKTEST_STATISTICAL_BOOTSTRAP_SIMULATIONS", "111")
    monkeypatch.setenv("BACKTEST_STATISTICAL_BOOTSTRAP_CONFIDENCE", "0.80")
    monkeypatch.setenv("BACKTEST_STATISTICAL_MIN_HAC_CONFIDENCE", "0.96")

    criteria = hourly._statistical_criteria()

    assert criteria["bootstrap_method"] == "moving_block"
    assert criteria["bootstrap_block_size"] == 12
    assert criteria["bootstrap_simulations"] == 700
    assert criteria["bootstrap_confidence"] == 0.975
    assert criteria["min_hac_mean_positive_probability"] == 0.96


def test_hourly_statistical_config_keeps_old_bootstrap_env_as_fallback(monkeypatch):
    monkeypatch.delenv("BACKTEST_BOOTSTRAP_SIMULATIONS", raising=False)
    monkeypatch.delenv("BACKTEST_BOOTSTRAP_CONFIDENCE", raising=False)
    monkeypatch.setenv("BACKTEST_STATISTICAL_BOOTSTRAP_SIMULATIONS", "333")
    monkeypatch.setenv("BACKTEST_STATISTICAL_BOOTSTRAP_CONFIDENCE", "0.90")

    criteria = hourly._statistical_criteria()

    assert criteria["bootstrap_method"] == "stationary"
    assert criteria["bootstrap_block_size"] == 10
    assert criteria["bootstrap_simulations"] == 333
    assert criteria["bootstrap_confidence"] == 0.90


def _selection():
    nested = {
        "selection_method": hourly.SELECTION_METHOD,
        "status": "completed",
        "passed": True,
        "latest_selected_strategy_id": "strategy-a",
        "latest_selection_eligible": True,
        "overlapping_test_windows": False,
        "train_eligible_window_rate": 1.0,
        "eligible_selection_rate": 1.0,
        "abstention_rate": 0.0,
        "capital_deployed_rate": 1.0,
        "trade_windows": 4,
        "no_trade_windows": 0,
        "gates": {
            "max_abstention_rate": True,
            "eligible_selection_rate": True,
        },
    }
    walk_forward_criteria = {
        "min_eligible_selection_rate": 0.5,
        "max_abstention_rate": 0.5,
    }
    return SimpleNamespace(
        best_eligible=SimpleNamespace(strategy_id="strategy-a"),
        nested_walk_forward=_Dumpable(nested),
        walk_forward_criteria=_Dumpable(walk_forward_criteria),
    )


def _statistical(version: str):
    return _Dumpable(
        {
            "schema_version": version,
            "status": "completed",
            "passed": True,
            "gates": {
                "observation_count": True,
                "trade_count": True,
                "adjusted_p_value": True,
                "probabilistic_sharpe_ratio": True,
                "deflated_sharpe_probability": True,
                "bootstrap_lower_bound": True,
                "block_bootstrap_lower_bound": True,
                "hac_mean_confidence": True,
                "time_series_bootstrap_authority": True,
            },
        }
    )


def _robustness():
    return _Dumpable(
        {
            "status": "completed",
            "passed": True,
            "criteria": {"min_scenario_pass_rate": 0.8},
            "failure_reasons": [],
        }
    )


def _criteria():
    return _Dumpable({"enabled": True, "bootstrap_method": "stationary"})


def test_new_production_promotion_rejects_statistical_v1_authority():
    with pytest.raises(RuntimeError, match="statistical-validation.v2"):
        hourly._pre_holdout_metadata(
            _selection(),
            _statistical(STATISTICAL_VALIDATION_V1),
            _robustness(),
            statistical_criteria=_criteria(),
        )


def test_pre_holdout_gate_accepts_complete_statistical_v2_authority():
    metadata = hourly._pre_holdout_metadata(
        _selection(),
        _statistical(STATISTICAL_VALIDATION_V2),
        _robustness(),
        statistical_criteria=_criteria(),
    )

    assert metadata["statistical_schema_version"] == STATISTICAL_VALIDATION_V2
    assert metadata["promotion_gates"]["statistical_validation_v2"] is True


def test_run_identity_changes_with_statistical_schema_version():
    base = {
        "evidence_version": 3,
        "walk_forward_criteria": {"train_bars": 126},
        "statistical_criteria": {"bootstrap_method": "stationary"},
        "robustness_validation": {"criteria": {"min_scenario_pass_rate": 0.8}},
        "final_holdout_criteria": {"enabled": True, "bars": 252},
        "sealed_holdout": {"dataset_fingerprint": "h" * 64},
    }
    v1 = {**base, "statistical_schema_version": STATISTICAL_VALIDATION_V1}
    v2 = {**base, "statistical_schema_version": STATISTICAL_VALIDATION_V2}
    common = {
        "symbol": "AAPL",
        "strategy_id": "strategy-a",
        "fingerprint": "f" * 64,
        "research_fingerprint": "r" * 64,
        "effective_parameters": {"fast_window": 10, "slow_window": 30},
        "timeframe": "1d",
    }

    assert hourly._run_id(**common, promotion_metadata=v1) != hourly._run_id(
        **common,
        promotion_metadata=v2,
    )
