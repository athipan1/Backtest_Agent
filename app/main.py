from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api_contracts import (
    StrictBacktestCompareRequest,
    StrictBacktestRobustnessRequest,
    StrictBacktestRunRequest,
    StrictPerformanceReportRequest,
    StrictWalkForwardRequest,
)
from app.compare import compare_strategies
from app.models import (
    BacktestCompareResult,
    BacktestRobustnessResult,
    BacktestRunRequest,
    BacktestRunResult,
    HealthData,
    PerformanceReport,
    StandardAgentResponse,
    WalkForwardResult,
)
from app.publisher import ENGINE_VERSION, publish_backtest_result
from app.robustness import run_robustness_analysis
from app.risk_engine import run_backtest_with_risk as run_backtest
from app.run_identity import deterministic_symbol_run_id
from app.security import require_backtest_api_key
from app.system_contract import router as system_contract_router
from app.walk_forward import run_walk_forward_validation


class BacktestRunAndPublishRequest(StrictBacktestRunRequest):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    account_id: str = "1"
    run_id: Optional[str] = None
    skill_id: Optional[str] = None
    strategy_id: Optional[str] = None
    timeframe: str = "1d"
    publish_to_database: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BacktestRunAndPublishResult(BaseModel):
    result: BacktestRunResult
    published: bool
    publish_status: str
    database_payload: Optional[Dict[str, Any]] = None
    database_response: Optional[Dict[str, Any]] = None


class BacktestBatchRunAndPublishRequest(BacktestRunAndPublishRequest):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    symbols: List[str] = Field(min_length=1, max_length=25)
    batch_id: Optional[str] = None


class BacktestBatchItemResult(BaseModel):
    symbol: str
    run_id: str
    status: Literal["success", "failed"]
    published: bool = False
    publish_status: str
    result: Optional[BacktestRunResult] = None
    database_payload: Optional[Dict[str, Any]] = None
    database_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BacktestBatchRunAndPublishResult(BaseModel):
    batch_id: str
    symbols: List[str]
    items: List[BacktestBatchItemResult]
    succeeded_symbols: List[str]
    failed_symbols: List[str]
    published_count: int
    published: bool
    publish_status: Literal["success", "skipped", "partial_failure", "failed"]
    all_succeeded: bool


app = FastAPI(
    title="Backtest Agent",
    description="Historical simulation service for the multi-agent trading system.",
    version="0.1.0",
)
app.include_router(system_contract_router)


def _max_request_bytes() -> int:
    raw = os.getenv("BACKTEST_MAX_REQUEST_BYTES", "5242880")
    try:
        value = int(raw)
    except ValueError:
        return 5 * 1024 * 1024
    return max(1024, value)


@app.middleware("http")
async def reject_oversized_requests(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                request_bytes = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"status": "error", "error": "invalid Content-Length"},
                )
            if request_bytes > _max_request_bytes():
                return JSONResponse(
                    status_code=413,
                    content={
                        "status": "error",
                        "error": "request payload exceeds configured limit",
                    },
                )
    return await call_next(request)


def build_report(request: StrictPerformanceReportRequest) -> PerformanceReport:
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


@app.post(
    "/backtest/run",
    response_model=StandardAgentResponse[BacktestRunResult],
    dependencies=[Depends(require_backtest_api_key)],
)
def backtest_run(
    request: StrictBacktestRunRequest,
) -> StandardAgentResponse[BacktestRunResult]:
    return StandardAgentResponse(status="success", data=run_backtest(request))


@app.post(
    "/backtest/robustness",
    response_model=StandardAgentResponse[BacktestRobustnessResult],
    dependencies=[Depends(require_backtest_api_key)],
)
def backtest_robustness(
    request: StrictBacktestRobustnessRequest,
) -> StandardAgentResponse[BacktestRobustnessResult]:
    return StandardAgentResponse(
        status="success",
        data=run_robustness_analysis(request),
    )


@app.post(
    "/backtest/run-and-publish",
    response_model=StandardAgentResponse[BacktestRunAndPublishResult],
    dependencies=[Depends(require_backtest_api_key)],
)
def backtest_run_and_publish(
    request: BacktestRunAndPublishRequest,
) -> StandardAgentResponse[BacktestRunAndPublishResult]:
    if len(_normalized_symbols(request.symbols)) != 1:
        raise HTTPException(
            status_code=422,
            detail=(
                "run-and-publish requires exactly one symbol; use "
                "/backtest/run-and-publish-batch for multiple symbols"
            ),
        )
    result = run_backtest(request)
    publish_report = {
        "status": "skipped",
        "database_response": None,
        "payload": None,
    }
    if request.publish_to_database:
        publish_report = publish_backtest_result(
            request=request,
            result=result,
            account_id=request.account_id,
            run_id=request.run_id,
            skill_id=request.skill_id,
            strategy_id=request.strategy_id,
            timeframe=request.timeframe,
            metadata=request.metadata,
        )

    publish_status = str(publish_report.get("status") or "success")
    publish_succeeded = (
        not request.publish_to_database or publish_status == "success"
    )
    return StandardAgentResponse(
        status="success" if publish_succeeded else "error",
        data=BacktestRunAndPublishResult(
            result=result,
            published=request.publish_to_database and publish_status == "success",
            publish_status=publish_status,
            database_payload=publish_report.get("payload"),
            database_response=publish_report.get("database_response"),
        ),
        error=(
            None
            if publish_succeeded
            else f"Database publish did not succeed: {publish_status}"
        ),
    )


def _normalized_symbols(symbols: List[str]) -> List[str]:
    return list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))


def _bars_for_exact_symbol(request: BacktestRunRequest, symbol: str) -> list:
    for key, bars in request.bars.items():
        if key.upper() == symbol:
            return bars
    return []


def _single_symbol_batch_request(
    request: BacktestBatchRunAndPublishRequest,
    *,
    batch_id: str,
    symbol: str,
    index: int,
    batch_size: int,
) -> BacktestRunAndPublishRequest:
    symbol_run_id = deterministic_symbol_run_id(
        request,
        symbol=symbol,
        timeframe=request.timeframe,
        engine_version=ENGINE_VERSION,
    )
    payload = request.model_dump(exclude={"batch_id"})
    payload.update(
        symbols=[symbol],
        bars={symbol: _bars_for_exact_symbol(request, symbol)},
        run_id=symbol_run_id,
        metadata={
            **request.metadata,
            "batch_id": batch_id,
            "batch_symbol": symbol,
            "batch_index": index,
            "batch_size": batch_size,
            "run_identity_scope": "exact_symbol",
        },
    )
    return BacktestRunAndPublishRequest(**payload)


@app.post(
    "/backtest/run-and-publish-batch",
    response_model=StandardAgentResponse[BacktestBatchRunAndPublishResult],
    dependencies=[Depends(require_backtest_api_key)],
)
def backtest_run_and_publish_batch(
    request: BacktestBatchRunAndPublishRequest,
) -> StandardAgentResponse[BacktestBatchRunAndPublishResult]:
    """Run and publish one independent Backtest per exact symbol identity."""
    symbols = _normalized_symbols(request.symbols)
    batch_id = request.batch_id or request.run_id or f"batch-{uuid4().hex[:24]}"
    items: List[BacktestBatchItemResult] = []

    for index, symbol in enumerate(symbols, start=1):
        single_request = _single_symbol_batch_request(
            request,
            batch_id=batch_id,
            symbol=symbol,
            index=index,
            batch_size=len(symbols),
        )
        try:
            response = backtest_run_and_publish(single_request)
            result = response.data
            if result is None:
                raise RuntimeError("single-symbol Backtest returned no data")
            publish_ok = not request.publish_to_database or result.published
            if not publish_ok:
                raise RuntimeError(
                    f"Database publish did not succeed: {result.publish_status}"
                )
            items.append(
                BacktestBatchItemResult(
                    symbol=symbol,
                    run_id=single_request.run_id or "",
                    status="success",
                    published=result.published,
                    publish_status=result.publish_status,
                    result=result.result,
                    database_payload=result.database_payload,
                    database_response=result.database_response,
                )
            )
        except Exception as exc:
            items.append(
                BacktestBatchItemResult(
                    symbol=symbol,
                    run_id=single_request.run_id or "",
                    status="failed",
                    publish_status="failed",
                    error=str(exc),
                )
            )

    succeeded = [item.symbol for item in items if item.status == "success"]
    failed = [item.symbol for item in items if item.status == "failed"]
    published_count = sum(1 for item in items if item.published)
    all_succeeded = bool(items) and not failed
    if failed and succeeded:
        publish_status = "partial_failure"
    elif failed:
        publish_status = "failed"
    elif request.publish_to_database:
        publish_status = "success"
    else:
        publish_status = "skipped"

    return StandardAgentResponse(
        status="success" if all_succeeded else "error",
        data=BacktestBatchRunAndPublishResult(
            batch_id=batch_id,
            symbols=symbols,
            items=items,
            succeeded_symbols=succeeded,
            failed_symbols=failed,
            published_count=published_count,
            published=(
                request.publish_to_database
                and all_succeeded
                and published_count == len(items)
            ),
            publish_status=publish_status,
            all_succeeded=all_succeeded,
        ),
        error=None if all_succeeded else "One or more symbol Backtests failed.",
    )


@app.post(
    "/backtest/compare",
    response_model=StandardAgentResponse[BacktestCompareResult],
    dependencies=[Depends(require_backtest_api_key)],
)
def backtest_compare(
    request: StrictBacktestCompareRequest,
) -> StandardAgentResponse[BacktestCompareResult]:
    return StandardAgentResponse(status="success", data=compare_strategies(request))


@app.post(
    "/backtest/walk-forward",
    response_model=StandardAgentResponse[WalkForwardResult],
    dependencies=[Depends(require_backtest_api_key)],
)
def backtest_walk_forward(
    request: StrictWalkForwardRequest,
) -> StandardAgentResponse[WalkForwardResult]:
    return StandardAgentResponse(status="success", data=run_walk_forward_validation(request))


@app.post(
    "/backtest/report",
    response_model=StandardAgentResponse[PerformanceReport],
    dependencies=[Depends(require_backtest_api_key)],
)
def backtest_report(
    request: StrictPerformanceReportRequest,
) -> StandardAgentResponse[PerformanceReport]:
    return StandardAgentResponse(status="success", data=build_report(request))


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Backtest Agent is running"}
