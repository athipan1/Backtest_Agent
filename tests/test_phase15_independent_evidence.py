"""Phase 15: strictly descriptive, separately pinned PIT archive and v8 prereg."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.phase15_independent_evidence import (
    load_phase15_documents, phase15_documents_from_env,
    phase15_v8_evidence_validation,
)
from app.phase9_oos_fill_evidence import phase9_oos_fill_evidence


def _stamp(day: int, clock: str) -> str:
    return f"2026-01-{day:02d}T{clock}Z"


def _inputs():
    observations = []
    archives = []
    matched = []
    folds = []
    summaries = []
    for day in (2, 3, 4):
        obs_id = f"archived-{day}"
        observations.append({
            "symbol": "AAPL", "source_observation_id": obs_id,
            "regime": "BULL",
            "regime_asof_timestamp": _stamp(day, "09:30:00"),
            "regime_available_at_timestamp": _stamp(day, "09:40:00"),
            "source": "historical_point_in_time_observation",
            "dataset_fingerprint": "pinned-provider-dataset",
        })
        archives.append({
            "symbol": "AAPL", "source_observation_id": obs_id,
            "publisher_record_id": f"third-party-record-{day}",
            "regime": "BULL",
            "regime_asof_timestamp": _stamp(day, "09:30:00"),
            "regime_available_at_timestamp": _stamp(day, "09:40:00"),
            "publisher_first_seen_at": _stamp(day, "09:41:00"),
            "archive_first_seen_at": _stamp(day, "09:42:00"),
            "source_dataset_fingerprint": "pinned-provider-dataset",
        })
        matched.append({
            "fold_id": f"nested-oos-{day}",
            "strategy_id": "baseline-trend", "symbol": "AAPL",
            "source_observation_id": obs_id,
            "regime": "BULL", "entry_timestamp": _stamp(day, "10:00:00"),
            "regime_asof_timestamp": _stamp(day, "09:30:00"),
            "regime_available_at_timestamp": _stamp(day, "09:40:00"),
        })
        folds.append({
            "fold_id": f"nested-oos-{day}", "oos_start": _stamp(day, "09:00:00"),
            "oos_end": _stamp(day, "16:00:00"),
            "decision": "TRADE",
        })
        summaries.append({
            "fold_id": f"nested-oos-{day}", "strategy_id": "baseline-trend",
            "regime": "BULL", "simulated_net_pnl": 4.0,
        })
    source = {
        "contract_verified": True, "source_sha256": "b" * 64,
        "source_id": "primary-provider-dataset",
        "dataset_fingerprint": "pinned-provider-dataset",
        "observations": observations,
    }
    p13 = {"pit_join_contract_complete": True, "matched_snapshots": matched}
    p14 = {
        "oos_fold_and_regime_accounting_verified": True,
        "fold_regime_cost_summaries": summaries,
        "trade_fold_count": 3, "covered_trade_fold_count": 3,
        "regime_trade_count": 3,
    }
    fills = {"folds": folds}
    archive_data = {
        "schema_version": "phase15-archived-provider-records.v1",
        "independent_archive_id": "different-archival-source",
        "historical_feed_sha256": "b" * 64,
        "source_dataset_fingerprint": "pinned-provider-dataset",
        "records": archives,
    }
    hypothesis_data = {
        "schema_version": "phase15-preregistered-v8-hypotheses.v1",
        "registered_at": "2026-01-01T12:00:00Z",
        "maximum_hypotheses": 2, "familywise_alpha": 0.05,
        "hypotheses": [{
            "hypothesis_id": "v8-bull-trend-net-positive",
            "strategy_id": "baseline-trend", "regime": "BULL",
            "metric": "simulated_fold_net_pnl_after_costs",
            "expected_direction": "positive",
            "minimum_oos_folds": 3,
        }],
    }
    return fills, p13, p14, source, archive_data, hypothesis_data


def _write(tmp_path, name, value):
    path = tmp_path / name
    raw = json.dumps(value, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _run(tmp_path, inputs=None):
    f, p13, p14, source, archive, hyps = inputs or _inputs()
    a_path, a_digest = _write(tmp_path, "archive.json", archive)
    h_path, h_digest = _write(tmp_path, "hypothesis.json", hyps)
    documents = load_phase15_documents(
        archive_file=a_path, archive_sha256=a_digest,
        hypothesis_file=h_path, hypothesis_sha256=h_digest,
    )
    return phase15_v8_evidence_validation(f, p13, p14, source, documents)


def test_digest_pinned_archive_and_pre_oos_registry_yield_descriptive_only(tmp_path):
    result = _run(tmp_path)
    assert result["auxiliary_documents_contract_consistent"] is True
    assert result["archived_observations_matched"] == 3
    assert result["registered_hypothesis_count"] == 1
    report = result["descriptive_hypothesis_diagnostics"][0]
    assert report["distinct_research_oos_folds"] == 3
    assert report["positive_net_fold_count"] == 3
    assert report["total_simulated_net_pnl"] == 12
    assert report["outcome"] == "descriptive_only_no_independent_hypothesis_test"
    assert report["statistically_significant"] is None
    assert result["external_archive_authenticity_verified"] is False
    assert result["external_preregistration_timestamp_verified"] is False
    assert result["independent_oos_hypothesis_validation_completed"] is False
    assert result["strategy_v8_promotion_ready"] is False
    assert result["profitability_proven"] is False
    assert result["new_strategy_evaluations_run"] == 0
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False


def test_no_configured_documents_keep_research_safe(monkeypatch):
    for env in (
        "BACKTEST_RESEARCH_V8_ARCHIVE_FILE",
        "BACKTEST_RESEARCH_V8_ARCHIVE_SHA256",
        "BACKTEST_RESEARCH_V8_HYPOTHESES_FILE",
        "BACKTEST_RESEARCH_V8_HYPOTHESES_SHA256",
    ):
        monkeypatch.delenv(env, raising=False)
    docs = phase15_documents_from_env()
    assert docs["archive"]["status"] == "not_configured"
    assert docs["hypotheses"]["status"] == "not_configured"
    f, p13, p14, source, *_ = _inputs()
    result = phase15_v8_evidence_validation(f, p13, p14, source, docs)
    assert result["descriptive_hypothesis_diagnostics"] == []
    assert "independent_archive_document_not_verified" in result["error_codes"]
    assert "preregistered_hypothesis_document_not_verified" in result["error_codes"]


def test_tampered_bytes_malformed_checksum_and_bad_schema_fail_closed(tmp_path):
    inputs = _inputs()
    a_path, digest = _write(tmp_path, "archive.json", inputs[4])
    h_path, h_digest = _write(tmp_path, "hyps.json", inputs[5])
    assert load_phase15_documents(
        archive_file=a_path, archive_sha256="z" * 64
    )["archive"]["status"] == "path_or_digest_invalid"
    assert load_phase15_documents(
        archive_file=a_path, archive_sha256="0" * 64
    )["archive"]["status"] == "sha256_mismatch"
    a_path.write_bytes(a_path.read_bytes() + b"\n")
    assert load_phase15_documents(
        archive_file=a_path, archive_sha256=digest
    )["archive"]["data"] is None
    h_path.write_text("{broken")
    broken_digest = hashlib.sha256(h_path.read_bytes()).hexdigest()
    assert load_phase15_documents(
        hypothesis_file=h_path, hypothesis_sha256=broken_digest
    )["hypotheses"]["status"] == "unreadable_document"
    assert load_phase15_documents(
        hypothesis_file=h_path, hypothesis_sha256=h_digest
    )["hypotheses"]["status"] == "sha256_mismatch"


def test_late_archive_first_seen_rejected_even_when_regime_label_matches(tmp_path):
    values = _inputs()
    values[4]["records"][0]["archive_first_seen_at"] = _stamp(2, "10:20:00")
    report = _run(tmp_path, values)
    assert "archive_mismatch_or_post_entry_first_seen" in report["error_codes"]
    assert not report["auxiliary_documents_contract_consistent"]


def test_changed_regime_label_and_source_fingerprint_are_rejected(tmp_path):
    values = _inputs()
    values[4]["records"][0]["regime"] = "BEAR"
    assert "archive_mismatch_or_post_entry_first_seen" in _run(
        tmp_path, values
    )["error_codes"]
    values = _inputs()
    values[4]["source_dataset_fingerprint"] = "different-dataset"
    assert "archive_source_identity_or_dataset_mismatch" in _run(
        tmp_path, values
    )["error_codes"]


def test_missing_referenced_archive_record_is_rejected(tmp_path):
    values = _inputs()
    values[4]["records"].pop()
    report = _run(tmp_path, values)
    assert "missing_archive_correspondence" in report["error_codes"]
    assert report["descriptive_hypothesis_diagnostics"] == []


def test_duplicate_archive_record_ids_and_missing_fields_fail_closed(tmp_path):
    values = _inputs()
    values[4]["records"].append(deepcopy(values[4]["records"][0]))
    assert "duplicate_archive_record_identity" in _run(tmp_path, values)["error_codes"]
    values = _inputs()
    values[4]["records"][1].pop("publisher_record_id")
    assert "invalid_archive_record" in _run(tmp_path, values)["error_codes"]


def test_late_hypothesis_registration_or_naive_timestamp_cannot_pass(tmp_path):
    values = _inputs()
    values[5]["registered_at"] = "2026-01-02T11:00:00Z"
    assert "hypothesis_preregistration_contract_invalid_or_post_oos" in \
        _run(tmp_path, values)["error_codes"]
    values = _inputs()
    values[5]["registered_at"] = "2026-01-01T12:00:00"
    assert "hypothesis_preregistration_contract_invalid_or_post_oos" in \
        _run(tmp_path, values)["error_codes"]


def test_invalid_trial_budget_alpha_and_duplicate_hypotheses_rejected(tmp_path):
    for problem in ("budget", "alpha", "duplicate"):
        values = _inputs()
        if problem == "budget":
            values[5]["maximum_hypotheses"] = 0
            expected = "hypothesis_preregistration_contract_invalid_or_post_oos"
        elif problem == "alpha":
            values[5]["familywise_alpha"] = 0.1
            expected = "hypothesis_preregistration_contract_invalid_or_post_oos"
        else:
            values[5]["hypotheses"].append(deepcopy(values[5]["hypotheses"][0]))
            expected = "invalid_or_duplicate_preregistered_hypothesis"
        assert expected in _run(tmp_path, values)["error_codes"]


def test_one_fold_in_insufficient_coverage_is_diagnostic_not_strategy_pass(tmp_path):
    values = _inputs()
    values[5]["hypotheses"][0]["minimum_oos_folds"] = 5
    result = _run(tmp_path, values)
    assert result["auxiliary_documents_contract_consistent"] is False
    assert result["descriptive_hypothesis_diagnostics"][0][
        "outcome"
    ] == "insufficient_distinct_oos_folds"
    assert result["descriptive_hypothesis_diagnostics"][0][
        "fold_coverage_sufficient_for_description"
    ] is False


def test_upstream_phase14_or_pit_integrity_failure_blocks_all_descriptions(tmp_path):
    values = _inputs()
    values[2]["oos_fold_and_regime_accounting_verified"] = False
    result = _run(tmp_path, values)
    assert "phase14_cross_fold_integrity_unverified" in result["error_codes"]
    assert result["descriptive_hypothesis_diagnostics"] == []
    values = _inputs()
    values[1]["pit_join_contract_complete"] = False
    assert "phase13_pit_join_incomplete" in _run(tmp_path, values)["error_codes"]


def test_source_identity_matches_by_record_id_not_only_regime_label(tmp_path):
    values = _inputs()
    values[1]["matched_snapshots"][0]["source_observation_id"] = "bogus-id"
    assert "missing_archive_correspondence" in _run(tmp_path, values)["error_codes"]
    values = _inputs()
    values[4]["independent_archive_id"] = values[3]["source_id"]
    assert "archive_source_identity_or_dataset_mismatch" in _run(
        tmp_path, values
    )["error_codes"]


def test_missing_or_nonfinite_historical_fold_pnl_fails_closed(tmp_path):
    values = _inputs()
    values[2]["fold_regime_cost_summaries"][0]["simulated_net_pnl"] = float("nan")
    assert "invalid_phase14_fold_cost_summaries" in _run(tmp_path, values)["error_codes"]
    values = _inputs()
    values[2]["fold_regime_cost_summaries"] = None
    assert "invalid_phase14_fold_cost_summaries" in _run(tmp_path, values)["error_codes"]


@pytest.mark.parametrize("item", [None, {}, [], False, 1, "wrong"])
def test_invalid_inputs_fail_closed_without_promotions(item):
    result = phase15_v8_evidence_validation(item, item, item, item, item)
    assert result["auxiliary_documents_contract_consistent"] is False
    assert result["strategy_v8_promotion_ready"] is False
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False


def test_research_phase9_artifact_includes_phase15_missing_feed_reasons():
    report = phase9_oos_fill_evidence(None)
    result = report["phase15_independent_evidence"]
    assert result["auxiliary_documents_contract_consistent"] is False
    assert "independent_archive_document_not_verified" in result["error_codes"]
    assert result["new_strategy_evaluations_run"] == 0
    assert report["promotion_allowed"] is False
    assert report["execution_allowed"] is False


def test_env_can_load_both_files_when_explicitly_set(tmp_path, monkeypatch):
    values = _inputs()
    a, ad = _write(tmp_path, "archive.json", values[4])
    h, hd = _write(tmp_path, "hypothesis.json", values[5])
    for key, val in {
        "BACKTEST_RESEARCH_V8_ARCHIVE_FILE": str(a),
        "BACKTEST_RESEARCH_V8_ARCHIVE_SHA256": ad,
        "BACKTEST_RESEARCH_V8_HYPOTHESES_FILE": str(h),
        "BACKTEST_RESEARCH_V8_HYPOTHESES_SHA256": hd,
    }.items():
        monkeypatch.setenv(key, val)
    docs = phase15_documents_from_env()
    assert docs["archive"]["sha256"] == ad
    assert docs["hypotheses"]["sha256"] == hd
