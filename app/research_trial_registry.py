from __future__ import annotations

from typing import Any, Final, Iterable


TRIAL_REGISTRY_SCHEMA_VERSION: Final[str] = "research-trial-registry.v1"

# This manifest is intentionally code-reviewed and append-only. A research profile may
# reuse an existing control, but a newly introduced strategy identity must be declared
# here before the research runner will evaluate it. That keeps multiple-testing
# accounting from silently resetting when a new profile is created.
_PROFILE_UNIQUE_TRIALS: Final[dict[str, tuple[str, ...]]] = {
    "strategy_research_v5": (
        "sma-crossover-balanced-v1",
        "trend-following-balanced-v1",
        "mean-reversion-balanced-v1",
        "breakout-balanced-v1",
        "trend-following-10-50-risk-v5",
        "trend-following-20-100-risk-v5",
        "breakout-10-40-risk-v5",
        "breakout-20-55-risk-v5",
    ),
    "strategy_research_v6": (
        "sma-crossover-balanced-v1",
        "trend-following-balanced-v1",
        "mean-reversion-balanced-v1",
        "breakout-balanced-v1",
        "trend-following-10-50-risk-v5",
        "trend-following-20-100-risk-v5",
        "breakout-10-40-risk-v5",
        "breakout-20-55-risk-v5",
        "trend-following-30-120-risk-v6",
        "trend-following-50-150-risk-v6",
        "breakout-20-80-risk-v6",
        "breakout-30-120-risk-v6",
        "mean-reversion-3-15-risk-v6",
        "mean-reversion-10-40-risk-v6",
    ),
}

_FIRST_SEEN_PROFILE: Final[dict[str, str]] = {
    strategy_id: profile_id
    for profile_id, strategy_ids in _PROFILE_UNIQUE_TRIALS.items()
    for strategy_id in strategy_ids
    if strategy_id
    not in {
        candidate_id
        for earlier_profile, candidate_ids in _PROFILE_UNIQUE_TRIALS.items()
        if earlier_profile != profile_id
        for candidate_id in candidate_ids
    }
}
# The comprehension above cannot encode profile ordering reliably. Build the explicit
# first-seen map below instead, preserving the append-only research chronology.
_FIRST_SEEN_PROFILE = {}
for _profile_id in ("strategy_research_v5", "strategy_research_v6"):
    for _strategy_id in _PROFILE_UNIQUE_TRIALS[_profile_id]:
        _FIRST_SEEN_PROFILE.setdefault(_strategy_id, _profile_id)


def registered_trial_ids(profile_id: str) -> tuple[str, ...]:
    try:
        return _PROFILE_UNIQUE_TRIALS[profile_id]
    except KeyError as exc:
        raise ValueError(f"Research profile is not registered for trial accounting: {profile_id}") from exc


def statistical_trial_count(profile_id: str) -> int:
    """Return cumulative unique strategy identities considered through this profile."""

    return len(registered_trial_ids(profile_id))


def build_trial_registry_snapshot(
    *,
    profile_id: str,
    candidate_ids: Iterable[str | None],
    dataset_fingerprint: str,
) -> dict[str, Any]:
    """Return deterministic, fail-closed trial accounting for one research run."""

    normalized_ids = tuple(str(value) for value in candidate_ids if value)
    if len(normalized_ids) != len(set(normalized_ids)):
        raise RuntimeError("Research trial registry refuses duplicate candidate identities")

    registered = registered_trial_ids(profile_id)
    unknown = sorted(set(normalized_ids).difference(registered))
    if unknown:
        raise RuntimeError(
            "Research trial registry refuses unregistered candidate identities: "
            + ", ".join(unknown)
        )

    missing_current = sorted(
        strategy_id
        for strategy_id in registered
        if _FIRST_SEEN_PROFILE.get(strategy_id) == profile_id
        and strategy_id not in normalized_ids
    )
    if missing_current:
        raise RuntimeError(
            "Research profile is missing preregistered new hypotheses: "
            + ", ".join(missing_current)
        )

    return {
        "schema_version": TRIAL_REGISTRY_SCHEMA_VERSION,
        "profile_id": profile_id,
        "dataset_fingerprint": dataset_fingerprint,
        "current_candidate_ids": list(normalized_ids),
        "current_candidate_count": len(normalized_ids),
        "statistical_trial_count": len(registered),
        "registered_unique_strategy_ids": list(registered),
        "new_hypothesis_ids": [
            strategy_id
            for strategy_id in normalized_ids
            if _FIRST_SEEN_PROFILE.get(strategy_id) == profile_id
        ],
        "control_ids": [
            strategy_id
            for strategy_id in normalized_ids
            if _FIRST_SEEN_PROFILE.get(strategy_id) != profile_id
        ],
    }
