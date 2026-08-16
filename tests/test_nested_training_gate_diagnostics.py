from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.diagnose_nested_training_gates import (
    diagnose_payload,
    load_console_payload,
    main,
    render_markdown,
)


def _metrics(*, trades=12, annualized_return=0.08, sharpe=1.1, profit_factor=1.5, excess=0.02):
    return {
        "initial_equity": 100000.0,
        "final_equity": 101000.0,
        "net_profit": 1000.0,
        "return_pct": 0.01,
        "trade_count": trades,
        "winning_trades": 7,
        "losing_trades": 5,
        "win_rate": 0.5833,
        "gross_profit": 2000.0,
        "gross_loss": -1000.0,
        "profit_factor": profit_factor,
        "expectancy": 83.33,
        "max_drawdown": -0.05,
        "annualized_return": annualized_return,
        "annualized_volatility": 0.10,
        "sharpe_ratio": sharpe,
        "sortino_ratio": 1.2,
        "calmar_ratio": 1.6,
        "realized_net_profit": 1000.0,
        "unrealized_pnl": 0.0,
        "open_position_count": 0,
        "allocation_rejections": 0,
        "partial_fills": 0,
        "liquidity_rejections": 0,
        "risk_rejections": 0,
        "kill_switch_events": 0,
        "benchmark_return_pct": 0.06,
        "excess_return_pct": excess,
    }


def _payload():
    criteria = {
        "min_trades": 10,
        "min_annualized_return": 0.05,
        "min_sharpe_ratio": 0.8,
        "min_profit_factor": 1.2,
        "max_drawdown_floor": -0.2,
        "min_excess_return": 0.0,
        "max_kill_switch_events": 0,
    }
    bad = _metrics(trades=6, annualized_return=0.02, sharpe=1.4, profit_factor=2.0, excess=-0.03)
    good = _metrics()
    return {
        "status": "success",
        "data": {
            "items": [
                {
                    "selection": {
                        "symbol": "ALL",
                        "selection_status": "no_eligible_strategy",
                        "selection_method": "nested_train_select_test_evaluate",
                        "selection_criteria": criteria,
                        "nested_walk_forward": {
                            "windows": [
                                {"window": 1, "decision": "NO_TRADE", "warnings": ["no candidate"]},
                                {"window": 2, "decision": "TRADE", "warnings": []},
                            ]
                        },
                        "ranked_results": [
                            {
                                "strategy_id": "mean-reversion",
                                "name": "Mean Reversion",
                                "walk_forward": {
                                    "windows": [
                                        {"window": 1, "train_metrics": bad},
                                        {"window": 2, "train_metrics": good},
                                    ]
                                },
                            },
                            {
                                "strategy_id": "sma",
                                "name": "SMA",
                                "walk_forward": {
                                    "windows": [
                                        {"window": 1, "train_metrics": _metrics(trades=4, annualized_return=-0.01, sharpe=-0.2, profit_factor=0.7)},
                                        {"window": 2, "train_metrics": good},
                                    ]
                                },
                            },
                        ],
                    }
                }
            ]
        },
    }


def test_diagnostic_explains_no_trade_with_exact_performance_gate_failures():
    report = diagnose_payload(_payload())
    item = report["items"][0]
    window = item["windows"][0]

    assert report["schema_version"] == "nested-training-gate-diagnostics.v1"
    assert window["nested_decision"] == "NO_TRADE"
    assert window["all_candidates_failed_performance_gates"] is True
    assert window["closest_candidate"]["strategy_id"] == "mean-reversion"
    assert set(window["closest_candidate"]["failed_performance_gates"]) == {
        "trade_count",
        "annualized_return",
        "excess_return",
    }
    assert item["summary"]["no_trade_windows_explained_by_performance_gates"] == 1
    assert item["summary"]["unexplained_no_trade_windows"] == []
    assert report["safety"]["backtest_rerun_performed"] is False
    assert report["safety"]["selection_thresholds_changed"] is False


def test_no_trade_that_passes_performance_gates_is_flagged_for_deeper_evidence():
    payload = _payload()
    payload["data"]["items"][0]["selection"]["nested_walk_forward"]["windows"][1]["decision"] = "NO_TRADE"

    report = diagnose_payload(payload)
    item = report["items"][0]

    assert item["summary"]["unexplained_no_trade_windows"] == [2]
    assert item["summary"]["statistical_training_gate_evidence_recomputed"] is False


def test_loader_accepts_runtime_event_line_followed_by_pretty_json(tmp_path: Path):
    path = tmp_path / "console.json"
    path.write_text(
        json.dumps({"event": "backtest_runtime_mode"}) + "\n" + json.dumps(_payload(), indent=2),
        encoding="utf-8",
    )

    loaded = load_console_payload(path)

    assert loaded["status"] == "success"
    assert loaded["data"]["items"][0]["selection"]["symbol"] == "ALL"


def test_loader_accepts_plain_json_and_rejects_empty_or_event_only(tmp_path: Path):
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps(_payload()), encoding="utf-8")
    assert load_console_payload(plain)["status"] == "success"

    empty = tmp_path / "empty.json"
    empty.write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_console_payload(empty)

    event_only = tmp_path / "event-only.json"
    event_only.write_text(json.dumps({"event": "backtest_runtime_mode"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no result payload"):
        load_console_payload(event_only)


def test_render_markdown_reports_failures_and_safe_no_failure_case():
    report = diagnose_payload(_payload())
    markdown = render_markdown(report)

    assert "Nested Training Gate Diagnostics" in markdown
    assert "`trade_count`" in markdown
    assert "Window 1" in markdown
    assert "mean-reversion" in markdown
    assert "does not change selection thresholds" in markdown

    empty_report = diagnose_payload({"data": {"items": [None, {}, {"selection": {}}]}})
    empty_markdown = render_markdown(empty_report)
    assert "No performance-gate failures found." in empty_markdown
    assert empty_report["aggregate"]["symbol_count"] == 0


def test_diagnostic_skips_malformed_ranked_rows_and_unknown_nested_window():
    payload = _payload()
    selection = payload["data"]["items"][0]["selection"]
    selection["ranked_results"].extend(
        [
            None,
            {"strategy_id": "broken", "walk_forward": {"windows": [None, {"window": None}, {"window": 3, "train_metrics": None}]}},
        ]
    )
    selection["nested_walk_forward"]["windows"].append({"window": 3, "warnings": "not-a-list"})

    report = diagnose_payload(payload)
    window3 = report["items"][0]["windows"][2]

    assert window3["window"] == 3
    assert window3["nested_decision"] == "UNKNOWN"
    assert window3["closest_candidate"] is None
    assert window3["nested_warnings"] == []


def test_cli_writes_json_and_markdown_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    source = tmp_path / "console.json"
    output = tmp_path / "diagnostic.json"
    markdown = tmp_path / "diagnostic.md"
    source.write_text(json.dumps(_payload()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnose_nested_training_gates.py",
            "--input",
            str(source),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
        ],
    )

    assert main() == 0
    assert output.exists()
    assert markdown.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["aggregate"]["symbol_count"] == 1
    assert "Nested Training Gate Diagnostics" in markdown.read_text(encoding="utf-8")
    assert "symbol_count" in capsys.readouterr().out
