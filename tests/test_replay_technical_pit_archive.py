import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.replay_technical_pit_archive import replay_archive


def archive():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    records = []
    for symbol in ("LAUR", "JFIN"):
        for i in range(330):
            now = start + timedelta(days=i)
            records.append({
                "symbol": symbol,
                "source_observation_id": f"{symbol}-{i}",
                "timestamp": now.isoformat(),
                "indicators_available_at": now.isoformat(),
                "regime_available_at": now.isoformat(),
                "open": 100.0 + i,
                "close": 105.0,
                "sma200": 100.0,
                "rsi14": 60.0,
                "macd": 0.30,
                "macd_signal": 0.10,
                "regime": "BULL",
            })
    return {
        "schema_version": "technical-pit-research-archive.v1",
        "source_id": "fixture-archive-only",
        "research_end": (start + timedelta(days=329)).isoformat(),
        "sealed_holdout_start": (start + timedelta(days=330)).isoformat(),
        "records": records,
    }


def replay(doc):
    raw = json.dumps(doc, sort_keys=True).encode()
    return replay_archive(
        raw, pinned_sha256=hashlib.sha256(raw).hexdigest(),
        expected_source_id="fixture-archive-only",
    )


def test_research_archive_is_diagnostic_only_and_splits_symbols():
    result = replay(archive())
    assert set(result["symbols"]) == {"LAUR", "JFIN"}
    assert result["symbols"]["LAUR"]["fold_count"] > 0
    assert result["symbols"]["JFIN"]["fold_count"] > 0
    assert result["production_certified"] is False
    assert result["execution_authorized"] is False
    assert result["diagnostic_only"] is True


def test_archive_checksum_and_identity_are_required():
    raw = json.dumps(archive()).encode()
    with pytest.raises(ValueError, match="checksum"):
        replay_archive(raw, pinned_sha256="0" * 64, expected_source_id="fixture-archive-only")
    with pytest.raises(ValueError, match="identity"):
        replay_archive(
            raw, pinned_sha256=hashlib.sha256(raw).hexdigest(),
            expected_source_id="different",
        )


def test_future_publication_is_rejected():
    doc = archive()
    row = doc["records"][0]
    row["indicators_available_at"] = (
        datetime.fromisoformat(row["timestamp"]) + timedelta(days=1)
    ).isoformat()
    with pytest.raises(ValueError, match="future_research_publication"):
        replay(doc)


def test_sealed_holdout_rows_are_never_ingested():
    doc = archive()
    doc["records"][-1]["timestamp"] = doc["sealed_holdout_start"]
    with pytest.raises(ValueError, match="sealed_holdout_row_prohibited"):
        replay(doc)


def test_research_holdout_overlap_is_rejected():
    doc = archive()
    doc["research_end"] = doc["sealed_holdout_start"]
    with pytest.raises(ValueError, match="research_holdout_overlap"):
        replay(doc)
