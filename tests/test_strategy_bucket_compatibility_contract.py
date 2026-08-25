from app.strategy_bucket_candidate_policy import (
    COMPATIBILITY_CONTRACT_SCHEMA,
    strategy_bucket_compatibility_contract,
)
from app.system_contract import ready


class _Response:
    status_code = 200


def test_strategy_bucket_contract_exports_authoritative_families():
    contract = strategy_bucket_compatibility_contract()

    assert contract["schema_version"] == COMPATIBILITY_CONTRACT_SCHEMA
    assert contract["profile"] == "balanced_v1"
    assert contract["bucket_strategy_families"] == {
        "core_dividend": ["trend_following", "sma_crossover"],
        "news_momentum": ["breakout", "trend_following"],
        "value_rebound": ["mean_reversion", "sma_crossover"],
    }
    assert contract["empty_intersection_outcome"] == "NO_TRADE"
    assert contract["manager_may_preflight"] is True
    assert contract["backtest_remains_authoritative"] is True
    assert contract["thresholds_relaxed"] is False


def test_readiness_exposes_compatibility_without_changing_profile(monkeypatch):
    monkeypatch.setattr(
        "app.system_contract.readiness_snapshot",
        lambda: {
            "ready": True,
            "environment": "test",
            "publishing_required": False,
            "checks": {},
        },
    )
    response = _Response()

    payload = ready(response)

    assert response.status_code == 200
    data = payload["data"]
    assert data["multi_strategy_profile"] == "balanced_v1"
    compatibility = data["strategy_bucket_compatibility"]
    assert compatibility["schema_version"] == COMPATIBILITY_CONTRACT_SCHEMA
    assert compatibility["thresholds_relaxed"] is False
