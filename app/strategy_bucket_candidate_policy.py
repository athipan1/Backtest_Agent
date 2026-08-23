from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.multi_strategy import MultiStrategyCandidate, default_multi_strategy_candidates

POLICY_SCHEMA = "strategy-bucket-candidate-policy.v1"
SUPPORTED_BUCKETS = frozenset({"core_dividend", "value_rebound", "news_momentum"})
DEFAULT_MANAGER_PRESELECTION_PATH = Path("reports/hourly-pre-backtest-discovery.json")

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
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": POLICY_SCHEMA,
            "applied": self.applied,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "source": self.source,
            "symbol_buckets": dict(self.symbol_buckets),
            "bucket_strategy_ids": {
                bucket: list(strategy_ids)
                for bucket, strategy_ids in BUCKET_STRATEGY_IDS.items()
            },
            "fail_closed": True,
        }


def _bool_text(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _configured_report_path() -> Path:
    configured = os.getenv("BACKTEST_STRATEGY_BUCKET_REPORT_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_MANAGER_PRESELECTION_PATH


def _enabled() -> bool:
    configured = os.getenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED")
    if configured is not None:
        return _bool_text(configured)
    return _configured_report_path().exists()


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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_manager_symbol_buckets(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise RuntimeError("Manager preselection report root must be a JSON object")

    response = _dict(payload.get("response"))
    data = _dict(response.get("data"))
    positions = data.get("pre_backtest_selected_positions")
    if not isinstance(positions, list):
        raise RuntimeError(
            "Manager preselection report is missing pre_backtest_selected_positions"
        )

    expected_symbols = [
        str(symbol or "").strip().upper()
        for symbol in payload.get("backtest_symbols") or []
        if str(symbol or "").strip()
    ]
    raw_map: dict[str, str] = {}
    for row in positions:
        if not isinstance(row, dict):
            raise RuntimeError("Manager preselection position must be a JSON object")
        symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        bucket = str(row.get("strategy_bucket") or row.get("bucket") or "").strip().lower()
        if not symbol:
            raise RuntimeError("Manager preselection position is missing symbol")
        if row.get("evidence_gate_passed") is not True:
            raise RuntimeError(f"Manager evidence gate did not pass for {symbol}")
        if row.get("bucket_classification_status") != "classified":
            raise RuntimeError(
                f"Manager strategy bucket is not classified for {symbol}: "
                f"{row.get('bucket_classification_status')!r}"
            )
        if symbol in raw_map and raw_map[symbol] != bucket:
            raise RuntimeError(f"Manager report contains conflicting strategy buckets for {symbol}")
        raw_map[symbol] = bucket

    normalized = _normalize_symbol_buckets(raw_map)
    if expected_symbols and set(normalized) != set(expected_symbols):
        missing = sorted(set(expected_symbols) - set(normalized))
        unexpected = sorted(set(normalized) - set(expected_symbols))
        raise RuntimeError(
            "Manager strategy bucket map does not match Backtest symbols: "
            f"missing={missing} unexpected={unexpected}"
        )
    return normalized


def _load_symbol_buckets() -> tuple[dict[str, str], str]:
    raw = os.getenv("BACKTEST_STRATEGY_BUCKETS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("BACKTEST_STRATEGY_BUCKETS_JSON is not valid JSON") from exc
        return _normalize_symbol_buckets(parsed), "env:BACKTEST_STRATEGY_BUCKETS_JSON"

    report_path = _configured_report_path()
    if not report_path.exists():
        raise RuntimeError(
            "Strategy bucket-aware Backtest requires BACKTEST_STRATEGY_BUCKETS_JSON "
            f"or Manager preselection report {report_path}"
        )
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Manager preselection report is invalid JSON: {report_path}") from exc
    return _extract_manager_symbol_buckets(payload), f"manager_report:{report_path}"


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
            reason="strategy_bucket_policy_disabled_or_manager_report_absent",
            symbol_buckets={},
        )
    symbol_buckets, source = _load_symbol_buckets()
    return StrategyBucketCandidatePolicy(
        applied=True,
        reason="manager_strategy_bucket_map_applied",
        symbol_buckets=symbol_buckets,
        policy_id=_policy_id(symbol_buckets),
        source=source,
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
    """Intersect Manager's per-symbol bucket with any later candidate policy.

    Apply this hook before the Market Regime policy. The Market Regime hook may then
    supply its own candidate allow-list; this wrapper intersects that allow-list with
    the Manager bucket instead of letting either policy override the other. No
    Backtest scoring, nested walk-forward, statistics, robustness, sealed holdout,
    promotion, Risk, or Execution gate is relaxed.
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
