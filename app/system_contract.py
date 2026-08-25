from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from app.multi_strategy import router as multi_strategy_router
from app.multi_strategy_walk_forward import router as multi_strategy_walk_forward_router
from app.observability import METRICS, current_correlation_id
from app.readiness import readiness_snapshot
from app.strategy_bucket_candidate_policy import (
    strategy_bucket_compatibility_contract,
)


BACKTEST_AGENT_TYPE = "backtest-agent"
BACKTEST_AGENT_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"

router = APIRouter()
router.include_router(multi_strategy_router)
router.include_router(multi_strategy_walk_forward_router)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def contract_response(
    *,
    status: str,
    data: Dict[str, Any] | None = None,
    metadata: Dict[str, Any] | None = None,
    error: Dict[str, Any] | None = None,
    confidence_score: float | None = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "agent_type": BACKTEST_AGENT_TYPE,
        "version": BACKTEST_AGENT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "timestamp": utc_timestamp(),
        "correlation_id": current_correlation_id(),
        "data": data,
        "metadata": metadata or {},
        "error": error,
        "confidence_score": confidence_score,
    }


@router.get("/version")
def version() -> Dict[str, Any]:
    return contract_response(
        status="success",
        data={
            "agent_type": BACKTEST_AGENT_TYPE,
            "version": BACKTEST_AGENT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "api_contract": "multi-agent-trading-api-contract",
        },
        metadata={
            "required_operational_endpoints": [
                "/health",
                "/ready",
                "/version",
                "/metrics",
            ],
        },
    )


@router.get("/ready")
def ready(response: Response) -> Dict[str, Any]:
    snapshot = readiness_snapshot()
    is_ready = bool(snapshot["ready"])
    if not is_ready:
        response.status_code = 503
    return contract_response(
        status="success" if is_ready else "error",
        data={
            "ready": is_ready,
            "environment": snapshot["environment"],
            "publishing_required": snapshot["publishing_required"],
            "run_endpoint": "/backtest/run",
            "compare_endpoint": "/backtest/compare",
            "multi_strategy_endpoint": "/backtest/multi-strategy",
            "multi_strategy_walk_forward_endpoint": (
                "/backtest/multi-strategy/walk-forward"
            ),
            "walk_forward_endpoint": "/backtest/walk-forward",
            "robustness_endpoint": "/backtest/robustness",
            "report_endpoint": "/backtest/report",
            "metrics_endpoint": "/metrics",
            "supported_strategies": [
                "sma_crossover",
                "trend_following",
                "mean_reversion",
                "breakout",
            ],
            "multi_strategy_profile": "balanced_v1",
            "strategy_bucket_compatibility": strategy_bucket_compatibility_contract(),
            "multi_strategy_selection": {
                "exact_symbol_only": True,
                "returns_best_eligible": True,
                "safety_gated": True,
                "statistical_gates": True,
                "multiple_testing_adjustment": "bonferroni",
                "probabilistic_sharpe": True,
                "deflated_sharpe": True,
                "bootstrap_confidence_interval": True,
            },
            "multi_strategy_walk_forward": {
                "nested_train_selection": True,
                "untouched_future_test_windows": True,
                "default_train_bars": 126,
                "default_test_bars": 126,
                "default_step_bars": 126,
                "default_embargo_bars": 0,
                "default_min_windows": 4,
                "overlapping_test_windows_by_default": False,
                "full_period_metrics_are_diagnostic_only": True,
            },
        },
        metadata={
            "contract_source": "backtest-agent-runtime-contract",
            "readiness_checks": snapshot["checks"],
        },
        error=(
            None
            if is_ready
            else {
                "code": "service_not_ready",
                "message": "One or more critical runtime checks failed.",
            }
        ),
        confidence_score=1.0 if is_ready else 0.0,
    )


@router.get("/metrics", response_class=PlainTextResponse)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(
        METRICS.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
