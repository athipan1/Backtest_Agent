from __future__ import annotations

from app.engine import _run_backtest
from app.models import BacktestRunRequest, BacktestRunResult
from app.risk_adapter import LocalRiskAdapter


def run_backtest_with_risk(request: BacktestRunRequest) -> BacktestRunResult:
    """Run the shared synchronous engine with the local risk gate enabled."""
    risk_adapter = LocalRiskAdapter() if request.use_risk_agent else None
    return _run_backtest(request, risk_adapter=risk_adapter)
