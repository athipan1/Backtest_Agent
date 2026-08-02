from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from app.models import BacktestMetrics, BacktestRunResult, StandardAgentResponse, StrategyName
from app.multi_strategy import (
    MultiStrategyBacktestRequest,
    MultiStrategyCandidate,
    MultiStrategyResultItem,
    build_run_request,
    resolve_strategy_id,
    run_multi_strategy_backtest,
)
from app.risk_engine import run_backtest_with_risk
from app.security import require_backtest_api_key


router = APIRouter()


class WalkForwardStabilityCriteria(BaseModel):
    """Conservative nested out-of-sample gates."""

    train_bars: int = Field(default=126, ge=20)
    test_bars: int = Field(default=126, ge=20)
    step_bars: int = Field(default=126, ge=1)
    embargo_bars: int = Field(default=0, ge=0)
    allow_overlapping_test_windows: bool = False
    min_windows: int = Field(default=4, ge=1)
    min_window_trades: int = Field(default=1, ge=0)
    min_train_eligible_window_rate: float = Field(default=0.50, ge=0, le=1)
    min_profitable_window_rate: float = Field(default=0.60, ge=0, le=1)
    min_median_sharpe_ratio: float = 0.70
    min_median_profit_factor: float = Field(default=1.10, ge=0)
    max_drawdown_floor: float = Field(default=-0.20, ge=-1, le=0)
    max_kill_switch_events: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_window_independence(self) -> "WalkForwardStabilityCriteria":
        if (
            not self.allow_overlapping_test_windows
            and self.step_bars < self.test_bars
        ):
            raise ValueError(
                "step_bars must be greater than or equal to test_bars unless "
                "allow_overlapping_test_windows is true"
            )
        return self


class WalkForwardWindowResult(BaseModel):
    window: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_bars: int
    test_bars: int
    selected_strategy_id: str
    selected_strategy_name: str
    train_selection_eligible: bool
    train_selection_score: float
    train_metrics: BacktestMetrics
    profitable: bool
    metrics: BacktestMetrics
    warnings: List[str] = Field(default_factory=list)


class WalkForwardStabilityResult(BaseModel):
    status: Literal["completed", "insufficient_history"]
    selection_method: Literal[
        "fixed_candidate_oos",
        "nested_train_select_test_evaluate",
    ] = "fixed_candidate_oos"
    passed: bool
    stability_score: float
    available_bars: int
    evaluated_windows: int
    train_eligible_windows: int = 0
    train_eligible_window_rate: float = 0.0
    profitable_windows: int
    profitable_window_rate: float
    median_annualized_return: Optional[float] = None
    median_sharpe_ratio: Optional[float] = None
    median_profit_factor: Optional[float] = None
    worst_max_drawdown: Optional[float] = None
    total_kill_switch_events: int = 0
    overlapping_test_windows: bool = False
    embargo_bars: int = 0
    latest_selected_strategy_id: Optional[str] = None
    latest_selection_eligible: bool = False
    selection_counts: Dict[str, int] = Field(default_factory=dict)
    gates: Dict[str, bool] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    windows: List[WalkForwardWindowResult] = Field(default_factory=list)


class WalkForwardMultiStrategyRequest(MultiStrategyBacktestRequest):
    walk_forward_criteria: WalkForwardStabilityCriteria = Field(
        default_factory=WalkForwardStabilityCriteria
    )


class WalkForwardMultiStrategyResultItem(BaseModel):
    rank: int
    strategy_id: str
    name: str
    strategy: StrategyName
    fast_window: int
    slow_window: int
    effective_parameters: Dict[str, Any]
    full_period_eligible: bool
    eligible: bool
    gates: Dict[str, bool]
    disqualification_reasons: List[str] = Field(default_factory=list)
    score: float
    score_components: Dict[str, float]
    metrics: BacktestMetrics
    walk_forward: WalkForwardStabilityResult
    warnings: List[str] = Field(default_factory=list)


class WalkForwardMultiStrategyResult(BaseModel):
    symbol: str
    candidate_source: Literal["balanced_v1", "provided"]
    selection_status: Literal["eligible_strategy_found", "no_eligible_strategy"]
    selection_method: Literal["nested_train_select_test_evaluate"] = (
        "nested_train_select_test_evaluate"
    )
    selection_criteria: Any
    walk_forward_criteria: WalkForwardStabilityCriteria
    nested_walk_forward: WalkForwardStabilityResult
    evaluated_count: int
    eligible_count: int
    ranked_results: List[WalkForwardMultiStrategyResultItem]
    best_overall: Optional[WalkForwardMultiStrategyResultItem] = None
    best_eligible: Optional[WalkForwardMultiStrategyResultItem] = None
    selected_result: Optional[BacktestRunResult] = None
    warnings: List[str] = Field(default_factory=list)


def _bars_for_symbol(request: WalkForwardMultiStrategyRequest) -> list[Any]:
    symbol = request.symbols[0].upper()
    for key, bars in request.bars.items():
        if key.upper() == symbol:
            return sorted(bars, key=lambda bar: bar.timestamp)
    return []


def _window_slices(
    request: WalkForwardMultiStrategyRequest,
) -> list[tuple[list[Any], list[Any]]]:
    source = _bars_for_symbol(request)
    criteria = request.walk_forward_criteria
    windows: list[tuple[list[Any], list[Any]]] = []
    test_start = criteria.train_bars + criteria.embargo_bars
    while test_start + criteria.test_bars <= len(source):
        train_end = test_start - criteria.embargo_bars
        train_start = train_end - criteria.train_bars
        train_slice = source[train_start:train_end]
        test_slice = source[test_start : test_start + criteria.test_bars]
        windows.append((train_slice, test_slice))
        test_start += criteria.step_bars
    return windows


def _profit_factor_for_stability(metrics: BacktestMetrics) -> float:
    if metrics.profit_factor is not None:
        return metrics.profit_factor
    if metrics.gross_profit > 0 and metrics.gross_loss == 0:
        return 10.0
    return 0.0


def _median_optional(values: List[Optional[float]]) -> Optional[float]:
    available = [value for value in values if value is not None]
    if not available:
        return None
    return round(float(median(available)), 6)


def _stability_score(
    *,
    criteria: WalkForwardStabilityCriteria,
    evaluated_windows: int,
    train_eligible_window_rate: float,
    profitable_window_rate: float,
    median_sharpe_ratio: Optional[float],
    median_profit_factor: Optional[float],
    worst_max_drawdown: Optional[float],
) -> float:
    window_component = min(evaluated_windows / criteria.min_windows, 1.0)
    train_component = (
        1.0
        if criteria.min_train_eligible_window_rate == 0
        else min(
            train_eligible_window_rate / criteria.min_train_eligible_window_rate,
            1.0,
        )
    )
    profitable_component = (
        1.0
        if criteria.min_profitable_window_rate == 0
        else min(
            profitable_window_rate / criteria.min_profitable_window_rate,
            1.0,
        )
    )
    sharpe_component = max(
        0.0,
        min(((median_sharpe_ratio or -1.0) + 1.0) / 2.0, 1.0),
    )
    profit_factor_component = min((median_profit_factor or 0.0) / 2.0, 1.0)
    if worst_max_drawdown is None:
        drawdown_component = 0.0
    elif criteria.max_drawdown_floor == 0:
        drawdown_component = 1.0 if worst_max_drawdown >= 0 else 0.0
    else:
        drawdown_component = max(
            0.0,
            min(
                1.0 - abs(worst_max_drawdown) / abs(criteria.max_drawdown_floor),
                1.0,
            ),
        )
    return round(
        (
            window_component
            + train_component
            + profitable_component
            + sharpe_component
            + profit_factor_component
            + drawdown_component
        )
        / 6.0,
        6,
    )


def _summarize_windows(
    *,
    request: WalkForwardMultiStrategyRequest,
    windows: List[WalkForwardWindowResult],
    selection_method: Literal[
        "fixed_candidate_oos",
        "nested_train_select_test_evaluate",
    ],
) -> WalkForwardStabilityResult:
    criteria = request.walk_forward_criteria
    evaluated_windows = len(windows)
    train_eligible_windows = sum(
        1 for window in windows if window.train_selection_eligible
    )
    train_eligible_window_rate = (
        0.0
        if evaluated_windows == 0
        else train_eligible_windows / evaluated_windows
    )
    profitable_windows = sum(1 for window in windows if window.profitable)
    profitable_window_rate = (
        0.0
        if evaluated_windows == 0
        else profitable_windows / evaluated_windows
    )
    median_annualized_return = _median_optional(
        [window.metrics.annualized_return for window in windows]
    )
    median_sharpe_ratio = _median_optional(
        [window.metrics.sharpe_ratio for window in windows]
    )
    median_profit_factor = (
        round(
            float(
                median(
                    [
                        _profit_factor_for_stability(window.metrics)
                        for window in windows
                    ]
                )
            ),
            6,
        )
        if windows
        else None
    )
    worst_max_drawdown = (
        min(window.metrics.max_drawdown for window in windows)
        if windows
        else None
    )
    total_kill_switch_events = sum(
        window.metrics.kill_switch_events for window in windows
    )
    gates = {
        "window_count": evaluated_windows >= criteria.min_windows,
        "train_eligible_window_rate": (
            train_eligible_window_rate
            >= criteria.min_train_eligible_window_rate
        ),
        "profitable_window_rate": (
            profitable_window_rate >= criteria.min_profitable_window_rate
        ),
        "median_sharpe_ratio": (
            median_sharpe_ratio is not None
            and median_sharpe_ratio >= criteria.min_median_sharpe_ratio
        ),
        "median_profit_factor": (
            median_profit_factor is not None
            and median_profit_factor >= criteria.min_median_profit_factor
        ),
        "worst_max_drawdown": (
            worst_max_drawdown is not None
            and worst_max_drawdown >= criteria.max_drawdown_floor
        ),
        "kill_switch_safety": (
            total_kill_switch_events <= criteria.max_kill_switch_events
        ),
    }
    observations = {
        "window_count": evaluated_windows,
        "train_eligible_window_rate": round(train_eligible_window_rate, 6),
        "profitable_window_rate": round(profitable_window_rate, 6),
        "median_sharpe_ratio": median_sharpe_ratio,
        "median_profit_factor": median_profit_factor,
        "worst_max_drawdown": worst_max_drawdown,
        "kill_switch_safety": total_kill_switch_events,
    }
    reasons = [
        f"walk_forward_{name} gate failed (observed={observations[name]!r})"
        for name, passed in gates.items()
        if not passed
    ]
    status: Literal["completed", "insufficient_history"] = (
        "completed"
        if evaluated_windows >= criteria.min_windows
        else "insufficient_history"
    )
    counts = Counter(window.selected_strategy_id for window in windows)
    latest = windows[-1] if windows else None
    return WalkForwardStabilityResult(
        status=status,
        selection_method=selection_method,
        passed=all(gates.values()),
        stability_score=_stability_score(
            criteria=criteria,
            evaluated_windows=evaluated_windows,
            train_eligible_window_rate=train_eligible_window_rate,
            profitable_window_rate=profitable_window_rate,
            median_sharpe_ratio=median_sharpe_ratio,
            median_profit_factor=median_profit_factor,
            worst_max_drawdown=worst_max_drawdown,
        ),
        available_bars=len(_bars_for_symbol(request)),
        evaluated_windows=evaluated_windows,
        train_eligible_windows=train_eligible_windows,
        train_eligible_window_rate=round(train_eligible_window_rate, 6),
        profitable_windows=profitable_windows,
        profitable_window_rate=round(profitable_window_rate, 6),
        median_annualized_return=median_annualized_return,
        median_sharpe_ratio=median_sharpe_ratio,
        median_profit_factor=median_profit_factor,
        worst_max_drawdown=worst_max_drawdown,
        total_kill_switch_events=total_kill_switch_events,
        overlapping_test_windows=criteria.step_bars < criteria.test_bars,
        embargo_bars=criteria.embargo_bars,
        latest_selected_strategy_id=(
            latest.selected_strategy_id if latest is not None else None
        ),
        latest_selection_eligible=(
            latest.train_selection_eligible if latest is not None else False
        ),
        selection_counts=dict(sorted(counts.items())),
        gates=gates,
        reasons=reasons,
        windows=windows,
    )


def run_candidate_walk_forward_stability(
    *,
    request: WalkForwardMultiStrategyRequest,
    candidate: MultiStrategyCandidate,
) -> WalkForwardStabilityResult:
    symbol = request.symbols[0].upper()
    strategy_id = resolve_strategy_id(candidate, request)
    windows: List[WalkForwardWindowResult] = []

    for window_number, (train_slice, test_slice) in enumerate(
        _window_slices(request),
        start=1,
    ):
        train_request = build_run_request(candidate, request).model_copy(
            deep=True,
            update={
                "bars": {symbol: train_slice},
                "force_close_at_end": True,
            },
        )
        test_request = build_run_request(candidate, request).model_copy(
            deep=True,
            update={
                "bars": {symbol: test_slice},
                "force_close_at_end": True,
            },
        )
        train_result = run_backtest_with_risk(train_request)
        test_result = run_backtest_with_risk(test_request)
        profitable = (
            test_result.metrics.trade_count
            >= request.walk_forward_criteria.min_window_trades
            and test_result.metrics.return_pct > 0
        )
        windows.append(
            WalkForwardWindowResult(
                window=window_number,
                train_start=train_slice[0].timestamp.isoformat(),
                train_end=train_slice[-1].timestamp.isoformat(),
                test_start=test_slice[0].timestamp.isoformat(),
                test_end=test_slice[-1].timestamp.isoformat(),
                train_bars=len(train_slice),
                test_bars=len(test_slice),
                selected_strategy_id=strategy_id,
                selected_strategy_name=candidate.name,
                train_selection_eligible=True,
                train_selection_score=0.0,
                train_metrics=train_result.metrics,
                profitable=profitable,
                metrics=test_result.metrics,
                warnings=list(
                    dict.fromkeys(train_result.warnings + test_result.warnings)
                ),
            )
        )

    return _summarize_windows(
        request=request,
        windows=windows,
        selection_method="fixed_candidate_oos",
    )


def _candidate_by_strategy_id(
    request: WalkForwardMultiStrategyRequest,
) -> Dict[str, MultiStrategyCandidate]:
    return {
        resolve_strategy_id(candidate, request): candidate
        for candidate in request.candidates
    }


def run_nested_walk_forward_stability(
    request: WalkForwardMultiStrategyRequest,
) -> WalkForwardStabilityResult:
    """Select on each train slice, then evaluate only on its future test slice."""

    symbol = request.symbols[0].upper()
    candidates = _candidate_by_strategy_id(request)
    windows: List[WalkForwardWindowResult] = []

    for window_number, (train_slice, test_slice) in enumerate(
        _window_slices(request),
        start=1,
    ):
        train_request = request.model_copy(
            deep=True,
            update={
                "bars": {symbol: train_slice},
                "force_close_at_end": True,
            },
        )
        train_selection = run_multi_strategy_backtest(train_request)
        selected_item = (
            train_selection.best_eligible or train_selection.best_overall
        )
        if selected_item is None:
            continue
        candidate = candidates[selected_item.strategy_id]
        test_request = build_run_request(candidate, request).model_copy(
            deep=True,
            update={
                "bars": {symbol: test_slice},
                "force_close_at_end": True,
            },
        )
        test_result = run_backtest_with_risk(test_request)
        profitable = (
            test_result.metrics.trade_count
            >= request.walk_forward_criteria.min_window_trades
            and test_result.metrics.return_pct > 0
        )
        windows.append(
            WalkForwardWindowResult(
                window=window_number,
                train_start=train_slice[0].timestamp.isoformat(),
                train_end=train_slice[-1].timestamp.isoformat(),
                test_start=test_slice[0].timestamp.isoformat(),
                test_end=test_slice[-1].timestamp.isoformat(),
                train_bars=len(train_slice),
                test_bars=len(test_slice),
                selected_strategy_id=selected_item.strategy_id,
                selected_strategy_name=selected_item.name,
                train_selection_eligible=(
                    train_selection.best_eligible is not None
                ),
                train_selection_score=selected_item.score,
                train_metrics=selected_item.metrics,
                profitable=profitable,
                metrics=test_result.metrics,
                warnings=list(
                    dict.fromkeys(
                        selected_item.warnings + test_result.warnings
                    )
                ),
            )
        )

    return _summarize_windows(
        request=request,
        windows=windows,
        selection_method="nested_train_select_test_evaluate",
    )


def _walk_forward_item(
    *,
    base_item: MultiStrategyResultItem,
    stability: WalkForwardStabilityResult,
    promotion_eligible: bool,
    nested: WalkForwardStabilityResult,
) -> WalkForwardMultiStrategyResultItem:
    gates = {
        **{
            f"full_period_diagnostic_{name}": passed
            for name, passed in base_item.gates.items()
        },
        **{
            f"candidate_oos_{name}": passed
            for name, passed in stability.gates.items()
        },
        **{
            f"nested_oos_{name}": passed
            for name, passed in nested.gates.items()
        },
    }
    reasons = list(stability.reasons)
    if not promotion_eligible:
        reasons.append("not selected by the latest nested training window")
    components = dict(base_item.score_components)
    components["candidate_oos_stability"] = round(
        0.10 * stability.stability_score,
        6,
    )
    components["nested_oos_stability"] = round(
        0.20 * nested.stability_score,
        6,
    )
    return WalkForwardMultiStrategyResultItem(
        rank=0,
        strategy_id=base_item.strategy_id,
        name=base_item.name,
        strategy=base_item.strategy,
        fast_window=base_item.fast_window,
        slow_window=base_item.slow_window,
        effective_parameters=base_item.effective_parameters,
        full_period_eligible=base_item.eligible,
        eligible=promotion_eligible,
        gates=gates,
        disqualification_reasons=list(dict.fromkeys(reasons)),
        score=round(sum(components.values()), 6),
        score_components=components,
        metrics=base_item.metrics,
        walk_forward=stability,
        warnings=base_item.warnings,
    )


def _latest_training_slice(
    request: WalkForwardMultiStrategyRequest,
) -> list[Any]:
    windows = _window_slices(request)
    return windows[-1][0] if windows else []


def run_walk_forward_multi_strategy_backtest(
    request: WalkForwardMultiStrategyRequest,
) -> WalkForwardMultiStrategyResult:
    base_result = run_multi_strategy_backtest(request)
    candidates = _candidate_by_strategy_id(request)
    nested = run_nested_walk_forward_stability(request)
    selected_strategy_id = (
        nested.latest_selected_strategy_id
        if nested.passed and nested.latest_selection_eligible
        else None
    )

    items = [
        _walk_forward_item(
            base_item=base_item,
            stability=run_candidate_walk_forward_stability(
                request=request,
                candidate=candidates[base_item.strategy_id],
            ),
            promotion_eligible=(
                base_item.strategy_id == selected_strategy_id
            ),
            nested=nested,
        )
        for base_item in base_result.ranked_results
    ]
    items.sort(
        key=lambda item: (
            -int(item.eligible),
            -item.score,
            -item.walk_forward.stability_score,
            -item.metrics.return_pct,
            item.strategy_id,
        )
    )
    ranked = [
        item.model_copy(update={"rank": rank})
        for rank, item in enumerate(items, start=1)
    ]
    eligible = [item for item in ranked if item.eligible]
    best_overall = ranked[0] if ranked else None
    best_eligible = eligible[0] if eligible else None
    selected_result = None
    if best_eligible is not None:
        selected_candidate = candidates[best_eligible.strategy_id]
        latest_train = _latest_training_slice(request)
        symbol = request.symbols[0].upper()
        if latest_train:
            selected_result = run_backtest_with_risk(
                build_run_request(selected_candidate, request).model_copy(
                    deep=True,
                    update={
                        "bars": {symbol: latest_train},
                        "force_close_at_end": True,
                    },
                )
            )

    warnings = list(base_result.warnings)
    warnings.append(
        "Full-period metrics are diagnostic only; promotion is determined by "
        "nested train-selection and untouched future test windows."
    )
    if best_eligible is None:
        warnings.append(
            "No strategy passed nested out-of-sample gates and the latest "
            "training-window eligibility check; do not promote this symbol."
        )

    return WalkForwardMultiStrategyResult(
        symbol=base_result.symbol,
        candidate_source=base_result.candidate_source,
        selection_status=(
            "eligible_strategy_found"
            if best_eligible is not None
            else "no_eligible_strategy"
        ),
        selection_criteria=base_result.selection_criteria,
        walk_forward_criteria=request.walk_forward_criteria,
        nested_walk_forward=nested,
        evaluated_count=len(ranked),
        eligible_count=len(eligible),
        ranked_results=ranked,
        best_overall=best_overall,
        best_eligible=best_eligible,
        selected_result=selected_result,
        warnings=list(dict.fromkeys(warnings)),
    )


@router.post(
    "/backtest/multi-strategy/walk-forward",
    response_model=StandardAgentResponse[WalkForwardMultiStrategyResult],
    dependencies=[Depends(require_backtest_api_key)],
)
def backtest_multi_strategy_walk_forward(
    request: WalkForwardMultiStrategyRequest,
) -> StandardAgentResponse[WalkForwardMultiStrategyResult]:
    return StandardAgentResponse(
        status="success",
        data=run_walk_forward_multi_strategy_backtest(request),
    )
