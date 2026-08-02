from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExecutionRealismPolicy(BaseModel):
    """Execution assumptions applied consistently across pricing and sizing."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    bid_ask_spread_bps: float = Field(default=0.0, ge=0, lt=10000)
    quantity_increment: int = Field(default=1, ge=1, le=1_000_000)
    signal_execution_delay_bars: Literal[1] = 1


_CURRENT_POLICY: ContextVar[ExecutionRealismPolicy | None] = ContextVar(
    "backtest_execution_policy",
    default=None,
)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite number") from exc


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def default_execution_policy() -> ExecutionRealismPolicy:
    return ExecutionRealismPolicy(
        bid_ask_spread_bps=_env_float(
            "BACKTEST_DEFAULT_BID_ASK_SPREAD_BPS",
            0.0,
        ),
        quantity_increment=_env_int(
            "BACKTEST_DEFAULT_QUANTITY_INCREMENT",
            1,
        ),
        signal_execution_delay_bars=1,
    )


def resolve_execution_policy(request: Any | None = None) -> ExecutionRealismPolicy:
    value = getattr(request, "execution_policy", None) if request is not None else None
    if value is None:
        return default_execution_policy()
    if isinstance(value, ExecutionRealismPolicy):
        return value
    return ExecutionRealismPolicy.model_validate(value)


def current_execution_policy() -> ExecutionRealismPolicy:
    return _CURRENT_POLICY.get() or default_execution_policy()


@contextmanager
def execution_policy_context(
    policy: ExecutionRealismPolicy,
) -> Iterator[None]:
    token = _CURRENT_POLICY.set(policy)
    try:
        yield
    finally:
        _CURRENT_POLICY.reset(token)


def quantize_quantity(quantity: float) -> int:
    policy = current_execution_policy()
    if quantity <= 0:
        return 0
    integer_quantity = int(quantity)
    return (
        integer_quantity // policy.quantity_increment
    ) * policy.quantity_increment


def execution_policy_metadata(request: Any | None = None) -> dict[str, Any]:
    policy = resolve_execution_policy(request)
    return policy.model_dump(mode="json")
