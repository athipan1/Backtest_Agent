from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import httpx


def _bounded_float_env(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _bounded_int_env(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _normalize_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        return ""
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"
    return normalized


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
        timeout_seconds: Optional[float] = None,
        reconciliation_attempts: Optional[int] = None,
        reconciliation_backoff_seconds: Optional[float] = None,
    ) -> None:
        configured_base_url = (
            os.getenv("DATABASE_AGENT_URL", "")
            if base_url is None
            else base_url
        )
        self.base_url = _normalize_base_url(configured_base_url)
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("DATABASE_AGENT_API_KEY", "")
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else _bounded_float_env(
                "DATABASE_AGENT_TIMEOUT_SECONDS",
                45.0,
                minimum=1.0,
                maximum=120.0,
            )
        )
        self.reconciliation_attempts = (
            reconciliation_attempts
            if reconciliation_attempts is not None
            else _bounded_int_env(
                "DATABASE_AGENT_RECONCILIATION_ATTEMPTS",
                3,
                minimum=1,
                maximum=6,
            )
        )
        self.reconciliation_backoff_seconds = (
            reconciliation_backoff_seconds
            if reconciliation_backoff_seconds is not None
            else _bounded_float_env(
                "DATABASE_AGENT_RECONCILIATION_BACKOFF_SECONDS",
                1.0,
                minimum=0.0,
                maximum=10.0,
            )
        )

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

    @staticmethod
    def _validated_document(
        response: httpx.Response,
        *,
        require_data: bool,
    ) -> Dict[str, Any]:
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
        return self._validated_document(response, require_data=require_data)

    def _get_existing_backtest_run(
        self,
        run_id: str,
        *,
        correlation_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        response = httpx.get(
            f"{self.base_url}/backtests/runs/{run_id}",
            headers=self._headers(correlation_id),
            timeout=self.timeout_seconds,
        )
        if response.status_code == 404:
            return None
        return self._validated_document(response, require_data=True)

    @staticmethod
    def _existing_run_matches_payload(
        document: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> bool:
        data = document.get("data")
        if not isinstance(data, dict):
            return False
        run = data.get("run")
        if not isinstance(run, dict):
            return False

        scalar_fields = (
            "run_id",
            "account_id",
            "skill_id",
            "strategy_id",
            "timeframe",
            "engine_version",
        )
        for field in scalar_fields:
            expected = payload.get(field)
            actual = run.get(field)
            if expected is not None and str(actual) != str(expected):
                return False

        expected_symbol = str(payload.get("symbol") or "").upper()
        actual_symbol = str(run.get("symbol") or "").upper()
        if expected_symbol != actual_symbol:
            return False
        if run.get("parameters") != payload.get("parameters"):
            return False
        if run.get("metrics") != payload.get("metrics"):
            return False

        expected_metadata = payload.get("metadata")
        actual_metadata = run.get("metadata")
        if isinstance(expected_metadata, dict):
            fingerprint = expected_metadata.get("dataset_fingerprint")
            if fingerprint is not None:
                if not isinstance(actual_metadata, dict):
                    return False
                if actual_metadata.get("dataset_fingerprint") != fingerprint:
                    return False

        expected_trades = payload.get("trades")
        actual_trades = data.get("trades")
        if isinstance(expected_trades, list):
            if not isinstance(actual_trades, list) or len(actual_trades) != len(expected_trades):
                return False

        expected_curve = payload.get("equity_curve")
        actual_curve = data.get("equity_curve")
        if isinstance(expected_curve, list):
            if not isinstance(actual_curve, list) or len(actual_curve) != len(expected_curve):
                return False
        return True

    def _reconcile_backtest_publish(
        self,
        payload: Dict[str, Any],
        *,
        correlation_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            return None

        for attempt in range(1, self.reconciliation_attempts + 1):
            if self.reconciliation_backoff_seconds > 0:
                time.sleep(self.reconciliation_backoff_seconds * attempt)
            try:
                document = self._get_existing_backtest_run(
                    run_id,
                    correlation_id=correlation_id,
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code >= 500:
                    continue
                raise RuntimeError(
                    "Database_Agent publish reconciliation failed "
                    f"for run_id={run_id}: HTTP {status_code}"
                ) from exc
            except httpx.TransportError:
                continue

            if document is None:
                continue
            if not self._existing_run_matches_payload(document, payload):
                raise RuntimeError(
                    "Database_Agent contains run_id="
                    f"{run_id} but its immutable identity does not match the publish payload"
                )
            return document
        return None

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
        run_id = str(payload.get("run_id") or "unknown")
        try:
            return self._post(
                "/backtests/runs",
                payload,
                correlation_id=correlation_id,
                require_data=False,
            )
        except httpx.TimeoutException as exc:
            existing = self._reconcile_backtest_publish(
                payload,
                correlation_id=correlation_id,
            )
            if existing is not None:
                return existing
            raise RuntimeError(
                "Database_Agent publish timed out and no exact persisted run "
                f"could be confirmed for run_id={run_id}; "
                f"timeout_seconds={self.timeout_seconds}"
            ) from exc
        except httpx.TransportError as exc:
            existing = self._reconcile_backtest_publish(
                payload,
                correlation_id=correlation_id,
            )
            if existing is not None:
                return existing
            raise RuntimeError(
                "Database_Agent publish transport failed and no exact persisted run "
                f"could be confirmed for run_id={run_id}; error_type={type(exc).__name__}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {409, 500}:
                existing = self._reconcile_backtest_publish(
                    payload,
                    correlation_id=correlation_id,
                )
                if existing is not None:
                    return existing
            raise

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
