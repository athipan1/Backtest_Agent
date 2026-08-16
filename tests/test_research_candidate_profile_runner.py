from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import hourly_promotion_runner
from scripts.run_research_candidate_profile import run_research_profile


def test_research_runner_injects_profile_and_disables_publish_and_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    original_request_class = hourly_promotion_runner.WalkForwardMultiStrategyRequest
    monkeypatch.setattr(
        hourly_promotion_runner,
        "WalkForwardMultiStrategyRequest",
        original_request_class,
    )
    monkeypatch.delenv("PUBLISH_TO_DATABASE", raising=False)
    observed: dict[str, object] = {}

    def fake_nested(report_path: Path):
        request = hourly_promotion_runner.WalkForwardMultiStrategyRequest(
            **hourly_promotion_runner._request_kwargs(symbol="ALL", bars=[])
        )
        observed["candidate_ids"] = [
            candidate.strategy_id for candidate in request.candidates
        ]
        observed["publish"] = __import__("os").environ.get("PUBLISH_TO_DATABASE")
        return {
            "status": "success",
            "data": {
                "mode": "nested_walk_forward_multi_strategy_selection",
                "items": [],
            },
            "error": None,
        }

    monkeypatch.setattr(
        hourly_promotion_runner,
        "run_nested_hourly_backtest",
        fake_nested,
    )
    report = tmp_path / "research.json"

    output = run_research_profile(
        profile_id="bull_research_v1",
        report_path=report,
    )

    assert observed["publish"] == "false"
    assert observed["candidate_ids"] == [
        "sma-crossover-bull-fast-v1",
        "sma-crossover-balanced-v1",
        "trend-following-bull-fast-v1",
        "trend-following-balanced-v1",
        "breakout-bull-fast-v1",
        "breakout-balanced-v1",
    ]
    data = output["data"]
    assert data["research_only"] is True
    assert data["database_publish_allowed"] is False
    assert data["promotion_allowed"] is False
    assert data["execution_allowed"] is False
    assert data["research_profile"]["candidate_count"] == 6
    assert json.loads(report.read_text(encoding="utf-8"))["data"] == data


def test_research_runner_refuses_database_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("PUBLISH_TO_DATABASE", "true")

    with pytest.raises(RuntimeError, match="refuses PUBLISH_TO_DATABASE=true"):
        run_research_profile(
            profile_id="bull_research_v1",
            report_path=tmp_path / "research.json",
        )
