from __future__ import annotations

from fastapi import FastAPI

from app.compare import compare_strategies
from app.models import BacktestCompareRequest, BacktestCompareResult, BacktestRunRequest, BacktestRunResult, HealthData, PerformanceReport, PerformanceReportRequest, StandardAgentResponse, WalkForwardRequest, WalkForwardResult
from app.risk_engine import run_backtest_with_risk as run_backtest
from app.walk_forward import run_walk_forward_validation


app = FastAPI(
    title="Backtest Agent",
    description="Historical simulation service for the multi-agent trading system.",
    version="0.1.0",
)


def build_report(request: PerformanceReportRequest) -> PerformanceReport:
    metrics = request.result.metrics
    gates = {
        "trade_count": metrics.trade_count >= request.min_trades,
        "profit_factor": metrics.profit_factor is not None and metrics.profit_factor >= request.min_profit_factor,
        "expectancy": metrics.expectancy > request.min_expectancy,
        "max_drawdown": metrics.max_drawdown >= request.max_drawdown_floor,
        "safety": metrics.kill_switch_events == 0,
    }
    score = round(sum(1 for value in gates.values() if value) / len(gates), 6)
    verdict = "blocked" if metrics.kill_switch_events > 0 else "paper_ready" if score >= 0.8 else "needs_improvement"
    return PerformanceReport(
        verdict=verdict,
        score=score,
        summary=f"{verdict}: score={score}, trades={metrics.trade_count}, return={metrics.return_pct}",
        strengths=[key for key, value in gates.items() if value],
        weaknesses=[key for key, value in gates.items() if not value],
        gates=gates,
        metrics=metrics,
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


@app.post("/backtest/report", response_model=StandardAgentResponse[PerformanceReport])
def backtest_report(request: PerformanceReportRequest) -> StandardAgentResponse[PerformanceReport]:
    return StandardAgentResponse(status="success", data=build_report(request))


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Backtest Agent is running"}
