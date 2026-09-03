from __future__ import annotations

from typing import Any

from app.multi_strategy import MultiStrategyCandidate

POLICY_SCHEMA = "research-strategy-expansion.v1"
EXPLORATORY_BUCKET = "exploratory"


def expanded_balanced_candidates() -> list[MultiStrategyCandidate]:
    """Return a deterministic research suite without relaxing any Backtest gate.

    The expansion changes only the candidate search space. Every candidate still
    passes through the existing walk-forward, nested OOS, statistical, sealed
    holdout and promotion gates owned by Backtest_Agent.
    """

    return [
        MultiStrategyCandidate(
            strategy_id="sma-crossover-fast-v1",
            name="SMA crossover 5/20",
            strategy="sma_crossover",
            fast_window=5,
            slow_window=20,
        ),
        MultiStrategyCandidate(
            strategy_id="sma-crossover-balanced-v1",
            name="SMA crossover 10/30",
            strategy="sma_crossover",
            fast_window=10,
            slow_window=30,
        ),
        MultiStrategyCandidate(
            strategy_id="sma-crossover-slow-v1",
            name="SMA crossover 20/50",
            strategy="sma_crossover",
            fast_window=20,
            slow_window=50,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-fast-v1",
            name="Trend following 10/30",
            strategy="trend_following",
            fast_window=10,
            slow_window=30,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-balanced-v1",
            name="Trend following 20/50",
            strategy="trend_following",
            fast_window=20,
            slow_window=50,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-slow-v1",
            name="Trend following 50/100",
            strategy="trend_following",
            fast_window=50,
            slow_window=100,
        ),
        MultiStrategyCandidate(
            strategy_id="mean-reversion-fast-v1",
            name="Mean reversion 3/10",
            strategy="mean_reversion",
            fast_window=3,
            slow_window=10,
        ),
        MultiStrategyCandidate(
            strategy_id="mean-reversion-balanced-v1",
            name="Mean reversion 5/20",
            strategy="mean_reversion",
            fast_window=5,
            slow_window=20,
        ),
        MultiStrategyCandidate(
            strategy_id="mean-reversion-slow-v1",
            name="Mean reversion 10/40",
            strategy="mean_reversion",
            fast_window=10,
            slow_window=40,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-fast-v1",
            name="Breakout 3/15",
            strategy="breakout",
            fast_window=3,
            slow_window=15,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-balanced-v1",
            name="Breakout 5/20",
            strategy="breakout",
            fast_window=5,
            slow_window=20,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-slow-v1",
            name="Breakout 10/50",
            strategy="breakout",
            fast_window=10,
            slow_window=50,
        ),
    ]


def _ids_for_family(family: str) -> tuple[str, ...]:
    return tuple(
        str(candidate.strategy_id)
        for candidate in expanded_balanced_candidates()
        if candidate.strategy == family and candidate.strategy_id
    )


def apply_research_strategy_expansion_policy() -> dict[str, Any]:
    """Expand the strategy-bucket policy used by the hourly research Backtest.

    This intentionally patches only candidate discovery metadata and the candidate
    factory consumed by the existing strategy bucket policy. It does not change
    any eligibility threshold or grant Risk, Execution, or broker authority.
    """

    from app import strategy_bucket_candidate_policy as bucket_policy

    bucket_policy.default_multi_strategy_candidates = expanded_balanced_candidates
    bucket_policy.SUPPORTED_BUCKETS = frozenset(
        {*bucket_policy.SUPPORTED_BUCKETS, EXPLORATORY_BUCKET}
    )
    bucket_policy.BUCKET_STRATEGY_IDS = {
        "core_dividend": (
            *_ids_for_family("trend_following"),
            *_ids_for_family("sma_crossover"),
        ),
        "value_rebound": (
            *_ids_for_family("mean_reversion"),
            *_ids_for_family("sma_crossover"),
        ),
        "news_momentum": (
            *_ids_for_family("breakout"),
            *_ids_for_family("trend_following"),
        ),
        EXPLORATORY_BUCKET: tuple(
            str(candidate.strategy_id)
            for candidate in expanded_balanced_candidates()
            if candidate.strategy_id
        ),
    }

    return {
        "schema_version": POLICY_SCHEMA,
        "candidate_count": len(expanded_balanced_candidates()),
        "strategy_families": sorted(
            {candidate.strategy for candidate in expanded_balanced_candidates()}
        ),
        "supported_buckets": sorted(bucket_policy.SUPPORTED_BUCKETS),
        "exploratory_bucket": EXPLORATORY_BUCKET,
        "selection_thresholds_relaxed": False,
        "nested_oos_required": True,
        "sealed_holdout_required": True,
        "production_authority_granted": False,
        "risk_execution_authority_granted": False,
        "broker_order_authorized": False,
    }
