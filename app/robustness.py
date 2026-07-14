from __future__ import annotations

from random import Random
from statistics import median
from typing import Iterable, List

from app.models import (
    BacktestRobustnessRequest,
    BacktestRobustnessResult,
    BacktestRunRequest,
    BacktestRunResult,
    MonteCarloResult,
    ParameterSensitivityResult,
    SensitivityScenarioResult,
)
from app.risk_engine import run_backtest_with_risk


_ROBUSTNESS_FIELDS = {
    "monte_carlo_simulations",
    "monte_carlo_seed",
    "min_monte_carlo_trades",
    "sensitivity_fast_delta",
    "sensitivity_slow_delta",
}


def _percentile(values: List[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _path_max_drawdown(initial_equity: float, pnl_path: Iterable[float]) -> tuple[float, float]:
    equity = initial_equity
    peak = initial_equity
    worst_drawdown = 0.0
    for pnl in pnl_path:
        equity = max(0.0, equity + pnl)
        peak = max(peak, equity)
        if peak > 0:
            worst_drawdown = min(worst_drawdown, (equity - peak) / peak)
        if equity <= 0:
            break
    return equity, worst_drawdown


def monte_carlo_trade_bootstrap(
    *,
    initial_equity: float,
    trade_pnls: List[float],
    simulations: int,
    seed: int,
    minimum_trades: int,
) -> MonteCarloResult:
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    if minimum_trades < 2:
        raise ValueError("minimum_trades must be at least 2")
    if len(trade_pnls) < minimum_trades:
        return MonteCarloResult(
            status="insufficient_data",
            simulations=simulations,
            seed=seed,
            source_trade_count=len(trade_pnls),
            trades_per_simulation=len(trade_pnls),
            reason=(
                f"requires at least {minimum_trades} closed trades; "
                f"received {len(trade_pnls)}"
            ),
        )

    random = Random(seed)
    final_equities: List[float] = []
    max_drawdowns: List[float] = []
    path_length = len(trade_pnls)
    for _ in range(simulations):
        sampled = [random.choice(trade_pnls) for _ in range(path_length)]
        final_equity, drawdown = _path_max_drawdown(initial_equity, sampled)
        final_equities.append(final_equity)
        max_drawdowns.append(drawdown)

    return MonteCarloResult(
        status="completed",
        simulations=simulations,
        seed=seed,
        source_trade_count=path_length,
        trades_per_simulation=path_length,
        median_final_equity=round(median(final_equities), 2),
        p05_final_equity=round(_percentile(final_equities, 0.05), 2),
        p95_final_equity=round(_percentile(final_equities, 0.95), 2),
        probability_of_loss=round(
            sum(value < initial_equity for value in final_equities)
            / simulations,
            6,
        ),
        median_max_drawdown=round(median(max_drawdowns), 6),
        p05_max_drawdown=round(_percentile(max_drawdowns, 0.05), 6),
    )


def _closed_trade_pnls(result: BacktestRunResult) -> List[float]:
    return [
        float(trade.round_trip_realized_pnl)
        for trade in result.trades
        if trade.side == "sell"
        and trade.position_closed
        and trade.round_trip_realized_pnl is not None
    ]


def _neighboring_windows(
    request: BacktestRobustnessRequest,
) -> List[tuple[int, int]]:
    fast_values = {
        request.fast_window - request.sensitivity_fast_delta,
        request.fast_window,
        request.fast_window + request.sensitivity_fast_delta,
    }
    slow_values = {
        request.slow_window - request.sensitivity_slow_delta,
        request.slow_window,
        request.slow_window + request.sensitivity_slow_delta,
    }
    return sorted(
        (fast, slow)
        for fast in fast_values
        for slow in slow_values
        if fast >= 1
        and slow >= 2
        and fast < slow
        and (fast, slow) != (request.fast_window, request.slow_window)
    )


def parameter_sensitivity(
    request: BacktestRobustnessRequest,
    baseline: BacktestRunResult,
) -> ParameterSensitivityResult:
    payload = request.model_dump(exclude=_ROBUSTNESS_FIELDS)
    scenarios: List[SensitivityScenarioResult] = []
    for fast_window, slow_window in _neighboring_windows(request):
        scenario_payload = {
            **payload,
            "fast_window": fast_window,
            "slow_window": slow_window,
        }
        result = run_backtest_with_risk(
            BacktestRunRequest(**scenario_payload)
        )
        scenarios.append(
            SensitivityScenarioResult(
                fast_window=fast_window,
                slow_window=slow_window,
                metrics=result.metrics,
            )
        )

    returns = [scenario.metrics.return_pct for scenario in scenarios]
    baseline_return = baseline.metrics.return_pct
    return ParameterSensitivityResult(
        scenario_count=len(scenarios),
        baseline_fast_window=request.fast_window,
        baseline_slow_window=request.slow_window,
        fast_delta=request.sensitivity_fast_delta,
        slow_delta=request.sensitivity_slow_delta,
        profitable_scenario_pct=(
            round(sum(value > 0 for value in returns) / len(returns), 6)
            if returns
            else None
        ),
        median_return_pct=round(median(returns), 6) if returns else None,
        worst_return_pct=round(min(returns), 6) if returns else None,
        best_return_pct=round(max(returns), 6) if returns else None,
        baseline_rank_by_return=(
            1 + sum(value > baseline_return for value in returns)
            if returns
            else None
        ),
        scenarios=scenarios,
    )


def run_robustness_analysis(
    request: BacktestRobustnessRequest,
) -> BacktestRobustnessResult:
    baseline_payload = request.model_dump(exclude=_ROBUSTNESS_FIELDS)
    baseline = run_backtest_with_risk(BacktestRunRequest(**baseline_payload))
    monte_carlo = monte_carlo_trade_bootstrap(
        initial_equity=request.initial_equity,
        trade_pnls=_closed_trade_pnls(baseline),
        simulations=request.monte_carlo_simulations,
        seed=request.monte_carlo_seed,
        minimum_trades=request.min_monte_carlo_trades,
    )
    sensitivity = parameter_sensitivity(request, baseline)

    warnings: List[str] = []
    if monte_carlo.status == "insufficient_data":
        warnings.append("monte_carlo_insufficient_closed_trades")
    elif (
        monte_carlo.probability_of_loss is not None
        and monte_carlo.probability_of_loss >= 0.25
    ):
        warnings.append("monte_carlo_loss_probability_at_least_25pct")
    if sensitivity.scenario_count < 4:
        warnings.append("parameter_neighborhood_is_small")
    if (
        baseline.metrics.return_pct > 0
        and sensitivity.profitable_scenario_pct is not None
        and sensitivity.profitable_scenario_pct < 0.5
    ):
        warnings.append("parameter_performance_is_fragile")

    return BacktestRobustnessResult(
        baseline=baseline,
        monte_carlo=monte_carlo,
        sensitivity=sensitivity,
        warnings=warnings,
    )
