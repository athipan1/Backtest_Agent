from __future__ import annotations

from fastapi import FastAPI

from app.models import BacktestRunRequest, BacktestRunResult, HealthData, StandardAgentResponse
from app.risk_engine import run_backtest_with_risk as run_backtest


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


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Backtest Agent is running"}
