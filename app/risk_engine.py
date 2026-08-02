from __future__ import annotations

from app.engine import _run_backtest
from app.execution_policy import (
    execution_policy_context,
    resolve_execution_policy,
)
from app.models import BacktestRunRequest, BacktestRunResult
from app.risk_adapter import LocalRiskAdapter


def run_backtest_with_risk(request: BacktestRunRequest) -> BacktestRunResult:
    """Run the engine with one isolated risk and execution policy context."""

    risk_adapter = LocalRiskAdapter() if request.use_risk_agent else None
    policy = resolve_execution_policy(request)
    with execution_policy_context(policy):
        return _run_backtest(request, risk_adapter=risk_adapter)
