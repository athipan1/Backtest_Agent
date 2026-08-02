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


def test_hourly_single_symbol_exits_nonzero_when_required_publish_is_skipped(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
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

    assert (tmp_path / "reports" / "hourly-backtest-result.json").exists()


def test_hourly_single_symbol_allows_explicit_storage_skip(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
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

    assert (tmp_path / "reports" / "hourly-backtest-result.json").exists()
