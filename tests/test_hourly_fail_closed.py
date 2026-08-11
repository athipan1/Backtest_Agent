import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_hourly_backtest as runner


class FakeResponse:
    def __init__(self, *, published: bool, publish_status: str):
        self.data = SimpleNamespace(
            published=published,
            publish_status=publish_status,
        )

    def model_dump(self, mode="python"):
        return {
            "status": "success" if self.data.published else "error",
            "data": {
                "published": self.data.published,
                "publish_status": self.data.publish_status,
            },
        }


def _payload(*, publish_to_database: bool) -> dict:
    return {
        "account_id": "1",
        "run_id": "single-run-1",
        "skill_id": "skill-1",
        "strategy_id": "strategy-1",
        "timeframe": "1d",
        "publish_to_database": publish_to_database,
        "symbols": ["AAPL"],
        "initial_equity": 100000,
        "fast_window": 2,
        "slow_window": 3,
        "fee_bps": 0,
        "slippage_bps": 0,
        "bars": {
            "AAPL": [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "volume": 1000,
                },
                {
                    "timestamp": "2026-01-02T00:00:00Z",
                    "open": 11,
                    "high": 12,
                    "low": 10,
                    "close": 11,
                    "volume": 1000,
                },
                {
                    "timestamp": "2026-01-03T00:00:00Z",
                    "open": 12,
                    "high": 13,
                    "low": 11,
                    "close": 12,
                    "volume": 1000,
                },
            ]
        },
    }


def _set_legacy_research(monkeypatch) -> None:
    monkeypatch.setenv("BACKTEST_MODE", "legacy_fixed")
    monkeypatch.setenv("BACKTEST_ENVIRONMENT", "research")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")


def test_scheduled_defaults_to_nested_promotion(monkeypatch):
    monkeypatch.delenv("BACKTEST_MODE", raising=False)
    monkeypatch.delenv("BACKTEST_ENVIRONMENT", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    environment = runner._runtime_environment()

    assert environment == "production"
    assert runner._resolve_backtest_mode(environment) == "nested_promotion"


def test_manual_defaults_to_nested_promotion(monkeypatch):
    monkeypatch.delenv("BACKTEST_MODE", raising=False)
    monkeypatch.delenv("BACKTEST_ENVIRONMENT", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    environment = runner._runtime_environment()

    assert environment == "research"
    assert runner._resolve_backtest_mode(environment) == "nested_promotion"


def test_invalid_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("BACKTEST_MODE", "best_effort")
    monkeypatch.setenv("BACKTEST_ENVIRONMENT", "research")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    with pytest.raises(ValueError, match="Unsupported BACKTEST_MODE"):
        runner._resolve_backtest_mode()


def test_invalid_runtime_environment_is_rejected(monkeypatch):
    monkeypatch.delenv("BACKTEST_MODE", raising=False)
    monkeypatch.setenv("BACKTEST_ENVIRONMENT", "staging")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    with pytest.raises(ValueError, match="Unsupported BACKTEST_ENVIRONMENT"):
        runner._runtime_environment()


def test_scheduled_run_cannot_override_environment_to_research(monkeypatch):
    monkeypatch.setenv("BACKTEST_ENVIRONMENT", "research")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    with pytest.raises(ValueError, match="cannot override"):
        runner._runtime_environment()


def test_legacy_mode_is_explicit_research_only(monkeypatch):
    _set_legacy_research(monkeypatch)

    environment = runner._runtime_environment()

    assert runner._resolve_backtest_mode(environment) == "legacy_fixed"


def test_production_cannot_run_legacy(monkeypatch):
    monkeypatch.setenv("BACKTEST_MODE", "legacy_fixed")
    monkeypatch.setenv("BACKTEST_ENVIRONMENT", "production")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    with pytest.raises(RuntimeError, match="Production Backtests require"):
        runner._resolve_backtest_mode()


def test_schedule_cannot_run_legacy_even_with_direct_research_argument(monkeypatch):
    monkeypatch.setenv("BACKTEST_MODE", "legacy_fixed")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    with pytest.raises(RuntimeError, match="Scheduled hourly Backtests cannot"):
        runner._resolve_backtest_mode("research")


def test_nested_failure_does_not_fallback_to_legacy(monkeypatch, tmp_path):
    from scripts import run_nested_hourly_backtest as nested_runner

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BACKTEST_MODE", "nested_promotion")
    monkeypatch.setenv("BACKTEST_ENVIRONMENT", "research")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr(
        runner,
        "_load_payload",
        lambda: pytest.fail("legacy payload loader must not run"),
    )
    monkeypatch.setattr(
        nested_runner,
        "main",
        lambda: (_ for _ in ()).throw(RuntimeError("nested failed")),
    )

    with pytest.raises(RuntimeError, match="nested failed"):
        runner.main()


def test_nested_report_records_mode_and_validation_path(monkeypatch, tmp_path):
    from scripts import run_nested_hourly_backtest as nested_runner

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BACKTEST_MODE", "nested_promotion")
    monkeypatch.setenv("BACKTEST_ENVIRONMENT", "research")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    report_path = tmp_path / "reports" / "hourly-backtest-result.json"

    def _nested_main() -> None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps({"status": "success", "data": {"mode": "nested"}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(nested_runner, "main", _nested_main)

    runner.main()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runtime"]["backtest_mode"] == "nested_promotion"
    assert report["runtime"]["automatic_fallback_allowed"] is False
    assert report["runtime"]["validation_path"] == [
        "nested_walk_forward",
        "statistical_validation",
        "robustness",
        "promotion_lifecycle",
    ]


def test_annotate_existing_report_ignores_missing_file(tmp_path):
    runner._annotate_existing_report(
        tmp_path / "missing.json",
        mode="nested_promotion",
        environment="research",
    )


def test_annotate_existing_report_rejects_non_object(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="report root"):
        runner._annotate_existing_report(
            report_path,
            mode="nested_promotion",
            environment="research",
        )


def test_hourly_single_symbol_exits_nonzero_when_required_publish_is_skipped(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    _set_legacy_research(monkeypatch)
    monkeypatch.setattr(
        runner,
        "_load_payload",
        lambda: _payload(publish_to_database=True),
    )
    monkeypatch.setattr(
        runner,
        "backtest_run_and_publish",
        lambda request: FakeResponse(
            published=False,
            publish_status="skipped",
        ),
    )

    with pytest.raises(SystemExit, match="publish failed or was skipped"):
        runner.main()

    report_path = tmp_path / "reports" / "hourly-backtest-result.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runtime"]["backtest_mode"] == "legacy_fixed"
    assert report["runtime"]["validation_path"] == ["legacy_fixed"]


def test_hourly_single_symbol_allows_explicit_storage_skip(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    _set_legacy_research(monkeypatch)
    monkeypatch.setattr(
        runner,
        "_load_payload",
        lambda: _payload(publish_to_database=False),
    )
    monkeypatch.setattr(
        runner,
        "backtest_run_and_publish",
        lambda request: FakeResponse(
            published=False,
            publish_status="skipped",
        ),
    )

    runner.main()

    report_path = tmp_path / "reports" / "hourly-backtest-result.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runtime"]["runtime_environment"] == "research"


def test_hourly_workflow_locks_schedule_to_nested_and_pins_actions():
    workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/hourly_backtest.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "github.event_name == 'schedule' && 'nested_promotion'" in workflow
    assert "github.event_name == 'schedule' && 'production'" in workflow
    assert "legacy_fixed" in workflow
    assert "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09" in workflow
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflow
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in workflow
