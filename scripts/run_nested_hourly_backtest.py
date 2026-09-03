from __future__ import annotations

from typing import Any

from app import hourly_promotion_runner
from app.insufficient_history_rejection_policy import (
    apply_insufficient_history_rejection_policy,
)
from app.market_regime_candidate_policy import (
    apply_runtime_market_regime_candidate_policy,
)
from app.nested_validation_v4 import apply_nested_validation_v4
from app.research_strategy_expansion_policy import (
    apply_research_strategy_expansion_policy,
)
from app.strategy_bucket_candidate_policy import (
    apply_strategy_bucket_candidate_policy,
)


_CONFIGURED = False
NESTED_VALIDATION_V4: dict[str, Any] | None = None
RESEARCH_STRATEGY_EXPANSION: dict[str, Any] | None = None


def _configure_runner() -> None:
    """Configure the production runner once, without import-time global mutation."""

    global _CONFIGURED, NESTED_VALIDATION_V4, RESEARCH_STRATEGY_EXPANSION
    if _CONFIGURED:
        return
    NESTED_VALIDATION_V4 = apply_nested_validation_v4(hourly_promotion_runner)
    # Insufficient listing history is a deterministic candidate rejection, not an
    # infrastructure failure. Install this after v4 so it wraps v4 gate rejection
    # semantics while keeping all other failures fail-closed.
    apply_insufficient_history_rejection_policy(hourly_promotion_runner)
    # Expand only the candidate search space. The existing Backtest validation,
    # nested OOS, statistical and sealed-holdout gates remain authoritative.
    RESEARCH_STRATEGY_EXPANSION = apply_research_strategy_expansion_policy()
    # Apply the per-symbol Manager bucket first. The Market Regime policy then
    # intersects its allow-list with this narrower candidate set.
    apply_strategy_bucket_candidate_policy(hourly_promotion_runner)
    apply_runtime_market_regime_candidate_policy(hourly_promotion_runner)
    _CONFIGURED = True


def main() -> None:
    _configure_runner()
    hourly_promotion_runner.main()


if __name__ == "__main__":
    main()
