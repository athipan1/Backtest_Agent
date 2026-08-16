from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.market_regime_candidate_policy import (
    _context_path,
    apply_runtime_market_regime_candidate_policy,
    resolve_market_regime_candidate_policy,
)


def _context(
    tmp_path: Path,
    *,
    decision: str = "PASS",
    new_entries_allowed: bool = True,
    recommended_action: str = "trade",
    allowed: list[str] | None = None,
) -> Path:
    path = tmp_path / "hourly-position-review.json"
    path.write_text(
        json.dumps(
            {
                "market_strategy": {
                    "regime": "bull",
                    "risk_level": "low",
                    "recommended_action": recommended_action,
                    "recommended_strategy": "trend_following",
                    "allowed_strategies": allowed
                    if allowed is not None
                    else ["trend_following", "breakout", "sma_crossover"],
                },
                "market_regime_gate": {
                    "gate_version": "manager-market-regime-gate.v1",
                    "decision": decision,
                    "new_entries_allowed": new_entries_allowed,
                    "recommended_action": recommended_action,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_missing_market_context_preserves_balanced_default(tmp_path: Path):
    policy, candidates = resolve_market_regime_candidate_policy(
        tmp_path / "missing.json"
    )

    assert policy.applied is False
    assert policy.reason == "market_context_not_available"
    assert candidates == ()


def test_context_path_finds_manager_report_in_sibling_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = tmp_path / "workspace"
    backtest_root = workspace / "Backtest_Agent"
    manager_reports = workspace / "Manager_Agent" / "reports"
    backtest_root.mkdir(parents=True)
    manager_reports.mkdir(parents=True)
    expected = manager_reports / "hourly-position-review.json"
    expected.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(backtest_root)
    monkeypatch.delenv("BACKTEST_MARKET_CONTEXT_PATH", raising=False)

    resolved = _context_path()

    assert resolved.resolve() == expected.resolve()


def test_explicit_context_path_remains_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    configured = tmp_path / "configured.json"
    monkeypatch.setenv("BACKTEST_MARKET_CONTEXT_PATH", str(configured))

    assert _context_path() == configured


def test_bull_context_filters_only_blocked_balanced_candidate(tmp_path: Path):
    path = _context(tmp_path)

    first, candidates = resolve_market_regime_candidate_policy(path)
    second, _ = resolve_market_regime_candidate_policy(path)

    assert first.applied is True
    assert first.policy_id == second.policy_id
    assert first.regime == "bull"
    assert first.allowed_strategies == (
        "trend_following",
        "breakout",
        "sma_crossover",
    )
    assert [candidate.strategy for candidate in candidates] == [
        "sma_crossover",
        "trend_following",
        "breakout",
    ]
    assert "mean-reversion-balanced-v1" not in first.candidate_ids


def test_non_tradeable_context_does_not_override_research_candidates(tmp_path: Path):
    path = _context(
        tmp_path,
        decision="BLOCK",
        new_entries_allowed=False,
        recommended_action="no_trade",
        allowed=[],
    )

    policy, candidates = resolve_market_regime_candidate_policy(path)

    assert policy.applied is False
    assert policy.reason == "market_context_not_tradeable"
    assert candidates == ()


def test_tradeable_context_rejects_unknown_strategy_contract(tmp_path: Path):
    path = _context(tmp_path, allowed=["trend_following", "future_magic"])

    with pytest.raises(RuntimeError, match="unsupported Backtest strategies"):
        resolve_market_regime_candidate_policy(path)


def test_tradeable_context_rejects_empty_allow_list(tmp_path: Path):
    path = _context(tmp_path, allowed=[])

    with pytest.raises(RuntimeError, match="cannot have an empty strategy allow-list"):
        resolve_market_regime_candidate_policy(path)


def test_runtime_hook_filters_request_and_binds_policy_to_evidence_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = _context(tmp_path)
    monkeypatch.setenv("BACKTEST_MARKET_CONTEXT_PATH", str(path))
    calls: dict[str, object] = {}

    class FakeRequest:
        def __init__(self, **kwargs):
            self.candidates = kwargs["candidates"]
            self.kwargs = kwargs

    def original_run_id(**kwargs):
        calls["run_id_strategy"] = kwargs["strategy_id"]
        return "run-id"

    def original_publish(**kwargs):
        calls["metadata"] = kwargs["metadata"]
        return "published"

    runner = SimpleNamespace(
        WalkForwardMultiStrategyRequest=FakeRequest,
        _run_id=original_run_id,
        publish_backtest_result=original_publish,
    )

    policy = apply_runtime_market_regime_candidate_policy(runner)
    request = runner.WalkForwardMultiStrategyRequest(symbols=["ALL"])
    result = runner._run_id(
        symbol="ALL",
        strategy_id="trend-following-balanced-v1",
        fingerprint="a",
        research_fingerprint="b",
        effective_parameters={},
        timeframe="1d",
        promotion_metadata={},
    )
    published = runner.publish_backtest_result(
        metadata={"selection_profile": "balanced_v1"}
    )

    assert policy.applied is True
    assert [candidate.strategy for candidate in request.candidates] == [
        "sma_crossover",
        "trend_following",
        "breakout",
    ]
    assert result == "run-id"
    assert f"candidate-policy={policy.policy_id}" in str(calls["run_id_strategy"])
    assert published == "published"
    metadata = calls["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["selection_profile"] == "market_regime_filtered_balanced_v1"
    assert metadata["market_regime_candidate_policy"]["policy_id"] == policy.policy_id
    assert runner.MARKET_REGIME_CANDIDATE_POLICY["applied"] is True


def test_runtime_hook_is_noop_when_market_context_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(
        "BACKTEST_MARKET_CONTEXT_PATH",
        str(tmp_path / "missing.json"),
    )
    original_request = object()
    original_run_id = object()
    original_publish = object()
    runner = SimpleNamespace(
        WalkForwardMultiStrategyRequest=original_request,
        _run_id=original_run_id,
        publish_backtest_result=original_publish,
    )

    policy = apply_runtime_market_regime_candidate_policy(runner)

    assert policy.applied is False
    assert runner.WalkForwardMultiStrategyRequest is original_request
    assert runner._run_id is original_run_id
    assert runner.publish_backtest_result is original_publish
    assert runner.MARKET_REGIME_CANDIDATE_POLICY["reason"] == "market_context_not_available"
