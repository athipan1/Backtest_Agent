from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

from app.multi_strategy import router as multi_strategy_router


BACKTEST_AGENT_TYPE = "backtest-agent"
BACKTEST_AGENT_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"

router = APIRouter()
router.include_router(multi_strategy_router)


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
        "correlation_id": None,
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
            "required_operational_endpoints": ["/health", "/ready", "/version"],
        },
    )


@router.get("/ready")
def ready() -> Dict[str, Any]:
    return contract_response(
        status="success",
        data={
            "ready": True,
            "run_endpoint": "/backtest/run",
            "compare_endpoint": "/backtest/compare",
            "multi_strategy_endpoint": "/backtest/multi-strategy",
            "walk_forward_endpoint": "/backtest/walk-forward",
            "robustness_endpoint": "/backtest/robustness",
            "report_endpoint": "/backtest/report",
            "supported_strategies": [
                "sma_crossover",
                "trend_following",
                "mean_reversion",
                "breakout",
            ],
            "multi_strategy_profile": "balanced_v1",
            "multi_strategy_selection": {
                "exact_symbol_only": True,
                "returns_best_eligible": True,
                "safety_gated": True,
            },
        },
        metadata={
            "contract_source": "backtest-agent-runtime-contract",
        },
        confidence_score=1.0,
    )
