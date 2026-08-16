from __future__ import annotations

from typing import Final

from app.multi_strategy import MultiStrategyCandidate


BULL_RESEARCH_PROFILE_ID: Final[str] = "bull_research_v1"


def bull_research_v1_candidates() -> list[MultiStrategyCandidate]:
    """Return a deterministic bull-market research suite.

    This profile deliberately remains outside the production balanced-v1 path.
    It expands only strategy configurations already supported by Backtest_Agent
    and is intended for nested walk-forward/statistical research before any
    candidate is considered for promotion.

    The faster variants address the observed training-window trade-count
    bottleneck without lowering ``min_trades`` or any performance/statistical
    gate. Candidate count is intentionally explicit so DSR/multiple-testing
    corrections can account for the larger research search space.
    """

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


def research_profile(profile_id: str) -> list[MultiStrategyCandidate]:
    normalized = profile_id.strip().lower()
    if normalized == BULL_RESEARCH_PROFILE_ID:
        return bull_research_v1_candidates()
    raise ValueError(f"Unknown research candidate profile: {profile_id}")
