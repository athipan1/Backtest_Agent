from datetime import datetime, timezone

from app.models import PriceBar
from scripts.run_hourly_backtest import _load_payload


class FakeProvider:
    def fetch_bars(self, **kwargs):
        assert kwargs["symbol"] == "AAPL"
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
    assert len(first["metadata"]["dataset_fingerprint"]) == 64
