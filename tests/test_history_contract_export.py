from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path

import pytest

from scripts import export_history_contract
from scripts.export_history_contract import (
    HistoryContractError,
    resolve_history_contract,
    write_history_contract,
)


def _runner(tmp_path: Path, *, research=630, holdout=252, history_days=1825) -> Path:
    path = tmp_path / "hourly_promotion_runner.py"
    path.write_text(
        "\n".join(
            [
                f"DEFAULT_HISTORY_DAYS = {history_days}",
                f"DEFAULT_MINIMUM_BARS = {research}",
                f"DEFAULT_FINAL_HOLDOUT_BARS = {holdout}",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_contract_reads_production_runner_defaults(tmp_path):
    runner = _runner(tmp_path)
    contract = resolve_history_contract({}, runner_path=runner)

    assert contract["research_minimum_bars"] == 630
    assert contract["sealed_holdout_bars"] == 252
    assert contract["required_total_bars"] == 882
    assert contract["history_days"] == 1825
    assert contract["runner_source"] == str(runner)
    assert contract["thresholds_relaxed"] is False


def test_runtime_overrides_change_exported_total_without_changing_runner_defaults(tmp_path):
    contract = resolve_history_contract(
        {
            "BACKTEST_NESTED_MINIMUM_BARS": "700",
            "BACKTEST_FINAL_HOLDOUT_BARS": "300",
            "BACKTEST_HISTORY_DAYS": "2000",
        },
        runner_path=_runner(tmp_path),
    )

    assert contract["required_total_bars"] == 1000
    assert contract["history_days"] == 2000
    assert contract["runner_defaults"]["research_minimum_bars"] == 630
    assert contract["runner_defaults"]["sealed_holdout_bars"] == 252


def test_disabled_final_holdout_fails_closed(tmp_path):
    with pytest.raises(HistoryContractError, match="FINAL_HOLDOUT_ENABLED"):
        resolve_history_contract(
            {"BACKTEST_FINAL_HOLDOUT_ENABLED": "false"},
            runner_path=_runner(tmp_path),
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BACKTEST_NESTED_MINIMUM_BARS", "0"),
        ("BACKTEST_FINAL_HOLDOUT_BARS", "-1"),
        ("BACKTEST_HISTORY_DAYS", "not-an-int"),
    ],
)
def test_invalid_runtime_contract_values_fail_closed(tmp_path, name, value):
    with pytest.raises(HistoryContractError):
        resolve_history_contract(
            {name: value},
            runner_path=_runner(tmp_path),
        )


def test_missing_runner_constant_fails_closed(tmp_path):
    runner = tmp_path / "hourly_promotion_runner.py"
    runner.write_text(
        "DEFAULT_MINIMUM_BARS = 630\nDEFAULT_FINAL_HOLDOUT_BARS = 252\n",
        encoding="utf-8",
    )

    with pytest.raises(HistoryContractError, match="incomplete"):
        resolve_history_contract({}, runner_path=runner)


def test_non_literal_runner_constant_fails_closed(tmp_path):
    runner = tmp_path / "hourly_promotion_runner.py"
    runner.write_text(
        "\n".join(
            [
                "DEFAULT_HISTORY_DAYS = 5 * 365",
                "DEFAULT_MINIMUM_BARS = 630",
                "DEFAULT_FINAL_HOLDOUT_BARS = 252",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(HistoryContractError, match="not a literal"):
        resolve_history_contract({}, runner_path=runner)


def test_unreadable_runner_fails_closed(tmp_path):
    with pytest.raises(HistoryContractError, match="cannot read"):
        resolve_history_contract({}, runner_path=tmp_path / "missing.py")


def test_write_contract_exports_env_and_json(tmp_path):
    github_env = tmp_path / "github-env"
    output = tmp_path / "contract.json"

    contract = write_history_contract(
        github_env_path=github_env,
        output_path=output,
        environ={},
        runner_path=_runner(tmp_path),
    )

    env_text = github_env.read_text(encoding="utf-8")
    assert "BACKTEST_HISTORY_REQUIRED_BARS=882" in env_text
    assert "BACKTEST_NESTED_MINIMUM_BARS=630" in env_text
    assert "BACKTEST_FINAL_HOLDOUT_BARS=252" in env_text
    assert "BACKTEST_HISTORY_DAYS=1825" in env_text
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["required_total_bars"] == contract["required_total_bars"] == 882


def test_main_requires_github_env(monkeypatch, capsys):
    monkeypatch.setattr(
        export_history_contract,
        "_parse_args",
        lambda: Namespace(github_env="", output="ignored.json"),
    )

    assert export_history_contract.main() == 1
    assert "GITHUB_ENV is missing" in capsys.readouterr().err


def test_main_reports_contract_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        export_history_contract,
        "_parse_args",
        lambda: Namespace(github_env=str(tmp_path / "env"), output=str(tmp_path / "out.json")),
    )
    monkeypatch.setattr(
        export_history_contract,
        "write_history_contract",
        lambda **kwargs: (_ for _ in ()).throw(HistoryContractError("bad contract")),
    )

    assert export_history_contract.main() == 1
    assert "bad contract" in capsys.readouterr().err


def test_main_exports_successful_contract(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        export_history_contract,
        "_parse_args",
        lambda: Namespace(github_env=str(tmp_path / "env"), output=str(tmp_path / "out.json")),
    )
    monkeypatch.setattr(
        export_history_contract,
        "write_history_contract",
        lambda **kwargs: {
            "research_minimum_bars": 630,
            "sealed_holdout_bars": 252,
            "required_total_bars": 882,
            "history_days": 1825,
        },
    )

    assert export_history_contract.main() == 0
    assert "required=882" in capsys.readouterr().out
