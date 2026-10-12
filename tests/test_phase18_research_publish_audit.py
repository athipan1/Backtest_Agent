"""Phase 18 CI requires complete, safe, immutable read-back evidence."""
import copy

from app.phase18_research_publish_audit import phase18_storage_checks


def _report():
    return {
        "status": "success",
        "data": {
            "research_only": True, "database_publish_allowed": False,
            "promotion_allowed": False, "execution_allowed": False,
            "holdout_opened_count": 0,
            "items": [
                {"symbol": "AAPL", "status": "no_eligible_strategy"},
                {"symbol": "MSFT", "status": "no_eligible_strategy"},
            ],
            "phase17_research_storage": {
                "enabled": True, "status": "stored",
                "stored_count": 2, "readback_verified_count": 2,
                "skipped": [], "promotion_allowed": False,
                "execution_allowed": False,
                "records": [
                    {
                        "evidence_id": "a" * 64, "artifact_sha256": "b" * 64,
                        "stored": True, "readback_verified": True,
                        "diagnostic_only": True, "promotion_allowed": False,
                        "execution_allowed": False,
                    },
                    {
                        "evidence_id": "c" * 64, "artifact_sha256": "d" * 64,
                        "stored": True, "readback_verified": True,
                        "diagnostic_only": True, "promotion_allowed": False,
                        "execution_allowed": False,
                    },
                ],
            },
        },
    }


def _passed(report, enabled=True):
    return all(phase18_storage_checks(report, publish_requested=enabled).values())


def test_explicit_opt_in_requires_complete_readback_for_all_no_trade_items():
    assert _passed(_report())


def test_disabled_default_cannot_masquerade_as_published():
    r = _report()
    r["data"]["phase17_research_storage"] = {
        "enabled": False, "status": "disabled", "promotion_allowed": False,
    }
    assert _passed(r, enabled=False)
    assert not _passed(r, enabled=True)
    assert not _passed(_report(), enabled=False)


def test_missing_skipped_or_duplicate_evidence_fails_closed():
    for key, val in [("stored_count", 1), ("readback_verified_count", 1),
                     ("skipped", [{"symbol": "MSFT", "reason": "failed_research"}]),
                     ("status", "partial"), ("enabled", False)]:
        r = _report()
        r["data"]["phase17_research_storage"][key] = val
        assert not _passed(r), key
    r = _report()
    r["data"]["phase17_research_storage"]["records"].pop()
    assert not _passed(r)
    r = _report()
    r["data"]["phase17_research_storage"]["records"][1]["evidence_id"] = "a" * 64
    assert not _passed(r)


def test_mismatch_and_unsafe_authorization_cannot_pass():
    for key, value in [
        ("readback_verified", False), ("stored", False),
        ("diagnostic_only", False), ("promotion_allowed", True),
        ("execution_allowed", True), ("evidence_id", "bad"),
        ("artifact_sha256", "bad"),
    ]:
        r = _report()
        r["data"]["phase17_research_storage"]["records"][0][key] = value
        assert not _passed(r), key
    for key, val in [
        ("holdout_opened_count", 1), ("database_publish_allowed", True),
        ("promotion_allowed", True), ("execution_allowed", True),
        ("research_only", False),
    ]:
        r = _report()
        r["data"][key] = val
        assert not _passed(r), key
    r = _report()
    r["data"]["items"][0]["status"] = "failed"
    assert not _passed(r)


def test_malformed_report_never_passes():
    assert not _passed({"status": "success", "data": {}})
    assert not _passed({"status": "success", "data": {}}, enabled=False)
