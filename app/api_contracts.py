from __future__ import annotations

import os
import re
from datetime import timezone
from typing import Any, Dict, List

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.models import (
    BacktestCompareRequest,
    BacktestRobustnessRequest,
    BacktestRunRequest,
    PerformanceReportRequest,
    PriceBar,
    StrategyCandidate,
    WalkForwardRequest,
)


_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,19}$")


def _limit(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _normalize_symbols(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("symbols must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("every symbol must be a string")
        symbol = item.strip().upper()
        if not symbol or _SYMBOL_PATTERN.fullmatch(symbol) is None:
            raise ValueError(f"invalid symbol: {item!r}")
        if symbol in seen:
            raise ValueError(f"duplicate symbol after normalization: {symbol}")
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _normalize_bars(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("bars must be an object keyed by symbol")
    normalized: dict[str, Any] = {}
    for raw_symbol, rows in value.items():
        if not isinstance(raw_symbol, str):
            raise ValueError("bar keys must be strings")
        symbol = raw_symbol.strip().upper()
        if not symbol or _SYMBOL_PATTERN.fullmatch(symbol) is None:
            raise ValueError(f"invalid bars symbol: {raw_symbol!r}")
        if symbol in normalized:
            raise ValueError(f"duplicate bars key after normalization: {symbol}")
        normalized[symbol] = rows
    return normalized


def _validate_dataset(model: Any) -> Any:
    symbol_set = set(model.symbols)
    bars_set = set(model.bars)
    if bars_set != symbol_set:
        missing = sorted(symbol_set - bars_set)
        unexpected = sorted(bars_set - symbol_set)
        details: list[str] = []
        if missing:
            details.append(f"missing bars for symbols: {missing}")
        if unexpected:
            details.append(f"unexpected bars for symbols: {unexpected}")
        raise ValueError("; ".join(details))

    max_symbols = _limit("BACKTEST_MAX_SYMBOLS", 25)
    max_bars_per_symbol = _limit("BACKTEST_MAX_BARS_PER_SYMBOL", 10000)
    max_total_bars = _limit("BACKTEST_MAX_TOTAL_BARS", 100000)
    if len(model.symbols) > max_symbols:
        raise ValueError(
            f"symbol count {len(model.symbols)} exceeds maximum {max_symbols}"
        )

    total_bars = 0
    for symbol, rows in model.bars.items():
        if not rows:
            raise ValueError(f"bars for {symbol} must not be empty")
        if len(rows) > max_bars_per_symbol:
            raise ValueError(
                f"bars for {symbol} exceed maximum {max_bars_per_symbol}"
            )
        total_bars += len(rows)
        timestamps: set[str] = set()
        previous = None
        for bar in rows:
            timestamp = bar.timestamp.astimezone(timezone.utc)
            timestamp_key = timestamp.isoformat()
            if timestamp_key in timestamps:
                raise ValueError(
                    f"duplicate timestamp for {symbol}: {timestamp_key}"
                )
            timestamps.add(timestamp_key)
            if previous is not None and timestamp <= previous:
                raise ValueError(
                    f"bars for {symbol} must be strictly increasing by timestamp"
                )
            previous = timestamp

    if total_bars > max_total_bars:
        raise ValueError(
            f"total bar count {total_bars} exceeds maximum {max_total_bars}"
        )
    return model


class StrictPriceBar(PriceBar):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def require_timezone(self) -> "StrictPriceBar":
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must include an explicit timezone")
        self.timestamp = self.timestamp.astimezone(timezone.utc)
        return self


class StrictStrategyCandidate(StrategyCandidate):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class StrictBacktestRunRequest(BacktestRunRequest):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    symbols: List[str] = Field(min_length=1, max_length=25)
    bars: Dict[str, List[StrictPriceBar]]

    _normalize_symbols = field_validator("symbols", mode="before")(
        _normalize_symbols
    )
    _normalize_bars = field_validator("bars", mode="before")(_normalize_bars)

    @model_validator(mode="after")
    def validate_strict_dataset(self) -> "StrictBacktestRunRequest":
        return _validate_dataset(self)


class StrictBacktestRobustnessRequest(BacktestRobustnessRequest):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    symbols: List[str] = Field(min_length=1, max_length=25)
    bars: Dict[str, List[StrictPriceBar]]

    _normalize_symbols = field_validator("symbols", mode="before")(
        _normalize_symbols
    )
    _normalize_bars = field_validator("bars", mode="before")(_normalize_bars)

    @model_validator(mode="after")
    def validate_strict_dataset(self) -> "StrictBacktestRobustnessRequest":
        return _validate_dataset(self)


class StrictBacktestCompareRequest(BacktestCompareRequest):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    symbols: List[str] = Field(min_length=1, max_length=25)
    bars: Dict[str, List[StrictPriceBar]]
    candidates: List[StrictStrategyCandidate] = Field(
        min_length=1,
        max_length=25,
    )

    _normalize_symbols = field_validator("symbols", mode="before")(
        _normalize_symbols
    )
    _normalize_bars = field_validator("bars", mode="before")(_normalize_bars)

    @model_validator(mode="after")
    def validate_strict_dataset(self) -> "StrictBacktestCompareRequest":
        return _validate_dataset(self)


class StrictWalkForwardRequest(WalkForwardRequest):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    symbols: List[str] = Field(min_length=1, max_length=25)
    bars: Dict[str, List[StrictPriceBar]]
    candidates: List[StrictStrategyCandidate] = Field(
        min_length=1,
        max_length=25,
    )

    _normalize_symbols = field_validator("symbols", mode="before")(
        _normalize_symbols
    )
    _normalize_bars = field_validator("bars", mode="before")(_normalize_bars)

    @model_validator(mode="after")
    def validate_strict_dataset(self) -> "StrictWalkForwardRequest":
        return _validate_dataset(self)


class StrictPerformanceReportRequest(PerformanceReportRequest):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
