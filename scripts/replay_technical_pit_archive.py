#!/usr/bin/env python3
"""Replay independently archived PIT indicators; no production promotion.

The archive must contain only research-period rows. A pinned SHA-256 must be
provided out of band. The script never downloads data or opens a holdout.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from app.technical_research_replay import nested_pit_diagnostics


ALLOWED = frozenset({"LAUR", "JFIN"})
SCHEMA = "technical-pit-research-archive.v1"


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing_timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("naive_timestamp")
    return parsed


def replay_archive(
    raw: bytes, *, pinned_sha256: str, expected_source_id: str,
) -> dict[str, Any]:
    digest = hashlib.sha256(raw).hexdigest()
    if not pinned_sha256 or digest != pinned_sha256.lower():
        raise ValueError("archive_checksum_mismatch")
    archive = json.loads(raw)
    if archive.get("schema_version") != SCHEMA:
        raise ValueError("unknown_archive_schema")
    if archive.get("source_id") != expected_source_id or not expected_source_id:
        raise ValueError("source_identity_mismatch")
    research_end = _time(archive.get("research_end"))
    holdout_start = _time(archive.get("sealed_holdout_start"))
    if research_end >= holdout_start:
        raise ValueError("research_holdout_overlap")
    records = archive.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("empty_research_archive")
    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in sorted(ALLOWED)}
    for record in records:
        if not isinstance(record, dict) or record.get("symbol") not in ALLOWED:
            raise ValueError("unknown_research_symbol")
        when = _time(record.get("timestamp"))
        if when > research_end or when >= holdout_start:
            raise ValueError("sealed_holdout_row_prohibited")
        indicator_available = _time(record.get("indicators_available_at"))
        regime_available = _time(record.get("regime_available_at"))
        if indicator_available > when or regime_available > when:
            raise ValueError("future_research_publication")
        if not record.get("source_observation_id"):
            raise ValueError("missing_source_observation_id")
        grouped[record["symbol"]].append({
            **record,
            "timestamp": when,
            "indicators_as_of": indicator_available,
            "regime_as_of": regime_available,
        })
    outputs = {}
    for symbol, rows in grouped.items():
        if len(rows) < 3:
            outputs[symbol] = {"status": "insufficient_history", "fold_count": 0}
        else:
            outputs[symbol] = nested_pit_diagnostics(rows)
    return {
        "schema_version": "technical-pit-research-replay.v1",
        "source_id": expected_source_id,
        "archive_sha256": digest,
        "research_end": research_end.isoformat(),
        "sealed_holdout_start": holdout_start.isoformat(),
        "production_certified": False,
        "execution_authorized": False,
        "diagnostic_only": True,
        "symbols": outputs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.archive.read_bytes()
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("archive_too_large")
    result = replay_archive(
        raw, pinned_sha256=args.sha256, expected_source_id=args.source_id
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
