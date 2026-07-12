from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable

from app.models import PriceBar


class HistoricalDataError(RuntimeError):
    """Raised when historical market data cannot be trusted for a backtest."""


TIMEFRAME_MAP = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "1h": "1Hour",
    "1d": "1Day",
}


def validate_price_bars(raw_bars: Iterable[dict], *, symbol: str, minimum_bars: int) -> list[PriceBar]:
    bars: list[PriceBar] = []
    timestamps = set()
    for index, item in enumerate(raw_bars):
        try:
            bar = PriceBar.model_validate(item)
        except Exception as exc:
            raise HistoricalDataError(f"{symbol} bar {index} is invalid: {exc}") from exc
        if bar.timestamp in timestamps:
            raise HistoricalDataError(f"{symbol} contains duplicate timestamp {bar.timestamp.isoformat()}")
        timestamps.add(bar.timestamp)
        bars.append(bar)

    bars.sort(key=lambda item: item.timestamp)
    if len(bars) < minimum_bars:
        raise HistoricalDataError(
            f"{symbol} returned {len(bars)} bars; at least {minimum_bars} are required"
        )
    return bars


def dataset_fingerprint(bars: dict[str, list[PriceBar]]) -> str:
    canonical = {
        symbol.upper(): [bar.model_dump(mode="json") for bar in sorted(rows, key=lambda item: item.timestamp)]
        for symbol, rows in sorted(bars.items(), key=lambda item: item[0].upper())
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class AlpacaMarketDataProvider:
    api_key: str
    secret_key: str
    base_url: str = "https://data.alpaca.markets"
    feed: str = "iex"
    adjustment: str = "all"
    timeout_seconds: float = 30.0
    opener: Callable = urllib.request.urlopen

    def fetch_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        minimum_bars: int,
        limit: int = 10000,
    ) -> list[PriceBar]:
        if not self.api_key or not self.secret_key:
            raise HistoricalDataError(
                "Alpaca Market Data credentials are required; refusing to fall back to sample bars"
            )
        alpaca_timeframe = TIMEFRAME_MAP.get(timeframe.lower())
        if alpaca_timeframe is None:
            raise HistoricalDataError(f"unsupported timeframe: {timeframe}")

        raw_bars: list[dict] = []
        page_token: str | None = None
        while len(raw_bars) < limit:
            params = {
                "timeframe": alpaca_timeframe,
                "start": start,
                "end": end,
                "limit": min(10000, limit - len(raw_bars)),
                "adjustment": self.adjustment,
                "feed": self.feed,
                "sort": "asc",
            }
            if page_token:
                params["page_token"] = page_token
            url = (
                f"{self.base_url.rstrip('/')}/v2/stocks/{urllib.parse.quote(symbol.upper())}/bars?"
                f"{urllib.parse.urlencode(params)}"
            )
            request = urllib.request.Request(
                url,
                headers={
                    "APCA-API-KEY-ID": self.api_key,
                    "APCA-API-SECRET-KEY": self.secret_key,
                    "Accept": "application/json",
                },
            )
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                raise HistoricalDataError(f"failed to fetch Alpaca Market Data for {symbol}: {exc}") from exc

            for item in payload.get("bars") or []:
                raw_bars.append(
                    {
                        "timestamp": item.get("t"),
                        "open": item.get("o"),
                        "high": item.get("h"),
                        "low": item.get("l"),
                        "close": item.get("c"),
                        "volume": item.get("v", 0),
                    }
                )
            page_token = payload.get("next_page_token")
            if not page_token:
                break

        return validate_price_bars(raw_bars, symbol=symbol.upper(), minimum_bars=minimum_bars)
