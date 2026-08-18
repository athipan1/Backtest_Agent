from __future__ import annotations

from app import hourly_promotion_runner
from app.market_regime_candidate_policy import (
    apply_runtime_market_regime_candidate_policy,
)
from app.nested_validation_v4 import apply_nested_validation_v4


NESTED_VALIDATION_V4 = apply_nested_validation_v4(hourly_promotion_runner)
apply_runtime_market_regime_candidate_policy(hourly_promotion_runner)
main = hourly_promotion_runner.main


if __name__ == "__main__":
    main()
