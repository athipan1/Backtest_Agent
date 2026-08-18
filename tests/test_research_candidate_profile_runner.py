from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import hourly_promotion_runner as promotion
from app.final_holdout import FinalHoldoutCriteria
from app.models import PriceBar
from app.pre_holdout_research import (
    _expected_rejection_stage,
    run_pre_holdout_research,
)
from scripts.run_research_candidate_profile import (
    install_research_profile,
    run_research_profile,
)


class Dumpable:
    def __init__(self, value):
        self.value = value

    def model_dump(self, mode="json"):
        return self.value


class FakeResult(Dumpable):
    def __init__(self, symbol: str):
        super().__init__({"symbols": [symbol], "metrics": {"return_pct": 0.10}})
        self.symbols = [symbol]


class FakeProvider:
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def fetch_bars(self, **kwargs):
        self.calls.append(kwargs)
        return self.bars


def _bars(count: int = 30) -> list[PriceBar]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        PriceBar(
            timestamp=start + timedelta(days=index),
            open=100 + index,
            high=102 + index,
            low=99 + index,
            close=101 + index,
            volume=100_000,
        )
        for index in range(count)
    ]


def _configure_runtime(monkeypatch, *, selection, pre_holdout=None):
    provider = FakeProvider(_bars())
    monkeypatch.delenv("PUBLISH_TO_DATABASE", raising=False)
    monkeypatch.setenv("BACKTEST_NESTED_MINIMUM_BARS", "10")
    monkeypatch.setattr(promotion, "_symbols_from_env", lambda: ["NVDA"])
    monkeypatch.setattr(
        promotion,
        "_default_date_range",
        lambda: ("2025-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    monkeypatch.setattr(
        promotion,
        "_final_holdout_criteria",
        lambda: FinalHoldoutCriteria(enabled=True, bars=20),
    )
    monkeypatch.setattr(
        promotion,
        "AlpacaMarketDataProvider",
        lambda **kwargs: provider,
    )
    monkeypatch.setattr(
        "app.pre_holdout_research.run_walk_forward_multi_strategy_backtest_v4",
        lambda request: selection(request),
    )
    monkeypatch.setattr(
        promotion,
        "run_backtest_with_risk",
        lambda request: FakeResult(request.symbols[0]),
    )
    monkeypatch.setattr(
        promotion,
        "run_statistical_validation",
        lambda *args, **kwargs: Dumpable(
            {"status": "completed", "passed": True, "gates": {"all": True}}
        ),
    )
    monkeypatch.setattr(
        promotion,
        "run_promotion_robustness",
        lambda request: Dumpable(
            {
                "status": "completed",
                "passed": True,
                "gates": {"all": True},
                "criteria": {},
            }
        ),
    )
    monkeypatch.setattr(
        promotion,
        "_pre_holdout_metadata",
        pre_holdout or (lambda *args, **kwargs: {"pre_holdout": "passed"}),
    )
    monkeypatch.setattr(
        promotion,
        "evaluate_sealed_final_holdout",
        lambda *args, **kwargs: pytest.fail("research must never evaluate holdout"),
    )
    monkeypatch.setattr(
        promotion,
        "publish_backtest_result",
        lambda *args, **kwargs: pytest.fail("research must never publish"),
    )
    monkeypatch.setattr(
        promotion,
        "DatabaseAgentClient",
        lambda *args, **kwargs: pytest.fail("research must never create Database client"),
    )
    return provider


def _eligible_selection(request):
    selected = request.candidates[4]
    return SimpleNamespace(
        best_eligible=SimpleNamespace(
            strategy_id=selected.strategy_id,
            effective_parameters={"strategy": selected.strategy},
        ),
        model_dump=lambda mode="json": {
            "selection_status": "eligible_strategy_found",
            "candidate_count": len(request.candidates),
        },
    )


def _ineligible_selection(request):
    return SimpleNamespace(
        best_eligible=None,
        model_dump=lambda mode="json": {
            "selection_status": "no_eligible_strategy",
            "candidate_count": len(request.candidates),
        },
    )


def test_install_profile_is_metadata_only_and_v5_is_default_research_shape():
    metadata = install_research_profile("strategy_research_v5")

    assert metadata["profile_id"] == "strategy_research_v5"
    assert metadata["candidate_count"] == 8
    assert metadata["candidate_ids"][-1] == "breakout-20-55-risk-v5"
    assert set(metadata["strategy_families"]) == {
        "sma_crossover",
        "trend_following",
        "mean_reversion",
        "breakout",
    }


def test_research_runner_keeps_holdout_sealed_for_pre_holdout_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider = _configure_runtime(monkeypatch, selection=_eligible_selection)
    report = tmp_path / "research.json"

    output = run_research_profile(
        profile_id="strategy_research_v5",
        report_path=report,
    )

    data = output["data"]
    assert output["status"] == "success"
    assert data["validation_profile"] == "nested_walk_forward_v4"
    assert data["pre_holdout_candidate_symbols"] == ["NVDA"]
    assert data["pre_holdout_candidate_count"] == 1
    assert data["holdout_reserved"] is True
    assert data["holdout_opened_count"] == 0
    assert data["database_publish_allowed"] is False
    assert data["promotion_allowed"] is False
    assert data["execution_allowed"] is False
    assert data["research_profile"]["candidate_count"] == 8
    item = data["items"][0]
    assert item["status"] == "pre_holdout_candidate"
    assert item["selected_strategy_id"] == "trend-following-10-50-risk-v5"
    assert item["sealed_holdout"] == {
        "enabled": True,
        "status": "sealed_not_opened",
        "bar_count": 20,
        "evaluation_allowed": False,
    }
    assert item["published"] is False
    assert item["promoted"] is False
    assert item["pre_holdout_metadata"]["validation_profile"] == "nested_walk_forward_v4"
    assert provider.calls[0]["minimum_bars"] == 30
    assert json.loads(report.read_text(encoding="utf-8"))["data"] == data
    assert (report.parent / "research-nvda.json").exists()


def test_no_eligible_candidate_is_safe_no_trade_and_skips_full_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _configure_runtime(monkeypatch, selection=_ineligible_selection)
    monkeypatch.setattr(
        promotion,
        "run_backtest_with_risk",
        lambda request: pytest.fail("no-eligible path must stop before full validation"),
    )

    output = run_pre_holdout_research(
        profile_id="strategy_research_v5",
        report_path=tmp_path / "research.json",
    )

    item = output["data"]["items"][0]
    assert output["status"] == "success"
    assert item["status"] == "no_eligible_strategy"
    assert item["rejection_stage"] == "nested_selection"
    assert item["sealed_holdout"]["status"] == "sealed_not_opened"
    assert output["data"]["ineligible_symbols"] == ["NVDA"]
    assert output["data"]["failed_symbols"] == []


def test_expected_pre_holdout_rejection_is_safe_and_holdout_stays_sealed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def reject(*args, **kwargs):
        raise RuntimeError("selected strategy statistical validation did not pass")

    _configure_runtime(
        monkeypatch,
        selection=_eligible_selection,
        pre_holdout=reject,
    )

    output = run_pre_holdout_research(
        profile_id="strategy_research_v5",
        report_path=tmp_path / "research.json",
    )

    item = output["data"]["items"][0]
    assert output["status"] == "success"
    assert item["status"] == "no_eligible_strategy"
    assert item["selected_strategy_id"] == "trend-following-10-50-risk-v5"
    assert item["rejection_stage"] == "statistical_validation"
    assert item["sealed_holdout"]["evaluation_allowed"] is False
    assert item["statistical_evidence"]["passed"] is True
    assert item["published"] is False


def test_unknown_runtime_failure_remains_operational_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def explode(*args, **kwargs):
        raise RuntimeError("unexpected research runtime failure")

    _configure_runtime(
        monkeypatch,
        selection=_eligible_selection,
        pre_holdout=explode,
    )

    output = run_pre_holdout_research(
        profile_id="strategy_research_v5",
        report_path=tmp_path / "research.json",
    )

    assert output["status"] == "error"
    assert output["data"]["failed_symbols"] == ["NVDA"]
    assert output["data"]["holdout_opened_count"] == 0
    assert output["data"]["items"][0]["status"] == "failed"
    assert "unexpected research runtime failure" in output["data"]["items"][0]["error"]


def test_research_runner_refuses_database_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("PUBLISH_TO_DATABASE", "true")

    with pytest.raises(RuntimeError, match="refuses PUBLISH_TO_DATABASE=true"):
        run_research_profile(
            profile_id="strategy_research_v5",
            report_path=tmp_path / "research.json",
        )


def test_research_runner_requires_reserved_holdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("PUBLISH_TO_DATABASE", raising=False)
    monkeypatch.setattr(promotion, "_symbols_from_env", lambda: ["NVDA"])
    monkeypatch.setattr(
        promotion,
        "_final_holdout_criteria",
        lambda: FinalHoldoutCriteria(enabled=False, bars=20),
    )

    with pytest.raises(RuntimeError, match="requires BACKTEST_FINAL_HOLDOUT_ENABLED=true"):
        run_pre_holdout_research(
            profile_id="strategy_research_v5",
            report_path=tmp_path / "research.json",
        )


def test_expected_rejection_classifier_is_fail_closed():
    assert (
        _expected_rejection_stage(
            RuntimeError("selected strategy robustness validation did not pass: fee_stress")
        )
        == "robustness_validation"
    )
    assert _expected_rejection_stage(RuntimeError("network timeout")) is None
