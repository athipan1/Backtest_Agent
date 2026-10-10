"""Phase 17 storage-only evidence publishing contract and fail-closed tests."""
import copy
import hashlib
import json

import httpx
import pytest

from app.phase17_research_storage import (
    build_research_evidence,
    canonical_bytes,
    publish_research_evidence,
    publish_research_report_if_enabled,
)


def _item():
    reports = {}
    for phase, suffix in [
        ("phase13", "phase13_historical_regime_evidence"),
        ("phase14", "phase14_historical_regime_validation"),
        ("phase15", "phase15_independent_evidence"),
        ("phase16", "phase16_prospective_oos_evidence"),
    ]:
        reports[suffix] = {
            "schema_version": phase + "-synthetic.v1",
            "promotion_allowed": False, "execution_allowed": False,
            "sealed_holdout_opened": False,
            "error_codes": ["missing_future_data"],
        }
    return {
        "symbol": "AAPL",
        "status": "no_eligible_strategy",
        "research_dataset_fingerprint": "existing-research-fingerprint",
        "phase9_oos_fill_evidence": reports,
        "published": False, "promoted": False,
        "sealed_holdout": {"status": "sealed_not_opened"},
    }


def _output():
    return {
        "status": "success",
        "data": {
            "research_only": True, "database_publish_allowed": False,
            "promotion_allowed": False, "execution_allowed": False,
            "holdout_opened_count": 0,
            "research_profile": {"profile_id": "strategy_research_v7"},
            "items": [_item()],
        },
    }


def test_deterministic_storage_digest_from_real_symbol_artifact():
    item = _item()
    a = build_research_evidence(item, profile_id="strategy_research_v7")
    b = build_research_evidence(item, profile_id="strategy_research_v7")
    assert a == b
    expected = dict(a)
    digest = expected.pop("evidence_id")
    assert digest == hashlib.sha256(canonical_bytes(expected)).hexdigest()
    assert a["artifact_sha256"] == hashlib.sha256(canonical_bytes(item)).hexdigest()
    assert set(a["phases"]) == {"phase13", "phase14", "phase15", "phase16"}
    assert a["promotion_allowed"] is False
    assert a["execution_allowed"] is False
    assert a["sealed_holdout_opened"] is False
    assert "selection" not in a["phases"]
    assert all("selection" not in phase for phase in a["phases"].values())
    assert "raw_oos_fills" not in json.dumps(a)
    assert "profitability_proven" not in a


def test_missing_any_phase_or_unsafe_gate_rejected():
    for key in ("phase13_historical_regime_evidence",
                "phase14_historical_regime_validation",
                "phase15_independent_evidence",
                "phase16_prospective_oos_evidence"):
        item = _item()
        item["phase9_oos_fill_evidence"].pop(key)
        with pytest.raises(ValueError, match="diagnostic missing"):
            build_research_evidence(item, profile_id="strategy_research_v7")
    item = _item()
    item["phase9_oos_fill_evidence"]["phase16_prospective_oos_evidence"]["execution_allowed"] = True
    with pytest.raises(ValueError, match="authorization unsafe"):
        build_research_evidence(item, profile_id="strategy_research_v7")


def test_publisher_requires_url_and_key_and_never_calls_broker(monkeypatch):
    monkeypatch.delenv("DATABASE_AGENT_URL", raising=False)
    monkeypatch.delenv("DATABASE_AGENT_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="URL and API key"):
        publish_research_evidence(_item(), profile_id="strategy_research_v7")
    called = []

    def fake_post(url, *, json, headers, timeout):
        called.append((url, json, headers, timeout))
        return httpx.Response(201, json={
            "status": "success",
            "data": {
                "evidence_id": json["evidence_id"],
                "artifact_sha256": json["artifact_sha256"],
                "promotion_allowed": False, "execution_allowed": False,
            },
            "metadata": {"idempotent_replay": False},
        }, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    result = publish_research_evidence(
        _item(), profile_id="strategy_research_v7",
        base_url="https://research.example.com", api_key="test-secret",
    )
    assert result["stored"] is True
    assert result["promotion_allowed"] is False
    assert len(called) == 1
    assert called[0][0] == "https://research.example.com/research/evidence"
    assert called[0][2]["X-API-KEY"] == "test-secret"
    assert called[0][3] == 30


def test_wrong_acknowledgment_is_not_counted_as_persisted(monkeypatch):
    def bad_ack(url, *, json, headers, timeout):
        return httpx.Response(201, json={
            "status": "success",
            "data": {
                "evidence_id": "0" * 64,
                "artifact_sha256": json["artifact_sha256"],
                "promotion_allowed": False, "execution_allowed": False,
            },
        }, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", bad_ack)
    with pytest.raises(RuntimeError, match="acknowledgment"):
        publish_research_evidence(
            _item(), profile_id="strategy_research_v7",
            base_url="https://research.example.com", api_key="test-secret",
        )


def test_fails_closed_on_server_error_without_retry(monkeypatch):
    calls = []

    def fail(url, *, json, headers, timeout):
        calls.append(url)
        return httpx.Response(
            503, json={"error": "unavailable"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(httpx.HTTPStatusError):
        publish_research_evidence(
            _item(), profile_id="strategy_research_v7",
            base_url="https://research.example.com", api_key="test-secret",
        )
    assert len(calls) == 1


def test_default_research_mode_keeps_broker_publication_disabled(monkeypatch):
    monkeypatch.delenv("BACKTEST_RESEARCH_EVIDENCE_PUBLISH", raising=False)
    result = publish_research_report_if_enabled(_output())
    assert result == {
        "enabled": False, "status": "disabled", "promotion_allowed": False
    }


def test_opt_in_report_stores_only_safe_diagnostics(monkeypatch):
    captured = []

    def fake_publish(item, *, profile_id):
        captured.append((item["symbol"], profile_id))
        return {"stored": True, "evidence_id": "a" * 64}

    monkeypatch.setattr(
        "app.phase17_research_storage.publish_research_evidence", fake_publish
    )
    monkeypatch.setenv("BACKTEST_RESEARCH_EVIDENCE_PUBLISH", "true")
    output = _output()
    result = publish_research_report_if_enabled(output)
    assert result["stored_count"] == 1
    assert result["promotion_allowed"] is False
    assert captured == [("AAPL", "strategy_research_v7")]
    assert output["data"]["database_publish_allowed"] is False


def test_opt_in_still_refuses_unsafe_report_and_unsealed_holdout(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_EVIDENCE_PUBLISH", "true")
    for field, value in [
        ("research_only", False), ("database_publish_allowed", True),
        ("promotion_allowed", True), ("execution_allowed", True),
        ("holdout_opened_count", 1),
    ]:
        value_report = _output()
        value_report["data"][field] = value
        with pytest.raises(RuntimeError):
            publish_research_report_if_enabled(value_report)


def test_failed_research_symbol_is_not_fabricated_as_evidence(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_EVIDENCE_PUBLISH", "true")
    report = _output()
    report["data"]["items"][0]["status"] = "failed"
    result = publish_research_report_if_enabled(report)
    assert result["stored_count"] == 0
    assert result["skipped"][0]["reason"] == "failed_research"
