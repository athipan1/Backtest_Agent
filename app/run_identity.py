from __future__ import annotations

import hashlib
import json
from typing import Any

from app.data_provider import dataset_fingerprint
from app.execution_policy import execution_policy_metadata
from app.models import BacktestRunRequest, PriceBar


_NON_SIMULATION_FIELDS = {
    "account_id",
    "batch_id",
    "metadata",
    "publish_to_database",
    "run_id",
}


def _bars_for_exact_symbol(
    request: BacktestRunRequest,
    symbol: str,
) -> list[PriceBar]:
    normalized_symbol = symbol.strip().upper()
    for key, bars in request.bars.items():
        if key.upper() == normalized_symbol:
            return list(bars)
    return []


def exact_symbol_identity(
    request: BacktestRunRequest,
    *,
    symbol: str,
    timeframe: str,
    engine_version: str,
) -> dict[str, Any]:
    """Build a stable identity from one symbol's data and exact run policy."""

    normalized_symbol = symbol.strip().upper()
    bars = _bars_for_exact_symbol(request, normalized_symbol)
    if not bars:
        raise ValueError(f"missing bars for exact symbol identity: {normalized_symbol}")

    parameters = request.model_dump(
        mode="json",
        exclude={"bars", "symbols"},
    )
    for field in _NON_SIMULATION_FIELDS:
        parameters.pop(field, None)
    parameters["execution_policy"] = execution_policy_metadata(request)

    return {
        "dataset_fingerprint": dataset_fingerprint(
            {normalized_symbol: bars}
        ),
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "engine_version": engine_version,
        "parameters": parameters,
    }


def deterministic_symbol_run_id(
    request: BacktestRunRequest,
    *,
    symbol: str,
    timeframe: str,
    engine_version: str,
) -> str:
    identity = exact_symbol_identity(
        request,
        symbol=symbol,
        timeframe=timeframe,
        engine_version=engine_version,
    )
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"backtest-{digest[:24]}"
