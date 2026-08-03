from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx


class DatabaseAgentClient:
    """HTTP client for immutable Backtest evidence and promotion attestations.

    The client deliberately exposes no paper approval, revocation, Risk,
    Execution, order, position, or broker operation. Backtest_Agent may create a
    promotion and attest only the evidence states it owns.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("DATABASE_AGENT_URL") or "").rstrip("/")
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("DATABASE_AGENT_API_KEY", "")
        )
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

    def _post(
        self,
        path: str,
        payload: Dict[str, Any],
        *,
        correlation_id: Optional[str],
        require_data: bool,
    ) -> Dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("DATABASE_AGENT_URL is not configured")

        response = httpx.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=self._headers(correlation_id),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        document = response.json()
        if not isinstance(document, dict):
            raise RuntimeError("Database_Agent returned a malformed response")
        if document.get("status") != "success":
            error = document.get("error")
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise RuntimeError(f"Database_Agent operation failed: {code}")
        if require_data and not isinstance(document.get("data"), dict):
            raise RuntimeError("Database_Agent response is missing promotion data")
        return document

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
        return self._post(
            "/backtests/runs",
            payload,
            correlation_id=correlation_id,
            require_data=False,
        )

    def create_backtest_promotion(
        self,
        payload: Dict[str, Any],
        *,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or replay a GENERATED promotion for one exact stored run."""

        return self._post(
            "/backtests/promotions",
            payload,
            correlation_id=correlation_id,
            require_data=True,
        )

    def transition_backtest_promotion(
        self,
        promotion_id: str,
        payload: Dict[str, Any],
        *,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Attest a Backtest-owned transition.

        Callers are additionally restricted by ``promotion_lifecycle.py`` to
        VALIDATED, OOS_PASSED, and ROBUSTNESS_PASSED. This client intentionally
        has no method for APPROVED_FOR_PAPER or PAPER_OBSERVING.
        """

        return self._post(
            f"/backtests/promotions/{promotion_id}/transition",
            payload,
            correlation_id=correlation_id,
            require_data=True,
        )
