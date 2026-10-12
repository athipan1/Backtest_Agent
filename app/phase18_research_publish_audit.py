"""Phase 18 CI audit for storage-only research evidence round-trips.

This verifier never contacts a broker or enables publication. It checks the
already-produced research report, independently of the publisher's return value.
"""
from __future__ import annotations

import re
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def phase18_storage_checks(
    report: dict[str, Any], *, publish_requested: bool,
) -> dict[str, bool]:
    """Fail closed if opted-in storage did not verify *every* research item.

    A NO_TRADE research result is still an item that must be stored and read
    back. A green research job must not mask missing rows or partial writes.
    """
    data = report.get("data")
    data = data if isinstance(data, dict) else {}
    storage = data.get("phase17_research_storage")
    storage = storage if isinstance(storage, dict) else {}
    items = data.get("items")
    items = items if isinstance(items, list) else []
    safe_report = (
        report.get("status") == "success"
        and data.get("research_only") is True
        and data.get("database_publish_allowed") is False
        and data.get("promotion_allowed") is False
        and data.get("execution_allowed") is False
        and data.get("holdout_opened_count") == 0
        and bool(items)
        and all(isinstance(item, dict) and item.get("status") != "failed" for item in items)
    )

    if not publish_requested:
        return {
            "phase18_research_safety": bool(safe_report),
            "phase18_storage_disabled_by_default": (
                storage.get("enabled") is False
                and storage.get("status") == "disabled"
                and storage.get("promotion_allowed") is False
                and not storage.get("records")
                and not storage.get("stored_count")
                and not storage.get("readback_verified_count")
            ),
        }

    records = storage.get("records")
    records = records if isinstance(records, list) else []
    evidence_ids = [
        row.get("evidence_id") if isinstance(row, dict) else None
        for row in records
    ]
    expected = len(items)
    complete = (
        storage.get("enabled") is True
        and storage.get("status") == "stored"
        and type(storage.get("stored_count")) is int
        and storage["stored_count"] == expected
        and type(storage.get("readback_verified_count")) is int
        and storage["readback_verified_count"] == expected
        and len(records) == expected
        and storage.get("skipped") == []
    )
    all_verified = all(
        isinstance(row, dict)
        and row.get("stored") is True
        and row.get("readback_verified") is True
        and row.get("diagnostic_only") is True
        and row.get("promotion_allowed") is False
        and row.get("execution_allowed") is False
        and isinstance(row.get("evidence_id"), str)
        and bool(_SHA256.fullmatch(row["evidence_id"]))
        and isinstance(row.get("artifact_sha256"), str)
        and bool(_SHA256.fullmatch(row["artifact_sha256"]))
        for row in records
    )
    return {
        "phase18_research_safety": bool(safe_report),
        "phase18_storage_enabled_explicitly": storage.get("enabled") is True,
        "phase18_storage_all_items_covered": bool(complete and expected > 0),
        "phase18_storage_all_readbacks_verified": bool(
            all_verified and len(records) == expected and expected > 0
            and len(set(evidence_ids)) == expected
        ),
        "phase18_storage_no_promotion": (
            storage.get("promotion_allowed") is False
            and storage.get("execution_allowed") is False
        ),
    }
