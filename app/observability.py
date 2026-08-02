from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from contextvars import ContextVar, Token
from threading import Lock
from typing import Any
from uuid import uuid4


_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CORRELATION_ID: ContextVar[str | None] = ContextVar(
    "backtest_correlation_id",
    default=None,
)
_REQUEST_LOGGER = logging.getLogger("backtest_agent.request")
_PROCESS_STARTED_AT = time.time()


def resolve_correlation_id(value: str | None) -> str:
    if value is not None:
        normalized = value.strip()
        if _CORRELATION_ID_PATTERN.fullmatch(normalized):
            return normalized
    return str(uuid4())


def set_correlation_id(value: str) -> Token[str | None]:
    return _CORRELATION_ID.set(value)


def reset_correlation_id(token: Token[str | None]) -> None:
    _CORRELATION_ID.reset(token)


def current_correlation_id() -> str | None:
    return _CORRELATION_ID.get()


def _metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._request_counts: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._duration_sums: dict[tuple[str, str], float] = defaultdict(float)
        self._validation_failures = 0
        self._authentication_failures = 0
        self._unhandled_errors = 0

    def observe_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_seconds: float,
        unhandled_error: bool = False,
    ) -> None:
        method = method.upper()
        with self._lock:
            self._request_counts[(method, path, status_code)] += 1
            self._duration_counts[(method, path)] += 1
            self._duration_sums[(method, path)] += max(0.0, duration_seconds)
            if status_code == 422:
                self._validation_failures += 1
            if path.startswith("/backtest") and status_code in {401, 403, 503}:
                self._authentication_failures += 1
            if unhandled_error:
                self._unhandled_errors += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "request_counts": dict(self._request_counts),
                "duration_counts": dict(self._duration_counts),
                "duration_sums": dict(self._duration_sums),
                "validation_failures": self._validation_failures,
                "authentication_failures": self._authentication_failures,
                "unhandled_errors": self._unhandled_errors,
            }

    def reset(self) -> None:
        with self._lock:
            self._request_counts.clear()
            self._duration_counts.clear()
            self._duration_sums.clear()
            self._validation_failures = 0
            self._authentication_failures = 0
            self._unhandled_errors = 0

    def render_prometheus(self) -> str:
        snapshot = self.snapshot()
        lines = [
            "# HELP backtest_process_start_time_seconds Unix process start time.",
            "# TYPE backtest_process_start_time_seconds gauge",
            f"backtest_process_start_time_seconds {_PROCESS_STARTED_AT:.6f}",
            "# HELP backtest_http_requests_total Total HTTP requests.",
            "# TYPE backtest_http_requests_total counter",
        ]
        for (method, path, status_code), value in sorted(
            snapshot["request_counts"].items()
        ):
            lines.append(
                "backtest_http_requests_total"
                f'{{method="{_metric_label(method)}",path="{_metric_label(path)}",'
                f'status="{status_code}"}} {value}'
            )

        lines.extend(
            [
                "# HELP backtest_http_request_duration_seconds HTTP request duration.",
                "# TYPE backtest_http_request_duration_seconds summary",
            ]
        )
        for method, path in sorted(snapshot["duration_counts"]):
            labels = (
                f'method="{_metric_label(method)}",path="{_metric_label(path)}"'
            )
            lines.append(
                "backtest_http_request_duration_seconds_count"
                f"{{{labels}}} {snapshot['duration_counts'][(method, path)]}"
            )
            lines.append(
                "backtest_http_request_duration_seconds_sum"
                f"{{{labels}}} {snapshot['duration_sums'][(method, path)]:.9f}"
            )

        scalar_metrics = [
            (
                "backtest_validation_failures_total",
                "Requests rejected by validation.",
                snapshot["validation_failures"],
            ),
            (
                "backtest_authentication_failures_total",
                "Protected Backtest requests rejected by authentication policy.",
                snapshot["authentication_failures"],
            ),
            (
                "backtest_unhandled_errors_total",
                "Unhandled request exceptions.",
                snapshot["unhandled_errors"],
            ),
        ]
        for name, help_text, value in scalar_metrics:
            lines.extend(
                [
                    f"# HELP {name} {help_text}",
                    f"# TYPE {name} counter",
                    f"{name} {value}",
                ]
            )
        return "\n".join(lines) + "\n"


METRICS = MetricsRegistry()


def route_template(scope: dict[str, Any], fallback_path: str) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    if fallback_path in {"/", "/health", "/ready", "/version", "/metrics"}:
        return fallback_path
    if fallback_path.startswith("/backtest/"):
        return "/backtest/__unknown__"
    return "/__unknown__"


def emit_request_log(
    *,
    correlation_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
    error_type: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "event": "http_request_completed",
        "correlation_id": correlation_id,
        "method": method.upper(),
        "path": path,
        "status_code": status_code,
        "duration_ms": round(duration_seconds * 1000.0, 3),
    }
    if error_type is not None:
        event["error_type"] = error_type
    _REQUEST_LOGGER.info(json.dumps(event, sort_keys=True, separators=(",", ":")))
