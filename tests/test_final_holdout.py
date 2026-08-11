from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.data_provider import dataset_fingerprint
from app.final_holdout import (
    FinalHoldoutCriteria,
    FinalHoldoutError,
    canonical_parameters_sha256,
    evaluate_sealed_final_holdout,
    split_sealed_final_holdout,
)
from app.models import BacktestMetrics, BacktestRunResult, PriceBar


def _bars(count: int) -> list[PriceBar]:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return [
        PriceBar(
            timestamp=start + timedelta(days=index),
            open=100 + index * 0.1,
            high=101 + index * 0.1,
            low=99 + index * 0.1,
            close=100.5 + index * 0.1,
            volume=1_000_000,
        )
        for index in range(count)
    ]


def _result(
    *,
    strategy: str = "sma_crossover",
    trades: int = 20,
    return_pct: float = 0.10,
    sharpe: float | None = 1.2,
    drawdown: float = -0.08,
    profit_factor: float | None = 1.5,
) -> BacktestRunResult:
    metrics = BacktestMetrics(
        initial_equity=100_000,
        final_equity=100_000 * (1 + return_pct),
        net_profit=100_000 * return_pct,
        return_pct=return_pct,
        trade_count=trades,
        winning_trades=max(0, trades - 5),
        losing_trades=min(5, trades),
        win_rate=(0.0 if trades == 0 else max(0, trades - 5) / trades),
        gross_profit=max(0.0, return_pct * 120_000),
        gross_loss=max(0.0, abs(return_pct) * 20_000),
        profit_factor=profit_factor,
        expectancy=500.0 if trades else 0.0,
        max_drawdown=drawdown,
        annualized_return=return_pct,
        annualized_volatility=0.12,
        sharpe_ratio=sharpe,
        sortino_ratio=1.4 if sharpe is not None else None,
        calmar_ratio=1.0 if drawdown < 0 else None,
    )
    return BacktestRunResult(
        strategy=strategy,
        symbols=["AAPL"],
        metrics=metrics,
        trades=[],
        equity_curve=[],
    )


def test_sealed_holdout_slicing_is_deterministic_and_non_overlapping():
    source = list(reversed(_bars(900)))
    criteria = FinalHoldoutCriteria(bars=252)

    first_research, first_holdout = split_sealed_final_holdout(
        source,
        criteria=criteria,
        minimum_research_bars=630,
    )
    second_research, second_holdout = split_sealed_final_holdout(
        source,
        criteria=criteria,
        minimum_research_bars=630,
    )

    assert first_research == second_research
    assert first_holdout == second_holdout
    assert len(first_research) == 648
    assert len(first_holdout) == 252
    assert first_research[-1].timestamp < first_holdout[0].timestamp
    assert set(bar.timestamp for bar in first_research).isdisjoint(
        bar.timestamp for bar in first_holdout
    )
    assert first_holdout == sorted(_bars(900), key=lambda item: item.timestamp)[-252:]


def test_insufficient_history_for_holdout_fails_closed():
    with pytest.raises(FinalHoldoutError, match="insufficient history"):
        split_sealed_final_holdout(
            _bars(881),
            criteria=FinalHoldoutCriteria(bars=252),
            minimum_research_bars=630,
        )


def test_disabled_holdout_returns_all_research_bars_only():
    source = _bars(900)
    research, holdout = split_sealed_final_holdout(
        source,
        criteria=FinalHoldoutCriteria(enabled=False),
        minimum_research_bars=630,
    )

    assert research == source
    assert holdout == []


def test_holdout_evidence_records_exact_fingerprint_strategy_and_parameters():
    holdout = _bars(252)
    parameters = {
        "strategy": "sma_crossover",
        "fast_window": 10,
        "slow_window": 30,
        "risk_per_trade": 0.01,
    }
    evidence = evaluate_sealed_final_holdout(
        result=_result(),
        bars=holdout,
        criteria=FinalHoldoutCriteria(
            bars=252,
            min_trades=10,
            min_return=0.0,
            min_sharpe=0.5,
            max_drawdown_floor=-0.20,
        ),
        strategy_id="sma-v1",
        effective_parameters=parameters,
    )

    assert evidence.enabled is True
    assert evidence.bar_count == 252
    assert evidence.trade_count == 20
    assert evidence.return_pct == 0.10
    assert evidence.sharpe_ratio == 1.2
    assert evidence.profit_factor == 1.5
    assert evidence.max_drawdown == -0.08
    assert evidence.dataset_fingerprint == dataset_fingerprint({"AAPL": holdout})
    assert evidence.strategy_id == "sma-v1"
    assert evidence.effective_parameters_sha256 == canonical_parameters_sha256(parameters)
    assert evidence.passed is True
    assert all(evidence.gates.values())


@pytest.mark.parametrize(
    "result, failed_gate",
    [
        (_result(trades=2), "minimum_trades"),
        (_result(return_pct=-0.05), "minimum_return"),
        (_result(sharpe=0.1), "minimum_sharpe"),
        (_result(drawdown=-0.35), "maximum_drawdown"),
        (_result(strategy="mean_reversion"), "exact_strategy"),
    ],
)
def test_holdout_gate_failure_blocks_evidence(result, failed_gate):
    evidence = evaluate_sealed_final_holdout(
        result=result,
        bars=_bars(252),
        criteria=FinalHoldoutCriteria(
            bars=252,
            min_trades=10,
            min_return=0.0,
            min_sharpe=0.5,
            max_drawdown_floor=-0.20,
        ),
        strategy_id="sma-v1",
        effective_parameters={"strategy": "sma_crossover"},
    )

    assert evidence.passed is False
    assert evidence.gates[failed_gate] is False


def test_holdout_bar_count_cannot_change_after_sealing():
    with pytest.raises(FinalHoldoutError, match="bar count changed"):
        evaluate_sealed_final_holdout(
            result=_result(),
            bars=_bars(251),
            criteria=FinalHoldoutCriteria(bars=252),
            strategy_id="sma-v1",
            effective_parameters={"strategy": "sma_crossover"},
        )


def test_disabled_holdout_cannot_be_promotion_evidence():
    with pytest.raises(FinalHoldoutError, match="disabled holdout"):
        evaluate_sealed_final_holdout(
            result=_result(),
            bars=_bars(252),
            criteria=FinalHoldoutCriteria(enabled=False),
            strategy_id="sma-v1",
            effective_parameters={"strategy": "sma_crossover"},
        )
