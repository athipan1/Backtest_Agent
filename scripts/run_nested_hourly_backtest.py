from __future__ import annotations

from typing import Any

from app import hourly_promotion_runner
from app.market_regime_candidate_policy import (
    apply_runtime_market_regime_candidate_policy,
)
from app.nested_validation_v4 import apply_nested_validation_v4


_CONFIGURED = False
NESTED_VALIDATION_V4: dict[str, Any] | None = None


def _configure_runner() -> None:
    """Configure the production runner once, without import-time global mutation."""

    global _CONFIGURED, NESTED_VALIDATION_V4
    if _CONFIGURED:
        return
    NESTED_VALIDATION_V4 = apply_nested_validation_v4(hourly_promotion_runner)
    apply_runtime_market_regime_candidate_policy(hourly_promotion_runner)
    _CONFIGURED = True


def main() -> None:
    _configure_runner()
    hourly_promotion_runner.main()


if __name__ == "__main__":
    main()
