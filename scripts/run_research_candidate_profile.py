from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.pre_holdout_research import run_pre_holdout_research
from app.research_candidate_profiles import (
    STRATEGY_RESEARCH_V5_PROFILE_ID,
    research_profile,
)


DEFAULT_REPORT_PATH = Path("reports/research-candidate-profile-result.json")


def install_research_profile(profile_id: str) -> dict[str, Any]:
    """Return immutable profile metadata without mutating production globals."""

    candidates = research_profile(profile_id)
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
    """Run nested v4 research while keeping the final holdout sealed."""

    return run_pre_holdout_research(
        profile_id=profile_id,
        report_path=report_path,
    )


def main() -> int:
    profile_id = os.getenv(
        "BACKTEST_RESEARCH_PROFILE",
        STRATEGY_RESEARCH_V5_PROFILE_ID,
    )
    report_path = Path(
        os.getenv("BACKTEST_RESEARCH_REPORT_PATH", str(DEFAULT_REPORT_PATH))
    )
    output = run_research_profile(profile_id=profile_id, report_path=report_path)
    print(__import__("json").dumps(output, indent=2, sort_keys=True))
    if output.get("status") != "success":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
