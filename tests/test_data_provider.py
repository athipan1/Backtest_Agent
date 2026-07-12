import json

import pytest

from app.data_provider import AlpacaMarketDataProvider, HistoricalDataError, dataset_fingerprint, validate_price_bars


def rows(last_close=102):
    return [
        {"timestamp": "2026-01-01T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10},
        {"timestamp": "2026-01-02T00:00:00Z", "open": 101, "high": 103, "low": 100, "close": last_close, "volume": 20},
    ]


def test_validate_price_bars_sorts_and_rejects_duplicates():
    bars = validate_price_bars(reversed(rows()), symbol="AAPL", minimum_bars=2)
    assert bars[0].timestamp < bars[1].timestamp

    with pytest.raises(HistoricalDataError, match="duplicate timestamp"):
        validate_price_bars([rows()[0], rows()[0]], symbol="AAPL", minimum_bars=2)


def test_dataset_fingerprint_is_deterministic_and_content_sensitive():
    original = validate_price_bars(rows(), symbol="AAPL", minimum_bars=2)
    changed = validate_price_bars(rows(last_close=101.5), symbol="AAPL", minimum_bars=2)
    assert dataset_fingerprint({"aapl": original}) == dataset_fingerprint({"AAPL": original})
    assert dataset_fingerprint({"AAPL": original}) != dataset_fingerprint({"AAPL": changed})


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_alpaca_provider_normalizes_market_data_response():
    def opener(request, timeout):
        assert "data.alpaca.markets" in request.full_url
        assert request.headers["Apca-api-key-id"] == "key"
        return FakeResponse(
            {
                "bars": [
                    {"t": item["timestamp"], "o": item["open"], "h": item["high"], "l": item["low"], "c": item["close"], "v": item["volume"]}
                    for item in rows()
                ],
                "next_page_token": None,
            }
        )

    provider = AlpacaMarketDataProvider(api_key="key", secret_key="secret", opener=opener)
    bars = provider.fetch_bars(
        symbol="AAPL",
        timeframe="1d",
        start="2026-01-01T00:00:00Z",
        end="2026-02-01T00:00:00Z",
        minimum_bars=2,
    )
    assert [bar.close for bar in bars] == [100, 102]


def test_alpaca_provider_refuses_missing_credentials():
    provider = AlpacaMarketDataProvider(api_key="", secret_key="")
    with pytest.raises(HistoricalDataError, match="refusing to fall back"):
        provider.fetch_bars(
            symbol="AAPL",
            timeframe="1d",
            start="2026-01-01T00:00:00Z",
            end="2026-02-01T00:00:00Z",
            minimum_bars=2,
        )
