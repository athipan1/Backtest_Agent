from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.multi_strategy import MultiStrategyCandidate, default_multi_strategy_candidates

POLICY_SCHEMA = "strategy-bucket-candidate-policy.v1"
SUPPORTED_BUCKETS = frozenset({"core_dividend", "value_rebound", "news_momentum"})

BUCKET_STRATEGY_IDS: dict[str, tuple[str, ...]] = {
    "core_dividend": (
        "trend-following-balanced-v1",
        "sma-crossover-balanced-v1",
    ),
    "value_rebound": (
        "mean-reversion-balanced-v1",
        "sma-crossover-balanced-v1",
    ),
    "news_momentum": (
        "breakout-balanced-v1",
        "trend-following-balanced-v1",
    ),
}


@dataclass(frozen=True)
class StrategyBucketCandidatePolicy:
    applied: bool
    reason: str
    symbol_buckets: Mapping[str, str]
    policy_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": POLICY_SCHEMA,
            "applied": self.applied,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "symbol_buckets": dict(self.symbol_buckets),
            "bucket_strategy_ids": {
                bucket: list(strategy_ids)
                for bucket, strategy_ids in BUCKET_STRATEGY_IDS.items()
            },
            "fail_closed": True,
        }


def _enabled() -> bool:
    return os.getenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _normalize_symbol_buckets(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise RuntimeError("Strategy bucket map must be a JSON object")

    normalized: dict[str, str] = {}
    for raw_symbol, raw_bucket in raw.items():
        symbol = str(raw_symbol or "").strip().upper()
        bucket = str(raw_bucket or "").strip().lower()
        if not symbol:
            raise RuntimeError("Strategy bucket map contains an empty symbol")
        if bucket not in SUPPORTED_BUCKETS:
            raise RuntimeError(
                f"Unsupported strategy bucket for {symbol}: {bucket or '<empty>'}"
            )
        if symbol in normalized and normalized[symbol] != bucket:
            raise RuntimeError(f"Conflicting strategy buckets for {symbol}")
        normalized[symbol] = bucket

    if not normalized:
        raise RuntimeError("Strategy bucket-aware Backtest requires at least one symbol bucket")
    return normalized


def _load_symbol_buckets() -> dict[str, str]:
    raw = os.getenv("BACKTEST_STRATEGY_BUCKETS_JSON", "").strip()
    if not raw:
        raise RuntimeError(
            "BACKTEST_STRATEGY_BUCKETS_JSON is required when strategy bucket-aware Backtest is enabled"
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("BACKTEST_STRATEGY_BUCKETS_JSON is not valid JSON") from exc
    return _normalize_symbol_buckets(parsed)


def _policy_id(symbol_buckets: Mapping[str, str]) -> str:
    identity = {
        "schema_version": POLICY_SCHEMA,
        "symbol_buckets": dict(sorted(symbol_buckets.items())),
        "bucket_strategy_ids": {
            bucket: list(strategy_ids)
            for bucket, strategy_ids in sorted(BUCKET_STRATEGY_IDS.items())
        },
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"strategy-bucket-{digest[:16]}"


def resolve_strategy_bucket_candidate_policy() -> StrategyBucketCandidatePolicy:
    if not _enabled():
        return StrategyBucketCandidatePolicy(
            applied=False,
            reason="strategy_bucket_policy_disabled",
            symbol_buckets={},
        )
    symbol_buckets = _load_symbol_buckets()
    return StrategyBucketCandidatePolicy(
        applied=True,
        reason="manager_strategy_bucket_map_applied",
        symbol_buckets=symbol_buckets,
        policy_id=_policy_id(symbol_buckets),
    )


def strategy_ids_for_bucket(bucket: str) -> tuple[str, ...]:
    normalized = str(bucket or "").strip().lower()
    try:
        return BUCKET_STRATEGY_IDS[normalized]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported strategy bucket: {normalized or '<empty>'}") from exc


def _symbol_from_request_kwargs(kwargs: Mapping[str, Any]) -> str:
    symbols = kwargs.get("symbols")
    if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)) or len(symbols) != 1:
        raise RuntimeError("Strategy bucket policy requires exactly one Backtest symbol")
    symbol = str(symbols[0] or "").strip().upper()
    if not symbol:
        raise RuntimeError("Strategy bucket policy received an empty Backtest symbol")
    return symbol


def _candidate_id(candidate: Any) -> str:
    return str(getattr(candidate, "strategy_id", "") or "")


def _filter_candidates(
    *,
    source_candidates: Sequence[MultiStrategyCandidate],
    allowed_strategy_ids: Sequence[str],
) -> list[MultiStrategyCandidate]:
    allowed = set(allowed_strategy_ids)
    selected = [
        candidate.model_copy(deep=True)
        for candidate in source_candidates
        if _candidate_id(candidate) in allowed
    ]
    if not selected:
        raise RuntimeError(
            "Strategy bucket and upstream candidate policies have no common Backtest strategy"
        )
    return selected


def apply_strategy_bucket_candidate_policy(runner_module: Any) -> StrategyBucketCandidatePolicy:
    """Intersect Manager's strategy bucket with any later candidate policy.

    Apply this hook before the Market Regime policy. The Market Regime hook may then
    supply its own candidate allow-list; this wrapper intersects that allow-list with
    the per-symbol Manager bucket instead of letting either policy override the other.
    No Backtest scoring, walk-forward, statistics, holdout, promotion, Risk, or
    Execution gate is relaxed.
    """

    policy = resolve_strategy_bucket_candidate_policy()
    setattr(runner_module, "STRATEGY_BUCKET_CANDIDATE_POLICY", policy.as_dict())
    if not policy.applied:
        return policy

    request_class = runner_module.WalkForwardMultiStrategyRequest
    original_run_id = runner_module._run_id
    original_publish = runner_module.publish_backtest_result

    def policy_request_factory(**kwargs: Any):
        symbol = _symbol_from_request_kwargs(kwargs)
        bucket = policy.symbol_buckets.get(symbol)
        if bucket is None:
            raise RuntimeError(
                f"Manager strategy bucket map is missing Backtest symbol {symbol}"
            )
        allowed_ids = strategy_ids_for_bucket(bucket)
        supplied = kwargs.pop("candidates", None)
        source_candidates = (
            list(supplied)
            if supplied is not None
            else default_multi_strategy_candidates()
        )
        candidates = _filter_candidates(
            source_candidates=source_candidates,
            allowed_strategy_ids=allowed_ids,
        )
        return request_class(candidates=candidates, **kwargs)

    def policy_run_id(**kwargs: Any) -> str:
        policy_id = policy.policy_id
        if not policy_id:
            raise RuntimeError("Applied strategy bucket policy is missing policy_id")
        symbol = str(kwargs.get("symbol") or "").strip().upper()
        bucket = policy.symbol_buckets.get(symbol)
        if bucket is None:
            raise RuntimeError(f"Strategy bucket run identity is missing symbol {symbol}")
        identity_strategy = (
            f"{kwargs['strategy_id']}::strategy-bucket={bucket}::bucket-policy={policy_id}"
        )
        return original_run_id(**{**kwargs, "strategy_id": identity_strategy})

    def policy_publish(**kwargs: Any):
        request = kwargs.get("request")
        symbols = getattr(request, "symbols", None)
        symbol = str(symbols[0] if symbols else "").strip().upper()
        bucket = policy.symbol_buckets.get(symbol)
        if bucket is None:
            raise RuntimeError(f"Strategy bucket publish metadata is missing symbol {symbol}")
        metadata = dict(kwargs.get("metadata") or {})
        metadata.update(
            {
                "strategy_bucket_candidate_policy": {
                    **policy.as_dict(),
                    "symbol": symbol,
                    "strategy_bucket": bucket,
                    "allowed_strategy_ids": list(strategy_ids_for_bucket(bucket)),
                }
            }
        )
        return original_publish(**{**kwargs, "metadata": metadata})

    runner_module.WalkForwardMultiStrategyRequest = policy_request_factory
    runner_module._run_id = policy_run_id
    runner_module.publish_backtest_result = policy_publish
    return policy
