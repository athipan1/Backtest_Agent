from __future__ import annotations

from app.models import BacktestCompareRequest, BacktestCompareResult, BacktestRunRequest, StrategyComparisonResult
from app.risk_engine import run_backtest_with_risk


def score_result(return_pct: float, max_drawdown: float, profit_factor: float | None, trade_count: int, risk_rejections: int) -> float:
    pf = profit_factor if profit_factor is not None else 0.0
    trade_penalty = 0.05 if trade_count == 0 else 0.0
    risk_penalty = min(risk_rejections * 0.001, 0.05)
    score = return_pct + (pf * 0.05) + max_drawdown - trade_penalty - risk_penalty
    return round(score, 6)


def compare_strategies(request: BacktestCompareRequest) -> BacktestCompareResult:
    ranked: list[StrategyComparisonResult] = []

    for candidate in request.candidates:
        run_request = BacktestRunRequest(
            symbols=request.symbols,
            initial_equity=request.initial_equity,
            bars=request.bars,
            strategy=candidate.strategy,
            fast_window=candidate.fast_window,
            slow_window=candidate.slow_window,
            risk_per_trade=request.risk_per_trade,
            max_position_pct=candidate.max_position_pct if candidate.max_position_pct is not None else request.max_position_pct,
            stop_loss_pct=candidate.stop_loss_pct if candidate.stop_loss_pct is not None else request.stop_loss_pct,
            reward_risk_ratio=candidate.reward_risk_ratio if candidate.reward_risk_ratio is not None else request.reward_risk_ratio,
            fee_bps=candidate.fee_bps if candidate.fee_bps is not None else request.fee_bps,
            slippage_bps=candidate.slippage_bps if candidate.slippage_bps is not None else request.slippage_bps,
            use_risk_agent=request.use_risk_agent,
            emergency_halt=request.emergency_halt,
            max_trades_per_day=request.max_trades_per_day,
        )
        result = run_backtest_with_risk(run_request)
        metrics = result.metrics
        ranked.append(
            StrategyComparisonResult(
                rank=0,
                name=candidate.name,
                strategy=candidate.strategy,
                fast_window=candidate.fast_window,
                slow_window=candidate.slow_window,
                score=score_result(
                    return_pct=metrics.return_pct,
                    max_drawdown=metrics.max_drawdown,
                    profit_factor=metrics.profit_factor,
                    trade_count=metrics.trade_count,
                    risk_rejections=metrics.risk_rejections,
                ),
                metrics=metrics,
                warnings=result.warnings,
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    ranked = [item.model_copy(update={"rank": index}) for index, item in enumerate(ranked, start=1)]
    return BacktestCompareResult(
        symbols=[symbol.upper() for symbol in request.symbols],
        ranked_results=ranked,
        best=ranked[0] if ranked else None,
    )
