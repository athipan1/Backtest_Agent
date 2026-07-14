from __future__ import annotations

from typing import Dict, List

from app.compare import compare_strategies
from app.models import BacktestCompareRequest, BacktestRunRequest, PriceBar, WalkForwardRequest, WalkForwardResult
from app.risk_engine import run_backtest_with_risk


def split_bars_by_ratio(bars: List[PriceBar], ratio: float) -> tuple[List[PriceBar], List[PriceBar]]:
    ordered = sorted(bars, key=lambda item: item.timestamp)
    split_index = int(len(ordered) * ratio)
    return ordered[:split_index], ordered[split_index:]


def _candidate_to_run_request(request: WalkForwardRequest, bars: Dict[str, List[PriceBar]], candidate) -> BacktestRunRequest:
    return BacktestRunRequest(
        symbols=request.symbols,
        initial_equity=request.initial_equity,
        bars=bars,
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
        force_close_at_end=request.force_close_at_end,
        max_total_exposure_pct=request.max_total_exposure_pct,
        max_open_positions=request.max_open_positions,
        cash_reserve_pct=request.cash_reserve_pct,
        max_new_positions_per_bar=request.max_new_positions_per_bar,
    )


def _pass_reasons(test_result) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    metrics = test_result.metrics
    if metrics.trade_count <= 0:
        reasons.append("test_trade_count_zero")
    if metrics.expectancy <= 0:
        reasons.append("test_expectancy_not_positive")
    if metrics.max_drawdown < -0.10:
        reasons.append("test_max_drawdown_below_minus_10pct")
    if metrics.profit_factor is not None and metrics.profit_factor < 1.10:
        reasons.append("test_profit_factor_below_1_10")
    return len(reasons) == 0, reasons


def run_walk_forward_validation(request: WalkForwardRequest) -> WalkForwardResult:
    train_bars: Dict[str, List[PriceBar]] = {}
    test_bars: Dict[str, List[PriceBar]] = {}
    reasons: List[str] = []

    for symbol in [item.upper() for item in request.symbols]:
        source = next((bars for key, bars in request.bars.items() if key.upper() == symbol), [])
        train, test = split_bars_by_ratio(source, request.train_ratio)
        train_bars[symbol] = train
        test_bars[symbol] = test
        if len(train) < request.min_train_bars:
            reasons.append(f"{symbol}_train_bars_below_minimum")
        if len(test) < request.min_test_bars:
            reasons.append(f"{symbol}_test_bars_below_minimum")

    train_compare = compare_strategies(
        BacktestCompareRequest(
            symbols=request.symbols,
            initial_equity=request.initial_equity,
            bars=train_bars,
            candidates=request.candidates,
            risk_per_trade=request.risk_per_trade,
            max_position_pct=request.max_position_pct,
            stop_loss_pct=request.stop_loss_pct,
            reward_risk_ratio=request.reward_risk_ratio,
            fee_bps=request.fee_bps,
            slippage_bps=request.slippage_bps,
            use_risk_agent=request.use_risk_agent,
            emergency_halt=request.emergency_halt,
            max_trades_per_day=request.max_trades_per_day,
            force_close_at_end=request.force_close_at_end,
            max_total_exposure_pct=request.max_total_exposure_pct,
            max_open_positions=request.max_open_positions,
            cash_reserve_pct=request.cash_reserve_pct,
            max_new_positions_per_bar=request.max_new_positions_per_bar,
        )
    )

    selected = train_compare.best
    if selected is None:
        reasons.append("no_train_candidate_selected")
        return WalkForwardResult(
            symbols=[symbol.upper() for symbol in request.symbols],
            train_ratio=request.train_ratio,
            train_bars={symbol: len(rows) for symbol, rows in train_bars.items()},
            test_bars={symbol: len(rows) for symbol, rows in test_bars.items()},
            selected_candidate=None,
            train_ranking=train_compare.ranked_results,
            test_result=None,
            passed=False,
            reasons=reasons,
        )

    candidate = next(item for item in request.candidates if item.name == selected.name)
    test_result = run_backtest_with_risk(_candidate_to_run_request(request, test_bars, candidate))
    test_passed, test_reasons = _pass_reasons(test_result)
    reasons.extend(test_reasons)

    return WalkForwardResult(
        symbols=[symbol.upper() for symbol in request.symbols],
        train_ratio=request.train_ratio,
        train_bars={symbol: len(rows) for symbol, rows in train_bars.items()},
        test_bars={symbol: len(rows) for symbol, rows in test_bars.items()},
        selected_candidate=selected,
        train_ranking=train_compare.ranked_results,
        test_result=test_result,
        passed=test_passed and not reasons,
        reasons=reasons,
    )
