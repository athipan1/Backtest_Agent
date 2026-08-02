from __future__ import annotations

import os
from typing import Any


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def environment_name() -> str:
    return (
        os.getenv("BACKTEST_ENV")
        or os.getenv("ENVIRONMENT")
        or "development"
    ).strip().lower()


def readiness_snapshot() -> dict[str, Any]:
    environment = environment_name()
    production = environment in {"production", "prod"}
    publishing_required = _bool_env("PUBLISH_TO_DATABASE", False)
    api_key_configured = bool(os.getenv("BACKTEST_API_KEY", ""))
    database_url_configured = bool(os.getenv("DATABASE_AGENT_URL", ""))
    database_api_key_configured = bool(
        os.getenv("DATABASE_AGENT_API_KEY", "")
    )

    checks = {
        "api_key_policy": {
            "critical": production,
            "ok": (not production) or api_key_configured,
            "detail": (
                "configured"
                if api_key_configured
                else "required only in production"
                if not production
                else "BACKTEST_API_KEY is missing"
            ),
        },
        "database_url": {
            "critical": publishing_required,
            "ok": (not publishing_required) or database_url_configured,
            "detail": (
                "configured"
                if database_url_configured
                else "publishing is disabled"
                if not publishing_required
                else "DATABASE_AGENT_URL is missing"
            ),
        },
        "database_api_key": {
            "critical": publishing_required and production,
            "ok": (
                not (publishing_required and production)
                or database_api_key_configured
            ),
            "detail": (
                "configured"
                if database_api_key_configured
                else "not required for this environment"
                if not (publishing_required and production)
                else "DATABASE_AGENT_API_KEY is missing"
            ),
        },
    }
    ready = all(
        check["ok"]
        for check in checks.values()
        if check["critical"]
    )
    return {
        "ready": ready,
        "environment": environment,
        "production": production,
        "publishing_required": publishing_required,
        "checks": checks,
    }
