from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from app.models import (
    BacktestCompareRequest,
    BacktestMetrics,
    BacktestRunRequest,
    BacktestRunResult,
    StandardAgentResponse,
    StrategyCandidate,
    StrategyName,
)
from app.risk_engine import run_backtest_with_risk


router = APIRouter()


class MultiStrategyCandidate(StrategyCandidate):
    """One exact strategy configuration evaluated by the selection endpoint."""

    strategy_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class StrategySelectionCriteria(BaseModel):
    """Safety-first gates required before a strategy can be selected."""

    min_trades: int = Field(default=10, ge=0)
    min_annualized_return: float = 0.05
    min_sharpe_ratio: float = 0.80
    min_profit_factor: float = Field(default=1.20, ge=0)
    max_drawdown_floor: float = Field(default=-0.20, ge=-1, le=0)
    min_excess_return: float = 0.0
    max_kill_switch_events: int = Field(default=0, ge=0)


def default_multi_strategy_candidates() -> List[MultiStrategyCandidate]:
    """Return the deterministic balanced-v1 strategy suite."""

    return [
        MultiStrategyCandidate(
            strategy_id="sma-crossover-balanced-v1",
            name="SMA crossover 10/30",
            strategy="sma_crossover",
            fast_window=10,
            slow_window=30,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-balanced-v1",
            name="Trend following 20/50",
            strategy="trend_following",
            fast_window=20,
            slow_window=50,
        ),
        MultiStrategyCandidate(
            strategy_id="mean-reversion-balanced-v1",
            name="Mean reversion 5/20",
            strategy="mean_reversion",
            fast_window=5,
            slow_window=20,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-balanced-v1",
            name="Breakout 5/20",
            strategy="breakout",
            fast_window=5,
            slow_window=20,
        ),
    ]


class MultiStrategyBacktestRequest(BacktestCompareRequest):
    """Compare multiple strategies for exactly one symbol."""

    symbols: List[str] = Field(min_length=1, max_length=1)
    candidates: List[MultiStrategyCandidate] = Field(
        default_factory=default_multi_strategy_candidates,
        min_length=1,
        max_length=25,
    )
    selection_criteria: StrategySelectionCriteria = Field(
        default_factory=StrategySelectionCriteria
    )

    @model_validator(mode="after")
    def validate_candidate_identities(self) -> "MultiStrategyBacktestRequest":
        resolved = [resolve_strategy_id(candidate, self) for candidate in self.candidates]
        duplicates = sorted(
            strategy_id
            for strategy_id in set(resolved)
            if resolved.count(strategy_id) > 1
        )
        if duplicates:
            raise ValueError(
                "duplicate strategy identities are not allowed: "
                + ", ".join(duplicates)
            )
        return self


class MultiStrategyResultItem(BaseModel):
    rank: int
    strategy_id: str
    name: str
    strategy: StrategyName
    fast_window: int
    slow_window: int
    effective_parameters: Dict[str, Any]
    eligible: bool
    gates: Dict[str, bool]
    disqualification_reasons: List[str] = Field(default_factory=list)
    score: float
    score_components: Dict[str, float]
    metrics: BacktestMetrics
    warnings: List[str] = Field(default_factory=list)


class MultiStrategyBacktestResult(BaseModel):
    symbol: str
    candidate_source: Literal["balanced_v1", "provided"]
    selection_status: Literal["eligible_strategy_found", "no_eligible_strategy"]
    selection_criteria: StrategySelectionCriteria
    evaluated_count: int
    eligible_count: int
    ranked_results: List[MultiStrategyResultItem]
    best_overall: Optional[MultiStrategyResultItem] = None
    best_eligible: Optional[MultiStrategyResultItem] = None
    selected_result: Optional[BacktestRunResult] = None
    warnings: List[str] = Field(default_factory=list)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._:-]+", "-", value.strip().lower())
    return normalized.strip("-") or "strategy"


def _effective_value(candidate_value: Optional[float], request_value: float) -> float:
    return request_value if candidate_value is None else candidate_value


def effective_parameters(
    candidate: MultiStrategyCandidate,
    request: MultiStrategyBacktestRequest,
) -> Dict[str, Any]:
    return {
        "strategy": candidate.strategy,
        "fast_window": candidate.fast_window,
        "slow_window": candidate.slow_window,
        "risk_per_trade": request.risk_per_trade,
        "max_position_pct": _effective_value(
            candidate.max_position_pct,
            request.max_position_pct,
        ),
        "stop_loss_pct": _effective_value(
            candidate.stop_loss_pct,
            request.stop_loss_pct,
        ),
        "reward_risk_ratio": _effective_value(
            candidate.reward_risk_ratio,
            request.reward_risk_ratio,
        ),
        "fee_bps": _effective_value(candidate.fee_bps, request.fee_bps),
        "slippage_bps": _effective_value(
            candidate.slippage_bps,
            request.slippage_bps,
        ),
        "use_risk_agent": request.use_risk_agent,
        "force_close_at_end": request.force_close_at_end,
        "max_total_exposure_pct": request.max_total_exposure_pct,
        "max_open_positions": request.max_open_positions,
        "cash_reserve_pct": request.cash_reserve_pct,
        "max_new_positions_per_bar": request.max_new_positions_per_bar,
        "periods_per_year": request.periods_per_year,
        "annual_risk_free_rate": request.annual_risk_free_rate,
        "max_volume_participation_pct": request.max_volume_participation_pct,
        "market_impact_bps": request.market_impact_bps,
    }


def resolve_strategy_id(
    candidate: MultiStrategyCandidate,
    request: MultiStrategyBacktestRequest,
) -> str:
    if candidate.strategy_id:
        return candidate.strategy_id

    parameters = effective_parameters(candidate, request)
    return _slug(
        "-".join(
            [
                candidate.strategy,
                f"f{candidate.fast_window}",
                f"s{candidate.slow_window}",
                f"sl{parameters['stop_loss_pct']:.4f}",
                f"rr{parameters['reward_risk_ratio']:.3f}",
            ]
        )
    )


def build_run_request(
    candidate: MultiStrategyCandidate,
    request: MultiStrategyBacktestRequest,
) -> BacktestRunRequest:
    parameters = effective_parameters(candidate, request)
    return BacktestRunRequest(
        symbols=request.symbols,
        initial_equity=request.initial_equity,
        bars=request.bars,
        strategy=candidate.strategy,
        fast_window=candidate.fast_window,
        slow_window=candidate.slow_window,
        risk_per_trade=request.risk_per_trade,
        max_position_pct=parameters["max_position_pct"],
        stop_loss_pct=parameters["stop_loss_pct"],
        reward_risk_ratio=parameters["reward_risk_ratio"],
        fee_bps=parameters["fee_bps"],
        slippage_bps=parameters["slippage_bps"],
        use_risk_agent=request.use_risk_agent,
        emergency_halt=request.emergency_halt,
        max_trades_per_day=request.max_trades_per_day,
        force_close_at_end=request.force_close_at_end,
        max_total_exposure_pct=request.max_total_exposure_pct,
        max_open_positions=request.max_open_positions,
        cash_reserve_pct=request.cash_reserve_pct,
        max_new_positions_per_bar=request.max_new_positions_per_bar,
        periods_per_year=request.periods_per_year,
        annual_risk_free_rate=request.annual_risk_free_rate,
        max_volume_participation_pct=request.max_volume_participation_pct,
        market_impact_bps=request.market_impact_bps,
    )


def evaluate_selection_gates(
    metrics: BacktestMetrics,
    criteria: StrategySelectionCriteria,
) -> tuple[Dict[str, bool], List[str]]:
    gates = {
        "trade_count": metrics.trade_count >= criteria.min_trades,
        "annualized_return": (
            metrics.annualized_return is not None
            and metrics.annualized_return >= criteria.min_annualized_return
        ),
        "sharpe_ratio": (
            metrics.sharpe_ratio is not None
            and metrics.sharpe_ratio >= criteria.min_sharpe_ratio
        ),
        "profit_factor": (
            metrics.profit_factor is not None
            and metrics.profit_factor >= criteria.min_profit_factor
        ),
        "max_drawdown": metrics.max_drawdown >= criteria.max_drawdown_floor,
        "excess_return": (
            metrics.excess_return_pct is not None
            and metrics.excess_return_pct >= criteria.min_excess_return
        ),
        "kill_switch_safety": (
            metrics.kill_switch_events <= criteria.max_kill_switch_events
        ),
    }

    observations = {
        "trade_count": metrics.trade_count,
        "annualized_return": metrics.annualized_return,
        "sharpe_ratio": metrics.sharpe_ratio,
        "profit_factor": metrics.profit_factor,
        "max_drawdown": metrics.max_drawdown,
        "excess_return": metrics.excess_return_pct,
        "kill_switch_safety": metrics.kill_switch_events,
    }
    reasons = [
        f"{name} gate failed (observed={observations[name]!r})"
        for name, passed in gates.items()
        if not passed
    ]
    return gates, reasons


def _bounded(value: Optional[float], lower: float, upper: float) -> float:
    if value is None:
        return lower
    return max(lower, min(upper, value))


def score_components(metrics: BacktestMetrics) -> Dict[str, float]:
    """Build a deterministic, explainable risk-adjusted ranking score."""

    components = {
        "total_return": 0.20 * _bounded(metrics.return_pct, -1.0, 1.0),
        "annualized_return": 0.20
        * _bounded(metrics.annualized_return, -1.0, 1.0),
        "sharpe_ratio": 0.20
        * (_bounded(metrics.sharpe_ratio, -3.0, 3.0) / 3.0),
        "sortino_ratio": 0.10
        * (_bounded(metrics.sortino_ratio, -3.0, 3.0) / 3.0),
        "profit_factor": 0.15
        * _bounded(
            ((metrics.profit_factor or 0.0) - 1.0) / 2.0,
            -0.5,
            1.0,
        ),
        "drawdown": 0.10 * _bounded(metrics.max_drawdown, -1.0, 0.0),
        "excess_return": 0.10
        * _bounded(metrics.excess_return_pct, -1.0, 1.0),
        "trade_activity": 0.05 * min(metrics.trade_count / 10.0, 1.0),
        "risk_rejection_penalty": -min(metrics.risk_rejections * 0.001, 0.05),
        "kill_switch_penalty": -min(metrics.kill_switch_events * 0.25, 1.0),
    }
    return {name: round(value, 6) for name, value in components.items()}


def run_multi_strategy_backtest(
    request: MultiStrategyBacktestRequest,
) -> MultiStrategyBacktestResult:
    evaluated: List[tuple[MultiStrategyResultItem, BacktestRunResult]] = []

    for candidate in request.candidates:
        run_request = build_run_request(candidate, request)
        result = run_backtest_with_risk(run_request)
        gates, reasons = evaluate_selection_gates(
            result.metrics,
            request.selection_criteria,
        )
        components = score_components(result.metrics)
        strategy_id = resolve_strategy_id(candidate, request)
        evaluated.append(
            (
                MultiStrategyResultItem(
                    rank=0,
                    strategy_id=strategy_id,
                    name=candidate.name,
                    strategy=candidate.strategy,
                    fast_window=candidate.fast_window,
                    slow_window=candidate.slow_window,
                    effective_parameters=effective_parameters(candidate, request),
                    eligible=all(gates.values()),
                    gates=gates,
                    disqualification_reasons=reasons,
                    score=round(sum(components.values()), 6),
                    score_components=components,
                    metrics=result.metrics,
                    warnings=result.warnings,
                ),
                result,
            )
        )

    evaluated.sort(
        key=lambda pair: (
            -int(pair[0].eligible),
            -pair[0].score,
            -pair[0].metrics.return_pct,
            pair[0].strategy_id,
        )
    )

    ranked_pairs = [
        (item.model_copy(update={"rank": rank}), result)
        for rank, (item, result) in enumerate(evaluated, start=1)
    ]
    ranked = [item for item, _ in ranked_pairs]
    best_overall = ranked[0] if ranked else None
    eligible_pairs = [pair for pair in ranked_pairs if pair[0].eligible]
    best_eligible = eligible_pairs[0][0] if eligible_pairs else None
    selected_result = eligible_pairs[0][1] if eligible_pairs else None
    warnings: List[str] = []
    if not best_eligible:
        warnings.append(
            "No strategy passed every selection gate; do not promote this symbol "
            "to Risk or Execution."
        )

    candidate_source: Literal["balanced_v1", "provided"] = (
        "provided" if "candidates" in request.model_fields_set else "balanced_v1"
    )
    return MultiStrategyBacktestResult(
        symbol=request.symbols[0].upper(),
        candidate_source=candidate_source,
        selection_status=(
            "eligible_strategy_found"
            if best_eligible is not None
            else "no_eligible_strategy"
        ),
        selection_criteria=request.selection_criteria,
        evaluated_count=len(ranked),
        eligible_count=len(eligible_pairs),
        ranked_results=ranked,
        best_overall=best_overall,
        best_eligible=best_eligible,
        selected_result=selected_result,
        warnings=warnings,
    )


@router.post(
    "/backtest/multi-strategy",
    response_model=StandardAgentResponse[MultiStrategyBacktestResult],
)
def backtest_multi_strategy(
    request: MultiStrategyBacktestRequest,
) -> StandardAgentResponse[MultiStrategyBacktestResult]:
    return StandardAgentResponse(
        status="success",
        data=run_multi_strategy_backtest(request),
    )
