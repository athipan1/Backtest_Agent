from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.multi_strategy import MultiStrategyCandidate, default_multi_strategy_candidates

_SUPPORTED_STRATEGIES = {
    "sma_crossover",
    "trend_following",
    "mean_reversion",
    "breakout",
}
_DEFAULT_CONTEXT_PATH = Path("reports/hourly-position-review.json")
_MANAGER_CONTEXT_RELATIVE_PATH = Path("Manager_Agent/reports/hourly-position-review.json")
_POLICY_SCHEMA = "market-regime-candidate-policy.v1"


@dataclass(frozen=True)
class MarketRegimeCandidatePolicy:
    applied: bool
    reason: str
    policy_id: str | None = None
    regime: str | None = None
    risk_level: str | None = None
    recommended_strategy: str | None = None
    allowed_strategies: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    source_path: str | None = None
    source_gate_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _POLICY_SCHEMA,
            "applied": self.applied,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "regime": self.regime,
            "risk_level": self.risk_level,
            "recommended_strategy": self.recommended_strategy,
            "allowed_strategies": list(self.allowed_strategies),
            "candidate_ids": list(self.candidate_ids),
            "source_path": self.source_path,
            "source_gate_version": self.source_gate_version,
        }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _context_path() -> Path:
    configured = os.getenv("BACKTEST_MARKET_CONTEXT_PATH", "").strip()
    if configured:
        return Path(configured)

    cwd = Path.cwd()
    repo_root = Path(__file__).resolve().parents[1]
    candidates = _unique_paths(
        [
            _DEFAULT_CONTEXT_PATH,
            cwd / _DEFAULT_CONTEXT_PATH,
            cwd.parent / _MANAGER_CONTEXT_RELATIVE_PATH,
            repo_root.parent / _MANAGER_CONTEXT_RELATIVE_PATH,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _policy_id(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"regime-allowlist-{digest[:16]}"


def _balanced_candidates_for(
    allowed_strategies: tuple[str, ...],
) -> tuple[MultiStrategyCandidate, ...]:
    allowed = set(allowed_strategies)
    return tuple(
        candidate
        for candidate in default_multi_strategy_candidates()
        if candidate.strategy in allowed
    )


def resolve_market_regime_candidate_policy(
    path: Path | None = None,
) -> tuple[MarketRegimeCandidatePolicy, tuple[MultiStrategyCandidate, ...]]:
    source = path or _context_path()
    if not source.exists():
        return (
            MarketRegimeCandidatePolicy(
                applied=False,
                reason="market_context_not_available",
                source_path=str(source),
            ),
            (),
        )

    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Market context root must be a JSON object")

    strategy = _dict(payload.get("market_strategy"))
    gate = _dict(payload.get("market_regime_gate"))
    tradeable = (
        gate.get("decision") == "PASS"
        and gate.get("new_entries_allowed") is True
        and gate.get("recommended_action") == "trade"
        and strategy.get("recommended_action") == "trade"
    )
    if not tradeable:
        return (
            MarketRegimeCandidatePolicy(
                applied=False,
                reason="market_context_not_tradeable",
                regime=str(strategy.get("regime") or "") or None,
                risk_level=str(strategy.get("risk_level") or "") or None,
                recommended_strategy=(
                    str(strategy.get("recommended_strategy") or "") or None
                ),
                source_path=str(source),
                source_gate_version=(str(gate.get("gate_version") or "") or None),
            ),
            (),
        )

    raw_allowed = strategy.get("allowed_strategies")
    if not isinstance(raw_allowed, list):
        raise RuntimeError("Tradeable Market Regime context requires allowed_strategies")
    allowed = tuple(
        dict.fromkeys(
            str(item).strip().lower()
            for item in raw_allowed
            if str(item).strip()
        )
    )
    if not allowed:
        raise RuntimeError(
            "Tradeable Market Regime context cannot have an empty strategy allow-list"
        )
    unknown = sorted(set(allowed) - _SUPPORTED_STRATEGIES)
    if unknown:
        raise RuntimeError(
            "Market Regime allow-list contains unsupported Backtest strategies: "
            + ", ".join(unknown)
        )

    candidates = _balanced_candidates_for(allowed)
    if not candidates:
        raise RuntimeError("Market Regime allow-list resolved to no Backtest candidates")
    candidate_ids = tuple(str(candidate.strategy_id) for candidate in candidates)
    identity = {
        "schema_version": _POLICY_SCHEMA,
        "regime": strategy.get("regime"),
        "risk_level": strategy.get("risk_level"),
        "allowed_strategies": list(allowed),
        "candidate_ids": list(candidate_ids),
        "source_gate_version": gate.get("gate_version"),
    }
    policy = MarketRegimeCandidatePolicy(
        applied=True,
        reason="market_regime_allow_list_applied",
        policy_id=_policy_id(identity),
        regime=str(strategy.get("regime") or "") or None,
        risk_level=str(strategy.get("risk_level") or "") or None,
        recommended_strategy=(
            str(strategy.get("recommended_strategy") or "") or None
        ),
        allowed_strategies=allowed,
        candidate_ids=candidate_ids,
        source_path=str(source.resolve(strict=False)),
        source_gate_version=(str(gate.get("gate_version") or "") or None),
    )
    return policy, candidates


def apply_runtime_market_regime_candidate_policy(
    runner_module: Any,
) -> MarketRegimeCandidatePolicy:
    """Inject a trusted Manager regime allow-list without relaxing any Backtest gate."""

    policy, candidates = resolve_market_regime_candidate_policy()
    setattr(runner_module, "MARKET_REGIME_CANDIDATE_POLICY", policy.as_dict())
    if not policy.applied:
        return policy

    request_class = runner_module.WalkForwardMultiStrategyRequest
    original_run_id = runner_module._run_id
    original_publish = runner_module.publish_backtest_result

    def policy_request_factory(**kwargs: Any):
        if "candidates" in kwargs:
            raise RuntimeError(
                "Market Regime candidate policy refuses an overlapping candidate override"
            )
        return request_class(
            candidates=[candidate.model_copy(deep=True) for candidate in candidates],
            **kwargs,
        )

    def policy_run_id(**kwargs: Any) -> str:
        policy_id = policy.policy_id
        if not policy_id:
            raise RuntimeError(
                "Applied Market Regime candidate policy is missing policy_id"
            )
        identity_strategy = f"{kwargs['strategy_id']}::candidate-policy={policy_id}"
        return original_run_id(**{**kwargs, "strategy_id": identity_strategy})

    def policy_publish(**kwargs: Any):
        metadata = dict(kwargs.get("metadata") or {})
        metadata.update(
            {
                "selection_profile": "market_regime_filtered_balanced_v1",
                "market_regime_candidate_policy": policy.as_dict(),
            }
        )
        return original_publish(**{**kwargs, "metadata": metadata})

    runner_module.WalkForwardMultiStrategyRequest = policy_request_factory
    runner_module._run_id = policy_run_id
    runner_module.publish_backtest_result = policy_publish
    return policy
