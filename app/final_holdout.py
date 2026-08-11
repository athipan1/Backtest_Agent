from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.data_provider import dataset_fingerprint
from app.models import BacktestRunResult, PriceBar


class FinalHoldoutError(RuntimeError):
    """Raised when the sealed final holdout cannot be evaluated safely."""


class FinalHoldoutCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool = True
    bars: int = Field(default=252, ge=20)
    min_trades: int = Field(default=10, ge=0)
    min_return: float = 0.0
    min_sharpe: float = 0.0
    max_drawdown_floor: float = Field(default=-0.20, ge=-1.0, le=0.0)


class SealedHoldoutEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool
    start: str
    end: str
    bar_count: int
    trade_count: int
    return_pct: float
    sharpe_ratio: float | None
    profit_factor: float | None
    max_drawdown: float
    dataset_fingerprint: str
    strategy_id: str
    effective_parameters_sha256: str
    passed: bool
    gates: dict[str, bool]
    criteria: FinalHoldoutCriteria


def canonical_parameters_sha256(parameters: dict[str, Any]) -> str:
    encoded = json.dumps(
        parameters,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def split_sealed_final_holdout(
    bars: Sequence[PriceBar],
    *,
    criteria: FinalHoldoutCriteria,
    minimum_research_bars: int,
) -> tuple[list[PriceBar], list[PriceBar]]:
    ordered = sorted(bars, key=lambda item: item.timestamp)
    if not criteria.enabled:
        return list(ordered), []
    required = minimum_research_bars + criteria.bars
    if len(ordered) < required:
        raise FinalHoldoutError(
            "insufficient history for sealed final holdout: "
            f"observed={len(ordered)}, required={required}, "
            f"research={minimum_research_bars}, holdout={criteria.bars}"
        )
    split_at = len(ordered) - criteria.bars
    research = list(ordered[:split_at])
    holdout = list(ordered[split_at:])
    if len(research) < minimum_research_bars or len(holdout) != criteria.bars:
        raise FinalHoldoutError("sealed final holdout slicing invariant failed")
    if research[-1].timestamp >= holdout[0].timestamp:
        raise FinalHoldoutError("sealed final holdout chronological boundary is invalid")
    return research, holdout


def evaluate_sealed_final_holdout(
    *,
    result: BacktestRunResult,
    bars: Sequence[PriceBar],
    criteria: FinalHoldoutCriteria,
    strategy_id: str,
    effective_parameters: dict[str, Any],
) -> SealedHoldoutEvidence:
    if not criteria.enabled:
        raise FinalHoldoutError("disabled holdout cannot be used as promotion evidence")
    ordered = sorted(bars, key=lambda item: item.timestamp)
    if len(ordered) != criteria.bars:
        raise FinalHoldoutError(
            "sealed final holdout bar count changed before evaluation: "
            f"observed={len(ordered)}, expected={criteria.bars}"
        )
    metrics = result.metrics
    gates = {
        "bar_count": len(ordered) == criteria.bars,
        "minimum_trades": metrics.trade_count >= criteria.min_trades,
        "minimum_return": metrics.return_pct >= criteria.min_return,
        "minimum_sharpe": (
            metrics.sharpe_ratio is not None
            and metrics.sharpe_ratio >= criteria.min_sharpe
        ),
        "maximum_drawdown": metrics.max_drawdown >= criteria.max_drawdown_floor,
        "exact_strategy": result.strategy == effective_parameters.get("strategy"),
    }
    return SealedHoldoutEvidence(
        enabled=True,
        start=ordered[0].timestamp.isoformat(),
        end=ordered[-1].timestamp.isoformat(),
        bar_count=len(ordered),
        trade_count=metrics.trade_count,
        return_pct=metrics.return_pct,
        sharpe_ratio=metrics.sharpe_ratio,
        profit_factor=metrics.profit_factor,
        max_drawdown=metrics.max_drawdown,
        dataset_fingerprint=dataset_fingerprint({result.symbols[0]: list(ordered)}),
        strategy_id=strategy_id,
        effective_parameters_sha256=canonical_parameters_sha256(effective_parameters),
        passed=all(gates.values()),
        gates=gates,
        criteria=criteria,
    )
