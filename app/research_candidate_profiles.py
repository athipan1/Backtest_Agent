from __future__ import annotations

from typing import Final

from app.multi_strategy import MultiStrategyCandidate


BULL_RESEARCH_PROFILE_ID: Final[str] = "bull_research_v1"
STRATEGY_RESEARCH_V5_PROFILE_ID: Final[str] = "strategy_research_v5"


def bull_research_v1_candidates() -> list[MultiStrategyCandidate]:
    """Return the legacy deterministic bull-market research suite."""

    return [
        MultiStrategyCandidate(
            strategy_id="sma-crossover-bull-fast-v1",
            name="SMA crossover bull research 5/15",
            strategy="sma_crossover",
            fast_window=5,
            slow_window=15,
        ),
        MultiStrategyCandidate(
            strategy_id="sma-crossover-balanced-v1",
            name="SMA crossover 10/30 baseline",
            strategy="sma_crossover",
            fast_window=10,
            slow_window=30,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-bull-fast-v1",
            name="Trend following bull research 10/30",
            strategy="trend_following",
            fast_window=10,
            slow_window=30,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-balanced-v1",
            name="Trend following 20/50 baseline",
            strategy="trend_following",
            fast_window=20,
            slow_window=50,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-bull-fast-v1",
            name="Breakout bull research 3/10",
            strategy="breakout",
            fast_window=3,
            slow_window=10,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-balanced-v1",
            name="Breakout 5/20 baseline",
            strategy="breakout",
            fast_window=5,
            slow_window=20,
        ),
    ]


def strategy_research_v5_candidates() -> list[MultiStrategyCandidate]:
    """Return the preregistered v5 hypothesis suite.

    The v5 suite is research-only and intentionally uses strategy families that
    Backtest_Agent already supports. Four balanced-v1 controls stay unchanged so
    every experiment has a stable benchmark. Four new hypotheses use slower trend
    and breakout horizons plus smaller position caps and wider reward/risk ratios.

    These configurations are fixed before the sealed holdout is inspected. They
    are not parameter-search grids and must be evaluated with candidate-count-aware
    statistical corrections. Passing this profile only makes a symbol eligible for
    a later, separately authorized final-holdout evaluation.
    """

    return [
        MultiStrategyCandidate(
            strategy_id="sma-crossover-balanced-v1",
            name="SMA crossover 10/30 baseline",
            strategy="sma_crossover",
            fast_window=10,
            slow_window=30,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-balanced-v1",
            name="Trend following 20/50 baseline",
            strategy="trend_following",
            fast_window=20,
            slow_window=50,
        ),
        MultiStrategyCandidate(
            strategy_id="mean-reversion-balanced-v1",
            name="Mean reversion 5/20 baseline",
            strategy="mean_reversion",
            fast_window=5,
            slow_window=20,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-balanced-v1",
            name="Breakout 5/20 baseline",
            strategy="breakout",
            fast_window=5,
            slow_window=20,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-10-50-risk-v5",
            name="Trend following v5 10/50 risk-controlled",
            strategy="trend_following",
            fast_window=10,
            slow_window=50,
            max_position_pct=0.08,
            stop_loss_pct=0.035,
            reward_risk_ratio=2.5,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-20-100-risk-v5",
            name="Trend following v5 20/100 slow trend",
            strategy="trend_following",
            fast_window=20,
            slow_window=100,
            max_position_pct=0.08,
            stop_loss_pct=0.04,
            reward_risk_ratio=3.0,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-10-40-risk-v5",
            name="Breakout v5 10/40 risk-controlled",
            strategy="breakout",
            fast_window=10,
            slow_window=40,
            max_position_pct=0.08,
            stop_loss_pct=0.035,
            reward_risk_ratio=2.5,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-20-55-risk-v5",
            name="Breakout v5 20/55 long horizon",
            strategy="breakout",
            fast_window=20,
            slow_window=55,
            max_position_pct=0.08,
            stop_loss_pct=0.04,
            reward_risk_ratio=3.0,
        ),
    ]


def research_profile(profile_id: str) -> list[MultiStrategyCandidate]:
    normalized = profile_id.strip().lower()
    if normalized == BULL_RESEARCH_PROFILE_ID:
        return bull_research_v1_candidates()
    if normalized == STRATEGY_RESEARCH_V5_PROFILE_ID:
        return strategy_research_v5_candidates()
    raise ValueError(f"Unknown research candidate profile: {profile_id}")
