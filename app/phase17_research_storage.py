"""Phase 17 opt-in storage-only publisher for Phase 13–16 research evidence.

Separate from normal backtest publication and promotion. A successful write is
only storage confirmation: it never indicates profitable OOS or trade approval.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import httpx

PHASE_MAP = {
    "phase13": "phase13_historical_regime_evidence",
    "phase14": "phase14_historical_regime_validation",
    "phase15": "phase15_independent_evidence",
    "phase16": "phase16_prospective_oos_evidence",
}
FIELDS = (
    "schema_version", "error_codes", "missing_or_rejected", "readiness_blockers",
    "remaining_blockers", "source_status", "source_sha256",
    "oos_fold_and_regime_accounting_verified",
    "pit_join_contract_complete", "auxiliary_documents_contract_consistent",
    "prospective_packet_contract_consistent", "archive_document_status",
    "hypothesis_document_status", "validated_forward_fold_count",
    "research_fold_count", "trade_fold_count", "registered_hypothesis_count",
    "covered_trade_fold_count", "sealed_holdout_opened", "promotion_allowed",
    "execution_allowed", "diagnostic_only", "used_for_selection",
    "net_profitability_proven", "profitability_proven",
)
MAX_ITEM_BYTES = 2_000_000


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def build_research_evidence(item: dict[str, Any], *, profile_id: str) -> dict[str, Any]:
    if (not isinstance(item, dict) or not isinstance(item.get("symbol"), str)
            or not item["symbol"] or not isinstance(profile_id, str) or not profile_id
            or not isinstance(item.get("research_dataset_fingerprint"), str)
            or not item["research_dataset_fingerprint"]):
        raise ValueError("complete research symbol and dataset identity required")
    research = item.get("phase9_oos_fill_evidence")
    if not isinstance(research, dict):
        raise ValueError("research result has no Phase 13–16 diagnostics")
    phases: dict[str, dict[str, Any]] = {}
    for name, source_name in PHASE_MAP.items():
        phase = research.get(source_name)
        if (not isinstance(phase, dict) or not isinstance(phase.get("schema_version"), str)
                or phase.get("promotion_allowed") is not False
                or phase.get("execution_allowed") is not False
                or phase.get("sealed_holdout_opened") is not False):
            raise ValueError(f"{name} diagnostic missing or authorization unsafe")
        phases[name] = {key: phase[key] for key in FIELDS if key in phase}
        phases[name].update({
            "promotion_allowed": False, "execution_allowed": False,
            "sealed_holdout_opened": False,
        })
    raw = canonical_bytes(item)
    if len(raw) > MAX_ITEM_BYTES:
        raise ValueError("source research report exceeds expected size")
    document = {
        "schema_version": "phase17-research-evidence.v1",
        "source_agent": "Backtest_Agent", "symbol": item["symbol"].upper(),
        "research_profile": profile_id,
        "research_dataset_fingerprint": item["research_dataset_fingerprint"],
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "phases": phases,
        "research_only": True, "diagnostic_only": True,
        "used_for_selection": False, "promotion_allowed": False,
        "execution_allowed": False, "sealed_holdout_opened": False,
    }
    return {"evidence_id": _sha(document), **document}


def verify_research_evidence_readback(
    document: dict[str, Any], *, url: str, key: str,
) -> None:
    """Require independent authenticated GET and exact immutable round-trip.

    This reads diagnostic-only research storage. It cannot authorize selection,
    production publication, broker execution, or opening a sealed holdout.
    """
    evidence_id = document["evidence_id"]
    response = httpx.get(
        f"{url}/research/evidence/{evidence_id}",
        headers={"X-API-KEY": key, "X-Correlation-ID": evidence_id},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Database_Agent research readback has invalid response")
    stored = body.get("data")
    metadata = body.get("metadata")
    original = {k: v for k, v in document.items() if k != "evidence_id"}
    if (body.get("status") != "success"
            or body.get("schema_version") != "phase17-research-evidence.v1"
            or not isinstance(stored, dict)
            or not isinstance(metadata, dict)
            or stored.get("evidence_id") != evidence_id
            or stored.get("symbol") != document["symbol"]
            or stored.get("research_profile") != document["research_profile"]
            or stored.get("artifact_sha256") != document["artifact_sha256"]
            or stored.get("payload") != original
            or stored.get("research_only") is not True
            or stored.get("promotion_allowed") is not False
            or stored.get("execution_allowed") is not False
            or metadata.get("safe_for_trading") is not False
            or metadata.get("promotion_allowed") is not False
            or metadata.get("execution_allowed") is not False):
        raise RuntimeError("Database_Agent research readback does not match immutable evidence")
    if _sha(stored["payload"]) != evidence_id:
        raise RuntimeError("Database_Agent research readback digest mismatch")


def publish_research_evidence(
    item: dict[str, Any], *, profile_id: str,
    base_url: str | None = None, api_key: str | None = None,
) -> dict[str, Any]:
    """Use the separate research endpoint, without retrying uncertain POSTs."""
    document = build_research_evidence(item, profile_id=profile_id)
    url = (base_url if base_url is not None else os.getenv("DATABASE_AGENT_URL", "")).strip().rstrip("/")
    key = api_key if api_key is not None else os.getenv("DATABASE_AGENT_API_KEY", "")
    if not url.startswith(("https://", "http://")) or not key:
        raise RuntimeError("Research-only storage requires Database_Agent URL and API key")
    response = httpx.post(
        f"{url}/research/evidence", json=document,
        headers={"X-API-KEY": key, "X-Correlation-ID": document["evidence_id"]},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    stored = body.get("data") if isinstance(body, dict) else None
    if (body.get("status") != "success" or not isinstance(stored, dict)
            or stored.get("evidence_id") != document["evidence_id"]
            or stored.get("artifact_sha256") != document["artifact_sha256"]
            or stored.get("promotion_allowed") is not False
            or stored.get("execution_allowed") is not False):
        raise RuntimeError("Database_Agent research evidence acknowledgment does not match")
    verify_research_evidence_readback(document, url=url, key=key)
    return {
        "evidence_id": document["evidence_id"],
        "artifact_sha256": document["artifact_sha256"],
        "stored": True, "readback_verified": True,
        "diagnostic_only": True, "promotion_allowed": False, "execution_allowed": False,
        "idempotent_replay": body.get("metadata", {}).get("idempotent_replay") is True,
    }


def publish_research_report_if_enabled(output: dict[str, Any]) -> dict[str, Any]:
    value = os.getenv("BACKTEST_RESEARCH_EVIDENCE_PUBLISH", "false").strip().lower()
    if value not in {"1", "true", "yes", "on"}:
        return {"enabled": False, "status": "disabled", "promotion_allowed": False}
    data = output.get("data")
    if not isinstance(data, dict) or data.get("research_only") is not True:
        raise RuntimeError("Only existing research-only reports may be stored")
    if (data.get("database_publish_allowed") is not False
            or data.get("promotion_allowed") is not False
            or data.get("execution_allowed") is not False
            or data.get("holdout_opened_count") != 0):
        raise RuntimeError("Research storage refuses production or unsealed evidence")
    profile = data.get("research_profile")
    profile_id = profile.get("profile_id") if isinstance(profile, dict) else None
    if not isinstance(profile_id, str) or not profile_id:
        raise RuntimeError("Research profile identity is required")
    rows = data.get("items")
    if not isinstance(rows, list):
        raise RuntimeError("Research symbol reports are missing")
    stored = []
    skipped = []
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError("Malformed research item")
        if item.get("status") == "failed":
            skipped.append({"symbol": item.get("symbol"), "reason": "failed_research"})
            continue
        stored.append(publish_research_evidence(item, profile_id=profile_id))
    return {
        "enabled": True, "status": "stored" if stored else "no_eligible_research",
        "stored_count": len(stored),
        "readback_verified_count": sum(row.get("readback_verified") is True for row in stored),
        "skipped": skipped, "records": stored,
        "promotion_allowed": False, "execution_allowed": False,
    }
