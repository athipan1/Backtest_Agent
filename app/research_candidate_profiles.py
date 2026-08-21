from __future__ import annotations

from typing import Final

from app.multi_strategy import MultiStrategyCandidate


BULL_RESEARCH_PROFILE_ID: Final[str] = "bull_research_v1"
STRATEGY_RESEARCH_V5_PROFILE_ID: Final[str] = "strategy_research_v5"
STRATEGY_RESEARCH_V6_PROFILE_ID: Final[str] = "strategy_research_v6"
STRATEGY_RESEARCH_V7_PROFILE_ID: Final[str] = "strategy_research_v7"


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
    """Return the preregistered v5 hypothesis suite."""

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


def strategy_research_v6_candidates() -> list[MultiStrategyCandidate]:
    """Return preregistered v6 hypotheses without tuning to a final holdout."""

    controls = strategy_research_v5_candidates()[:4]
    return [
        *controls,
        MultiStrategyCandidate(
            strategy_id="trend-following-30-120-risk-v6",
            name="Trend following v6 30/120 slow trend",
            strategy="trend_following",
            fast_window=30,
            slow_window=120,
            max_position_pct=0.06,
            stop_loss_pct=0.045,
            reward_risk_ratio=3.0,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-50-150-risk-v6",
            name="Trend following v6 50/150 structural trend",
            strategy="trend_following",
            fast_window=50,
            slow_window=150,
            max_position_pct=0.06,
            stop_loss_pct=0.05,
            reward_risk_ratio=3.2,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-20-80-risk-v6",
            name="Breakout v6 20/80 medium horizon",
            strategy="breakout",
            fast_window=20,
            slow_window=80,
            max_position_pct=0.06,
            stop_loss_pct=0.04,
            reward_risk_ratio=2.8,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-30-120-risk-v6",
            name="Breakout v6 30/120 slow horizon",
            strategy="breakout",
            fast_window=30,
            slow_window=120,
            max_position_pct=0.06,
            stop_loss_pct=0.045,
            reward_risk_ratio=3.2,
        ),
        MultiStrategyCandidate(
            strategy_id="mean-reversion-3-15-risk-v6",
            name="Mean reversion v6 3/15 short cycle",
            strategy="mean_reversion",
            fast_window=3,
            slow_window=15,
            max_position_pct=0.05,
            stop_loss_pct=0.025,
            reward_risk_ratio=1.8,
        ),
        MultiStrategyCandidate(
            strategy_id="mean-reversion-10-40-risk-v6",
            name="Mean reversion v6 10/40 slow cycle",
            strategy="mean_reversion",
            fast_window=10,
            slow_window=40,
            max_position_pct=0.05,
            stop_loss_pct=0.03,
            reward_risk_ratio=2.0,
        ),
    ]


def strategy_research_v7_candidates() -> list[MultiStrategyCandidate]:
    """Return sparse v7 hypotheses aimed at stronger OOS statistical power.

    v6 showed that adding more nearby slow-horizon variants did not improve the
    multiple-testing-adjusted evidence. v7 therefore keeps the four unchanged
    balanced controls and adds only six economically distinct hypotheses. The
    parameter set is preregistered before any final holdout is opened and uses
    smaller position caps than v5 production-style experiments.
    """

    controls = strategy_research_v5_candidates()[:4]
    return [
        *controls,
        MultiStrategyCandidate(
            strategy_id="sma-crossover-15-45-risk-v7",
            name="SMA crossover v7 15/45 medium trend",
            strategy="sma_crossover",
            fast_window=15,
            slow_window=45,
            max_position_pct=0.05,
            stop_loss_pct=0.03,
            reward_risk_ratio=2.4,
        ),
        MultiStrategyCandidate(
            strategy_id="sma-crossover-30-90-risk-v7",
            name="SMA crossover v7 30/90 slow trend",
            strategy="sma_crossover",
            fast_window=30,
            slow_window=90,
            max_position_pct=0.05,
            stop_loss_pct=0.04,
            reward_risk_ratio=2.8,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-15-60-risk-v7",
            name="Trend following v7 15/60 medium horizon",
            strategy="trend_following",
            fast_window=15,
            slow_window=60,
            max_position_pct=0.05,
            stop_loss_pct=0.035,
            reward_risk_ratio=2.5,
        ),
        MultiStrategyCandidate(
            strategy_id="trend-following-40-160-risk-v7",
            name="Trend following v7 40/160 structural horizon",
            strategy="trend_following",
            fast_window=40,
            slow_window=160,
            max_position_pct=0.05,
            stop_loss_pct=0.05,
            reward_risk_ratio=3.2,
        ),
        MultiStrategyCandidate(
            strategy_id="breakout-15-60-risk-v7",
            name="Breakout v7 15/60 confirmation horizon",
            strategy="breakout",
            fast_window=15,
            slow_window=60,
            max_position_pct=0.05,
            stop_loss_pct=0.035,
            reward_risk_ratio=2.6,
        ),
        MultiStrategyCandidate(
            strategy_id="mean-reversion-5-30-risk-v7",
            name="Mean reversion v7 5/30 wider recovery cycle",
            strategy="mean_reversion",
            fast_window=5,
            slow_window=30,
            max_position_pct=0.04,
            stop_loss_pct=0.025,
            reward_risk_ratio=1.8,
        ),
    ]


def research_profile(profile_id: str) -> list[MultiStrategyCandidate]:
    normalized = profile_id.strip().lower()
    if normalized == BULL_RESEARCH_PROFILE_ID:
        return bull_research_v1_candidates()
    if normalized == STRATEGY_RESEARCH_V5_PROFILE_ID:
        return strategy_research_v5_candidates()
    if normalized == STRATEGY_RESEARCH_V6_PROFILE_ID:
        return strategy_research_v6_candidates()
    if normalized == STRATEGY_RESEARCH_V7_PROFILE_ID:
        return strategy_research_v7_candidates()
    raise ValueError(f"Unknown research candidate profile: {profile_id}")
