from datetime import datetime, timezone

from app.models import PriceBar
from scripts import run_hourly_backtest as hourly
from scripts.run_hourly_backtest import _load_payload, _symbols_from_env


class FakeProvider:
    def __init__(self):
        self.symbols = []

    def fetch_bars(self, **kwargs):
        self.symbols.append(kwargs["symbol"])
        assert kwargs["minimum_bars"] == 2
        return [
            PriceBar(
                timestamp=datetime(2026, 1, day, tzinfo=timezone.utc),
                open=100 + day,
                high=102 + day,
                low=99 + day,
                close=101 + day,
                volume=1000,
            )
            for day in (1, 2)
        ]


def test_hourly_payload_uses_provider_and_deterministic_identity(monkeypatch):
    monkeypatch.delenv("BACKTEST_SYMBOLS", raising=False)
    monkeypatch.setenv("BACKTEST_SYMBOL", "aapl")
    monkeypatch.setenv("BACKTEST_MINIMUM_BARS", "2")
    monkeypatch.setenv("BACKTEST_START", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("BACKTEST_END", "2026-02-01T00:00:00Z")
    first = _load_payload(provider=FakeProvider())
    second = _load_payload(provider=FakeProvider())

    assert first["bars"] == second["bars"]
    assert first["run_id"] == second["run_id"]
    assert first["run_id"].startswith("backtest-")
    assert first["metadata"]["data_source"] == "alpaca_market_data"
    assert first["metadata"]["bar_count"] == 2
    assert first["metadata"]["bar_counts"] == {"AAPL": 2}
    assert len(first["metadata"]["dataset_fingerprint"]) == 64


def test_hourly_run_identity_changes_when_risk_policy_changes(monkeypatch):
    monkeypatch.delenv("BACKTEST_SYMBOLS", raising=False)
    monkeypatch.setenv("BACKTEST_SYMBOL", "AAPL")
    monkeypatch.setenv("BACKTEST_MINIMUM_BARS", "2")
    monkeypatch.setenv("BACKTEST_START", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("BACKTEST_END", "2026-02-01T00:00:00Z")
    monkeypatch.setenv("BACKTEST_RISK_PER_TRADE", "0.01")
    conservative = _load_payload(provider=FakeProvider())

    monkeypatch.setenv("BACKTEST_RISK_PER_TRADE", "0.02")
    aggressive = _load_payload(provider=FakeProvider())

    assert conservative["run_id"] != aggressive["run_id"]
    assert conservative["risk_per_trade"] == 0.01
    assert aggressive["risk_per_trade"] == 0.02


def test_hourly_payload_fetches_deduplicated_batch_symbols(monkeypatch):
    monkeypatch.setenv("BACKTEST_SYMBOLS", "aapl, MSFT,AAPL")
    monkeypatch.setenv("BACKTEST_MAX_SYMBOLS", "10")
    monkeypatch.setenv("BACKTEST_MINIMUM_BARS", "2")
    monkeypatch.setenv("BACKTEST_START", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("BACKTEST_END", "2026-02-01T00:00:00Z")
    provider = FakeProvider()

    payload = _load_payload(provider=provider)

    assert payload["symbols"] == ["AAPL", "MSFT"]
    assert provider.symbols == ["AAPL", "MSFT"]
    assert sorted(payload["bars"]) == ["AAPL", "MSFT"]
    assert payload["metadata"]["bar_count"] == 4
    assert payload["metadata"]["bar_counts"] == {"AAPL": 2, "MSFT": 2}
    assert payload["run_id"].startswith("backtest-")


def test_hourly_symbol_parser_enforces_configured_batch_limit(monkeypatch):
    monkeypatch.setenv("BACKTEST_SYMBOLS", "AAPL,MSFT,NVDA")
    monkeypatch.setenv("BACKTEST_MAX_SYMBOLS", "2")

    try:
        _symbols_from_env()
    except ValueError as exc:
        assert "maximum is 2" in str(exc)
    else:
        raise AssertionError("expected batch limit validation to fail")


def test_hourly_symbol_parser_rejects_unsafe_symbol(monkeypatch):
    monkeypatch.setenv("BACKTEST_SYMBOLS", "AAPL,../MSFT")
    monkeypatch.setenv("BACKTEST_MAX_SYMBOLS", "10")

    try:
        _symbols_from_env()
    except ValueError as exc:
        assert "invalid symbols" in str(exc)
    else:
        raise AssertionError("expected unsafe symbol validation to fail")


def test_hourly_main_writes_batch_summary_and_per_symbol_reports(
    monkeypatch,
    tmp_path,
):
    bars = [
        {
            "timestamp": f"2026-01-0{day}T00:00:00Z",
            "open": 100 + day,
            "high": 102 + day,
            "low": 99 + day,
            "close": 101 + day,
            "volume": 1000,
        }
        for day in (1, 2, 3)
    ]
    payload = {
        "account_id": "1",
        "run_id": "batch-report-test",
        "skill_id": "skill-1",
        "strategy_id": "strategy-1",
        "timeframe": "1d",
        "publish_to_database": False,
        "symbols": ["AAPL", "MSFT"],
        "initial_equity": 100000,
        "fast_window": 2,
        "slow_window": 3,
        "fee_bps": 0,
        "slippage_bps": 0,
        "bars": {"AAPL": bars, "MSFT": bars},
        "metadata": {"storage_only": True},
    }
    monkeypatch.setattr(hourly, "_load_payload", lambda: payload)
    monkeypatch.chdir(tmp_path)

    hourly.main()

    reports = tmp_path / "reports"
    assert (reports / "hourly-backtest-result.json").exists()
    assert (reports / "hourly-backtest-aapl.json").exists()
    assert (reports / "hourly-backtest-msft.json").exists()
