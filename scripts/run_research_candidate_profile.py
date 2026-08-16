from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app import hourly_promotion_runner
from app.multi_strategy_walk_forward import WalkForwardMultiStrategyRequest
from app.research_candidate_profiles import (
    BULL_RESEARCH_PROFILE_ID,
    research_profile,
)


DEFAULT_REPORT_PATH = Path("reports/research-candidate-profile-result.json")


def install_research_profile(profile_id: str) -> dict[str, Any]:
    """Install candidates only into this process's nested research runner."""

    candidates = research_profile(profile_id)
    original_request_class = hourly_promotion_runner.WalkForwardMultiStrategyRequest

    def research_request_factory(**kwargs: Any) -> WalkForwardMultiStrategyRequest:
        if "candidates" in kwargs:
            raise RuntimeError("Research profile refuses an overlapping candidate override")
        return original_request_class(
            candidates=[candidate.model_copy(deep=True) for candidate in candidates],
            **kwargs,
        )

    hourly_promotion_runner.WalkForwardMultiStrategyRequest = research_request_factory
    return {
        "profile_id": profile_id,
        "candidate_count": len(candidates),
        "candidate_ids": [candidate.strategy_id for candidate in candidates],
        "strategy_families": [candidate.strategy for candidate in candidates],
    }


def run_research_profile(
    *,
    profile_id: str,
    report_path: Path,
) -> dict[str, Any]:
    """Run nested evidence generation without database publishing or promotion."""

    if os.getenv("PUBLISH_TO_DATABASE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }:
        raise RuntimeError("Research evaluator refuses PUBLISH_TO_DATABASE=true")

    os.environ["PUBLISH_TO_DATABASE"] = "false"
    profile = install_research_profile(profile_id)
    output = hourly_promotion_runner.run_nested_hourly_backtest(report_path)
    data = output.get("data") if isinstance(output.get("data"), dict) else {}
    data["research_only"] = True
    data["research_profile"] = profile
    data["database_publish_allowed"] = False
    data["promotion_allowed"] = False
    data["execution_allowed"] = False
    output["data"] = data
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(output, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output


def main() -> int:
    profile_id = os.getenv("BACKTEST_RESEARCH_PROFILE", BULL_RESEARCH_PROFILE_ID)
    report_path = Path(
        os.getenv("BACKTEST_RESEARCH_REPORT_PATH", str(DEFAULT_REPORT_PATH))
    )
    output = run_research_profile(profile_id=profile_id, report_path=report_path)
    print(json.dumps(output, indent=2, sort_keys=True))
    if output.get("status") != "success":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
