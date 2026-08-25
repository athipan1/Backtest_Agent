from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    contract = resolve_history_contract({}, runner_path=_runner(tmp_path))

    assert contract["research_minimum_bars"] == 630
    assert contract["sealed_holdout_bars"] == 252
    assert contract["required_total_bars"] == 882
    assert contract["history_days"] == 1825
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


def test_missing_runner_constant_fails_closed(tmp_path):
    runner = tmp_path / "hourly_promotion_runner.py"
    runner.write_text(
        "DEFAULT_MINIMUM_BARS = 630\nDEFAULT_FINAL_HOLDOUT_BARS = 252\n",
        encoding="utf-8",
    )

    with pytest.raises(HistoryContractError, match="incomplete"):
        resolve_history_contract({}, runner_path=runner)


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
