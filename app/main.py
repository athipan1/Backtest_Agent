from __future__ import annotations

from fastapi import FastAPI

from app.compare import compare_strategies
from app.models import BacktestCompareRequest, BacktestCompareResult, BacktestRunRequest, BacktestRunResult, HealthData, StandardAgentResponse, WalkForwardRequest, WalkForwardResult
from app.risk_engine import run_backtest_with_risk as run_backtest
from app.walk_forward import run_walk_forward_validation


app = FastAPI(
    title="Backtest Agent",
    description="Historical simulation service for the multi-agent trading system.",
    version="0.1.0",
)


@app.get("/health", response_model=StandardAgentResponse[HealthData])
def health() -> StandardAgentResponse[HealthData]:
    return StandardAgentResponse(status="success", data=HealthData())


@app.post("/backtest/run", response_model=StandardAgentResponse[BacktestRunResult])
def backtest_run(request: BacktestRunRequest) -> StandardAgentResponse[BacktestRunResult]:
    return StandardAgentResponse(status="success", data=run_backtest(request))


@app.post("/backtest/compare", response_model=StandardAgentResponse[BacktestCompareResult])
def backtest_compare(request: BacktestCompareRequest) -> StandardAgentResponse[BacktestCompareResult]:
    return StandardAgentResponse(status="success", data=compare_strategies(request))


@app.post("/backtest/walk-forward", response_model=StandardAgentResponse[WalkForwardResult])
def backtest_walk_forward(request: WalkForwardRequest) -> StandardAgentResponse[WalkForwardResult]:
    return StandardAgentResponse(status="success", data=run_walk_forward_validation(request))


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Backtest Agent is running"}
