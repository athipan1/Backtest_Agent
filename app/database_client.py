from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx


class DatabaseAgentClient:
    """Small HTTP client for publishing Backtest_Agent outputs to Database_Agent.

    The client is intentionally write-only for backtest result publishing and does
    not expose any broker, order, approval, or execution operations.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("DATABASE_AGENT_URL") or "").rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("DATABASE_AGENT_API_KEY", "")
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _headers(self, correlation_id: Optional[str] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        return headers

    def publish_backtest_run(
        self,
        payload: Dict[str, Any],
        *,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "status": "skipped",
                "reason": "DATABASE_AGENT_URL is not configured",
            }

        response = httpx.post(
            f"{self.base_url}/backtests/runs",
            json=payload,
            headers=self._headers(correlation_id),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
