from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status


def _is_production() -> bool:
    environment = (
        os.getenv("BACKTEST_ENV")
        or os.getenv("ENVIRONMENT")
        or "development"
    )
    return environment.strip().lower() in {"production", "prod"}


def require_backtest_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
) -> None:
    """Protect compute and publish endpoints with constant-time comparison.

    Development remains backward compatible when no key is configured. A
    production deployment fails closed when BACKTEST_API_KEY is absent.
    """

    configured_key = os.getenv("BACKTEST_API_KEY", "")
    if not configured_key:
        if _is_production():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="BACKTEST_API_KEY must be configured in production",
            )
        return

    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-KEY header is required",
        )
    if not hmac.compare_digest(x_api_key, configured_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid API key",
        )
