from __future__ import annotations

import math
import os
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.execution_policy import (
    ExecutionRealismPolicy,
    execution_policy_context,
    resolve_execution_policy,
)
from app.models import (
    BacktestRobustnessRequest,
    BacktestRunRequest,
    BacktestRunResult,
)
from app.robustness import run_robustness_analysis
from app.risk_engine import run_backtest_with_risk


class PromotionRobustnessCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    min_parameter_scenarios: int = Field(default=4, ge=1)
    min_parameter_profitable_rate: float = Field(default=0.50, ge=0, le=1)
    min_scenario_pass_rate: float = Field(default=0.80, ge=0, le=1)
    min_stress_return_pct: float = Field(default=-0.10, ge=-1, le=1)
    max_stress_drawdown_floor: float = Field(default=-0.30, ge=-1, le=0)
    catastrophic_loss_floor: float = Field(default=-0.50, ge=-1, lt=0)
    max_monte_carlo_loss_probability: float = Field(default=0.50, ge=0, le=1)
    min_monte_carlo_p05_equity_ratio: float = Field(default=0.80, ge=0, le=2)
    max_monte_carlo_p05_drawdown_floor: float = Field(default=-0.35, ge=-1, le=0)
    monte_carlo_simulations: int = Field(default=500, ge=100, le=10000)
    monte_carlo_seed: int = 42
    min_monte_carlo_trades: int = Field(default=5, ge=2)
    sensitivity_fast_delta: int = Field(default=1, ge=1, le=50)
    sensitivity_slow_delta: int = Field(default=1, ge=1, le=50)


class StressScenarioEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: Literal["fee_stress", "spread_stress", "slippage_stress", "liquidity_stress"]
    passed: bool
    return_pct: float
    max_drawdown: float
    trade_count: int
    kill_switch_events: int
    final_equity: float
    assumptions: Dict[str, Any] = Field(default_factory=dict)
    failure_reasons: list[str] = Field(default_factory=list)


class PromotionRobustnessEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    status: Literal["completed"] = "completed"
    passed: bool
    scenario_pass_rate: float
    catastrophic_loss: bool
    gates: Dict[str, bool]
    criteria: PromotionRobustnessCriteria
    parameter_sensitivity: Dict[str, Any]
    monte_carlo: Dict[str, Any]
    stress_scenarios: list[StressScenarioEvidence]
    failure_reasons: list[str] = Field(default_factory=list)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def promotion_robustness_criteria_from_env() -> PromotionRobustnessCriteria:
    return PromotionRobustnessCriteria(
        min_parameter_scenarios=_int_env(
            "BACKTEST_PROMOTION_MIN_PARAMETER_SCENARIOS", 4
        ),
        min_parameter_profitable_rate=_float_env(
            "BACKTEST_PROMOTION_MIN_PARAMETER_PROFITABLE_RATE", 0.50
        ),
        min_scenario_pass_rate=_float_env(
            "BACKTEST_PROMOTION_MIN_ROBUSTNESS_PASS_RATE", 0.80
        ),
        min_stress_return_pct=_float_env(
            "BACKTEST_PROMOTION_MIN_STRESS_RETURN_PCT", -0.10
        ),
        max_stress_drawdown_floor=_float_env(
            "BACKTEST_PROMOTION_MAX_STRESS_DRAWDOWN_FLOOR", -0.30
        ),
        catastrophic_loss_floor=_float_env(
            "BACKTEST_PROMOTION_CATASTROPHIC_LOSS_FLOOR", -0.50
        ),
        max_monte_carlo_loss_probability=_float_env(
            "BACKTEST_PROMOTION_MAX_MONTE_CARLO_LOSS_PROBABILITY", 0.50
        ),
        min_monte_carlo_p05_equity_ratio=_float_env(
            "BACKTEST_PROMOTION_MIN_MONTE_CARLO_P05_EQUITY_RATIO", 0.80
        ),
        max_monte_carlo_p05_drawdown_floor=_float_env(
            "BACKTEST_PROMOTION_MAX_MONTE_CARLO_P05_DRAWDOWN_FLOOR", -0.35
        ),
        monte_carlo_simulations=_int_env(
            "BACKTEST_PROMOTION_MONTE_CARLO_SIMULATIONS", 500
        ),
        monte_carlo_seed=_int_env(
            "BACKTEST_PROMOTION_MONTE_CARLO_SEED", 42
        ),
        min_monte_carlo_trades=_int_env(
            "BACKTEST_PROMOTION_MIN_MONTE_CARLO_TRADES", 5
        ),
        sensitivity_fast_delta=_int_env(
            "BACKTEST_PROMOTION_SENSITIVITY_FAST_DELTA", 1
        ),
        sensitivity_slow_delta=_int_env(
            "BACKTEST_PROMOTION_SENSITIVITY_SLOW_DELTA", 1
        ),
    )


def _finite_metrics(result: BacktestRunResult) -> bool:
    values = result.metrics.model_dump().values()
    return all(
        value is None
        or isinstance(value, (bool, int))
        or (isinstance(value, float) and math.isfinite(value))
        for value in values
    )


def _scenario_evidence(
    *,
    name: Literal["fee_stress", "spread_stress", "slippage_stress", "liquidity_stress"],
    result: BacktestRunResult,
    assumptions: Dict[str, Any],
    criteria: PromotionRobustnessCriteria,
) -> StressScenarioEvidence:
    reasons: list[str] = []
    metrics = result.metrics
    if not _finite_metrics(result):
        reasons.append("invalid_metrics")
    if metrics.return_pct < criteria.min_stress_return_pct:
        reasons.append("stress_return_below_floor")
    if metrics.max_drawdown < criteria.max_stress_drawdown_floor:
        reasons.append("stress_drawdown_below_floor")
    if metrics.kill_switch_events != 0:
        reasons.append("kill_switch_event")
    if metrics.final_equity <= 0:
        reasons.append("equity_depleted")
    return StressScenarioEvidence(
        name=name,
        passed=not reasons,
        return_pct=metrics.return_pct,
        max_drawdown=metrics.max_drawdown,
        trade_count=metrics.trade_count,
        kill_switch_events=metrics.kill_switch_events,
        final_equity=metrics.final_equity,
        assumptions=assumptions,
        failure_reasons=reasons,
    )


def _run_request(
    request: BacktestRunRequest,
    *,
    updates: Optional[Dict[str, Any]] = None,
    policy: Optional[ExecutionRealismPolicy] = None,
) -> BacktestRunResult:
    scenario = request.model_copy(
        deep=True,
        update={"force_close_at_end": True, **(updates or {})},
    )
    if policy is None:
        return run_backtest_with_risk(scenario)
    with execution_policy_context(policy):
        return run_backtest_with_risk(scenario)


def run_promotion_robustness(
    request: BacktestRunRequest,
    *,
    criteria: Optional[PromotionRobustnessCriteria] = None,
) -> PromotionRobustnessEvidence:
    resolved = criteria or promotion_robustness_criteria_from_env()
    baseline_policy = resolve_execution_policy(request)
    robustness_request = BacktestRobustnessRequest(
        **request.model_dump(),
        force_close_at_end=True,
        monte_carlo_simulations=resolved.monte_carlo_simulations,
        monte_carlo_seed=resolved.monte_carlo_seed,
        min_monte_carlo_trades=resolved.min_monte_carlo_trades,
        sensitivity_fast_delta=resolved.sensitivity_fast_delta,
        sensitivity_slow_delta=resolved.sensitivity_slow_delta,
    )
    core = run_robustness_analysis(robustness_request)

    fee_bps = max(request.fee_bps * 2.0, request.fee_bps + 5.0, 5.0)
    slippage_bps = max(
        request.slippage_bps * 2.0,
        request.slippage_bps + 5.0,
        5.0,
    )
    spread_bps = max(
        baseline_policy.bid_ask_spread_bps * 2.0,
        baseline_policy.bid_ask_spread_bps + 5.0,
        5.0,
    )
    liquidity_rate = min(request.max_volume_participation_pct, 0.25)

    stress_scenarios = [
        _scenario_evidence(
            name="fee_stress",
            result=_run_request(request, updates={"fee_bps": fee_bps}),
            assumptions={"fee_bps": fee_bps},
            criteria=resolved,
        ),
        _scenario_evidence(
            name="spread_stress",
            result=_run_request(
                request,
                policy=baseline_policy.model_copy(
                    update={"bid_ask_spread_bps": spread_bps}
                ),
            ),
            assumptions={"bid_ask_spread_bps": spread_bps},
            criteria=resolved,
        ),
        _scenario_evidence(
            name="slippage_stress",
            result=_run_request(
                request,
                updates={"slippage_bps": slippage_bps},
            ),
            assumptions={"slippage_bps": slippage_bps},
            criteria=resolved,
        ),
        _scenario_evidence(
            name="liquidity_stress",
            result=_run_request(
                request,
                updates={"max_volume_participation_pct": liquidity_rate},
            ),
            assumptions={"max_volume_participation_pct": liquidity_rate},
            criteria=resolved,
        ),
    ]

    sensitivity = core.sensitivity
    parameter_gate = (
        sensitivity.scenario_count >= resolved.min_parameter_scenarios
        and sensitivity.profitable_scenario_pct is not None
        and sensitivity.profitable_scenario_pct
        >= resolved.min_parameter_profitable_rate
        and sensitivity.worst_return_pct is not None
        and sensitivity.worst_return_pct >= resolved.min_stress_return_pct
        and all(_finite_metrics(item.metrics) for item in sensitivity.scenarios)
    )

    monte_carlo = core.monte_carlo
    drawdown_gate = (
        monte_carlo.status == "completed"
        and monte_carlo.probability_of_loss is not None
        and monte_carlo.probability_of_loss
        <= resolved.max_monte_carlo_loss_probability
        and monte_carlo.p05_final_equity is not None
        and monte_carlo.p05_final_equity
        >= request.initial_equity * resolved.min_monte_carlo_p05_equity_ratio
        and monte_carlo.p05_max_drawdown is not None
        and monte_carlo.p05_max_drawdown
        >= resolved.max_monte_carlo_p05_drawdown_floor
    )

    stress_gate_by_name = {item.name: item.passed for item in stress_scenarios}
    scenario_gates = {
        "parameter_perturbation": parameter_gate,
        "fee_stress": stress_gate_by_name["fee_stress"],
        "spread_stress": stress_gate_by_name["spread_stress"],
        "slippage_stress": stress_gate_by_name["slippage_stress"],
        "liquidity_stress": stress_gate_by_name["liquidity_stress"],
        "drawdown_stress": drawdown_gate,
    }
    passed_scenarios = sum(scenario_gates.values())
    scenario_pass_rate = passed_scenarios / len(scenario_gates)

    all_returns = [
        core.baseline.metrics.return_pct,
        *[item.return_pct for item in stress_scenarios],
        *[
            item.metrics.return_pct
            for item in sensitivity.scenarios
        ],
    ]
    catastrophic_loss = any(
        value < resolved.catastrophic_loss_floor for value in all_returns
    )
    finite_metrics = (
        _finite_metrics(core.baseline)
        and all(_finite_metrics(item.metrics) for item in sensitivity.scenarios)
        and all(math.isfinite(item.return_pct) for item in stress_scenarios)
    )
    gates = {
        **scenario_gates,
        "minimum_scenario_pass_rate": (
            scenario_pass_rate >= resolved.min_scenario_pass_rate
        ),
        "no_catastrophic_loss": not catastrophic_loss,
        "finite_metrics": finite_metrics,
    }
    reasons = sorted(name for name, passed in gates.items() if not passed)
    return PromotionRobustnessEvidence(
        passed=all(gates.values()),
        scenario_pass_rate=round(scenario_pass_rate, 6),
        catastrophic_loss=catastrophic_loss,
        gates=gates,
        criteria=resolved,
        parameter_sensitivity=sensitivity.model_dump(mode="json"),
        monte_carlo=monte_carlo.model_dump(mode="json"),
        stress_scenarios=stress_scenarios,
        failure_reasons=reasons,
    )
