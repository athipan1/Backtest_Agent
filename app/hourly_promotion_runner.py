from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.data_provider import AlpacaMarketDataProvider, dataset_fingerprint
from app.database_client import DatabaseAgentClient
from app.multi_strategy import build_run_request, resolve_strategy_id
from app.multi_strategy_walk_forward import (
    WalkForwardMultiStrategyRequest,
    run_walk_forward_multi_strategy_backtest,
)
from app.promotion_lifecycle import create_and_advance_backtest_promotion
from app.promotion_robustness import run_promotion_robustness
from app.publisher import ENGINE_VERSION, publish_backtest_result
from app.risk_engine import run_backtest_with_risk
from app.statistical_validation import run_statistical_validation


VALIDATION_PROFILE = "nested_walk_forward_v2"
SELECTION_METHOD = "nested_train_select_test_evaluate"
DEFAULT_HISTORY_DAYS = 5 * 365
DEFAULT_MINIMUM_BARS = 630


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _symbols_from_env() -> list[str]:
    raw = os.getenv("BACKTEST_SYMBOLS") or os.getenv("BACKTEST_SYMBOL", "AAPL")
    symbols = list(
        dict.fromkeys(
            item.strip().upper()
            for item in raw.split(",")
            if item.strip()
        )
    )
    if not symbols:
        raise ValueError("BACKTEST_SYMBOLS must contain at least one symbol")
    invalid = [
        symbol
        for symbol in symbols
        if re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", symbol) is None
    ]
    if invalid:
        raise ValueError(f"BACKTEST_SYMBOLS contains invalid symbols: {invalid}")
    max_symbols = int(os.getenv("BACKTEST_MAX_SYMBOLS", "10"))
    if len(symbols) > max_symbols:
        raise ValueError(
            f"BACKTEST_SYMBOLS contains {len(symbols)} symbols; maximum is {max_symbols}"
        )
    return symbols


def _default_date_range() -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=DEFAULT_HISTORY_DAYS)
    return start.isoformat(), end.isoformat()


def _walk_forward_criteria() -> dict[str, Any]:
    legacy_minimum = os.getenv("BACKTEST_WALK_FORWARD_MIN_TRAIN_ELIGIBLE_RATE")
    eligible_minimum = float(
        os.getenv("BACKTEST_WALK_FORWARD_MIN_ELIGIBLE_SELECTION_RATE")
        or legacy_minimum
        or "0.50"
    )
    return {
        "train_bars": int(os.getenv("BACKTEST_WALK_FORWARD_TRAIN_BARS", "126")),
        "test_bars": int(os.getenv("BACKTEST_WALK_FORWARD_TEST_BARS", "126")),
        "step_bars": int(os.getenv("BACKTEST_WALK_FORWARD_STEP_BARS", "126")),
        "embargo_bars": int(os.getenv("BACKTEST_WALK_FORWARD_EMBARGO_BARS", "0")),
        "allow_overlapping_test_windows": _bool_env(
            "BACKTEST_WALK_FORWARD_ALLOW_OVERLAP", False
        ),
        "min_windows": int(os.getenv("BACKTEST_WALK_FORWARD_MIN_WINDOWS", "4")),
        "min_window_trades": int(
            os.getenv("BACKTEST_WALK_FORWARD_MIN_WINDOW_TRADES", "1")
        ),
        "min_train_eligible_window_rate": eligible_minimum,
        "min_eligible_selection_rate": eligible_minimum,
        "max_abstention_rate": float(
            os.getenv("BACKTEST_WALK_FORWARD_MAX_ABSTENTION_RATE", "0.50")
        ),
        "min_profitable_window_rate": float(
            os.getenv("BACKTEST_WALK_FORWARD_MIN_PROFITABLE_RATE", "0.60")
        ),
        "min_median_sharpe_ratio": float(
            os.getenv("BACKTEST_WALK_FORWARD_MIN_MEDIAN_SHARPE", "0.70")
        ),
        "min_median_profit_factor": float(
            os.getenv("BACKTEST_WALK_FORWARD_MIN_MEDIAN_PROFIT_FACTOR", "1.10")
        ),
        "max_drawdown_floor": float(
            os.getenv("BACKTEST_WALK_FORWARD_MAX_DRAWDOWN_FLOOR", "-0.20")
        ),
        "max_kill_switch_events": int(
            os.getenv("BACKTEST_WALK_FORWARD_MAX_KILL_SWITCH_EVENTS", "0")
        ),
    }


def _statistical_criteria() -> dict[str, Any]:
    return {
        "enabled": True,
        "min_observations": int(
            os.getenv("BACKTEST_STATISTICAL_MIN_OBSERVATIONS", "30")
        ),
        "min_trades": int(os.getenv("BACKTEST_STATISTICAL_MIN_TRADES", "10")),
        "max_adjusted_p_value": float(
            os.getenv("BACKTEST_STATISTICAL_MAX_ADJUSTED_P_VALUE", "0.05")
        ),
        "min_probabilistic_sharpe_ratio": float(
            os.getenv("BACKTEST_STATISTICAL_MIN_PSR", "0.95")
        ),
        "min_deflated_sharpe_probability": float(
            os.getenv("BACKTEST_STATISTICAL_MIN_DSR", "0.90")
        ),
        "min_bootstrap_annualized_return": float(
            os.getenv("BACKTEST_STATISTICAL_MIN_BOOTSTRAP_RETURN", "0.0")
        ),
        "bootstrap_confidence": float(
            os.getenv("BACKTEST_STATISTICAL_BOOTSTRAP_CONFIDENCE", "0.95")
        ),
        "bootstrap_simulations": int(
            os.getenv("BACKTEST_STATISTICAL_BOOTSTRAP_SIMULATIONS", "500")
        ),
        "bootstrap_seed": int(
            os.getenv("BACKTEST_STATISTICAL_BOOTSTRAP_SEED", "42")
        ),
    }


def _request_kwargs(*, symbol: str, bars: list[Any]) -> dict[str, Any]:
    return {
        "symbols": [symbol],
        "initial_equity": float(os.getenv("BACKTEST_INITIAL_EQUITY", "100000")),
        "bars": {symbol: bars},
        "fee_bps": float(os.getenv("BACKTEST_FEE_BPS", "0")),
        "slippage_bps": float(os.getenv("BACKTEST_SLIPPAGE_BPS", "0")),
        "risk_per_trade": float(os.getenv("BACKTEST_RISK_PER_TRADE", "0.01")),
        "max_position_pct": float(os.getenv("BACKTEST_MAX_POSITION_PCT", "0.10")),
        "stop_loss_pct": float(os.getenv("BACKTEST_STOP_LOSS_PCT", "0.03")),
        "reward_risk_ratio": float(os.getenv("BACKTEST_REWARD_RISK_RATIO", "2.0")),
        "use_risk_agent": _bool_env("BACKTEST_USE_RISK_AGENT", True),
        "max_trades_per_day": int(os.getenv("BACKTEST_MAX_TRADES_PER_DAY", "5")),
        "emergency_halt": _bool_env("BACKTEST_EMERGENCY_HALT", False),
        "force_close_at_end": _bool_env("BACKTEST_FORCE_CLOSE_AT_END", False),
        "max_total_exposure_pct": float(
            os.getenv("BACKTEST_MAX_TOTAL_EXPOSURE_PCT", "1.0")
        ),
        "max_open_positions": int(os.getenv("BACKTEST_MAX_OPEN_POSITIONS", "25")),
        "cash_reserve_pct": float(os.getenv("BACKTEST_CASH_RESERVE_PCT", "0.0")),
        "max_new_positions_per_bar": int(
            os.getenv("BACKTEST_MAX_NEW_POSITIONS_PER_BAR", "25")
        ),
        "periods_per_year": int(os.getenv("BACKTEST_PERIODS_PER_YEAR", "252")),
        "annual_risk_free_rate": float(
            os.getenv("BACKTEST_ANNUAL_RISK_FREE_RATE", "0.0")
        ),
        "max_volume_participation_pct": float(
            os.getenv("BACKTEST_MAX_VOLUME_PARTICIPATION_PCT", "1.0")
        ),
        "market_impact_bps": float(os.getenv("BACKTEST_MARKET_IMPACT_BPS", "0.0")),
        "walk_forward_criteria": _walk_forward_criteria(),
        "statistical_criteria": _statistical_criteria(),
    }


def _selected_candidate(request: WalkForwardMultiStrategyRequest, strategy_id: str):
    for candidate in request.candidates:
        if resolve_strategy_id(candidate, request) == strategy_id:
            return candidate
    raise RuntimeError(f"selected strategy not found in request candidates: {strategy_id}")


def _rate(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    rate = float(value)
    if rate < 0.0 or rate > 1.0:
        return None
    return rate


def _abstention_policy_evidence(
    evidence: dict[str, Any],
    criteria: dict[str, Any],
) -> dict[str, Any]:
    nested_gates = evidence.get("gates") or {}
    eligible_rate = _rate(evidence.get("eligible_selection_rate"))
    if eligible_rate is None:
        eligible_rate = _rate(evidence.get("train_eligible_window_rate"))

    abstention_rate = _rate(evidence.get("abstention_rate"))
    if abstention_rate is None and eligible_rate is not None:
        abstention_rate = round(1.0 - eligible_rate, 6)

    capital_deployed_rate = _rate(evidence.get("capital_deployed_rate"))
    if capital_deployed_rate is None:
        capital_deployed_rate = eligible_rate

    explicit_abstention_gate = nested_gates.get("max_abstention_rate")
    if isinstance(explicit_abstention_gate, bool):
        abstention_policy_passed = explicit_abstention_gate
    else:
        maximum = _rate(criteria.get("max_abstention_rate"))
        abstention_policy_passed = (
            abstention_rate is not None
            and maximum is not None
            and abstention_rate <= maximum
        )

    explicit_eligible_gate = nested_gates.get("eligible_selection_rate")
    if isinstance(explicit_eligible_gate, bool):
        eligible_selection_policy_passed = explicit_eligible_gate
    else:
        minimum = _rate(criteria.get("min_eligible_selection_rate"))
        eligible_selection_policy_passed = (
            eligible_rate is not None
            and minimum is not None
            and eligible_rate >= minimum
        )

    return {
        "eligible_selection_rate": eligible_rate,
        "abstention_rate": abstention_rate,
        "capital_deployed_rate": capital_deployed_rate,
        "abstention_policy_passed": abstention_policy_passed,
        "eligible_selection_policy_passed": eligible_selection_policy_passed,
    }


def _promotion_metadata(
    selection: Any,
    statistical_evidence: Any,
    robustness_evidence: Any,
    *,
    statistical_criteria: Any,
) -> dict[str, Any]:
    if selection.best_eligible is None:
        raise RuntimeError("promotion metadata requested without best_eligible")
    evidence = selection.nested_walk_forward.model_dump(mode="json")
    criteria = selection.walk_forward_criteria.model_dump(mode="json")
    statistical_policy = statistical_criteria.model_dump(mode="json")
    statistical = statistical_evidence.model_dump(mode="json")
    robustness = robustness_evidence.model_dump(mode="json")
    selected_strategy_id = selection.best_eligible.strategy_id
    latest_strategy_id = str(evidence.get("latest_selected_strategy_id") or "")
    abstention = _abstention_policy_evidence(evidence, criteria)
    gates = {
        "nested_validation_passed": evidence.get("passed") is True,
        "latest_selection_eligible": evidence.get("latest_selection_eligible") is True,
        "exact_strategy_match": latest_strategy_id == selected_strategy_id,
        "independent_test_windows": evidence.get("overlapping_test_windows") is False,
        "abstention_policy_passed": abstention["abstention_policy_passed"] is True,
        "eligible_selection_policy_passed": (
            abstention["eligible_selection_policy_passed"] is True
        ),
        "statistical_validation_enabled": statistical_policy.get("enabled") is True,
    }
    if evidence.get("selection_method") != SELECTION_METHOD:
        raise RuntimeError("nested selection method mismatch")
    if evidence.get("status") != "completed":
        raise RuntimeError("nested walk-forward validation is incomplete")
    if statistical.get("status") != "completed" or statistical.get("passed") is not True:
        raise RuntimeError("selected strategy statistical validation did not pass")
    if not statistical.get("gates") or not all(statistical["gates"].values()):
        raise RuntimeError("selected strategy statistical gates did not all pass")
    if robustness.get("status") != "completed" or robustness.get("passed") is not True:
        failed = robustness.get("failure_reasons") or []
        raise RuntimeError(
            "selected strategy robustness validation did not pass: "
            + ", ".join(str(item) for item in failed)
        )
    if not all(gates.values()):
        failed = sorted(name for name, passed in gates.items() if not passed)
        raise RuntimeError("nested promotion gates failed: " + ", ".join(failed))
    return {
        "validation_profile": VALIDATION_PROFILE,
        "evidence_version": 2,
        "selection_method": SELECTION_METHOD,
        "walk_forward_required": True,
        "walk_forward_passed": True,
        "walk_forward_status": evidence.get("status"),
        "walk_forward_stability_score": evidence.get("stability_score"),
        "walk_forward_evaluated_windows": evidence.get("evaluated_windows"),
        "walk_forward_profitable_window_rate": evidence.get("profitable_window_rate"),
        "walk_forward_train_eligible_window_rate": evidence.get(
            "train_eligible_window_rate"
        ),
        "walk_forward_eligible_selection_rate": abstention[
            "eligible_selection_rate"
        ],
        "walk_forward_abstention_rate": abstention["abstention_rate"],
        "walk_forward_capital_deployed_rate": abstention[
            "capital_deployed_rate"
        ],
        "walk_forward_trade_windows": evidence.get("trade_windows"),
        "walk_forward_no_trade_windows": evidence.get("no_trade_windows"),
        "walk_forward_median_sharpe_ratio": evidence.get("median_sharpe_ratio"),
        "walk_forward_median_profit_factor": evidence.get("median_profit_factor"),
        "walk_forward_worst_max_drawdown": evidence.get("worst_max_drawdown"),
        "walk_forward_validation": evidence,
        "walk_forward_criteria": criteria,
        "promotion_gates": gates,
        "statistical_criteria": statistical_policy,
        "statistical_evidence": statistical,
        "selection_gates": {
            f"statistical_{name}": passed
            for name, passed in statistical["gates"].items()
        },
        "robustness_validation": robustness,
        "immutable_evidence_snapshot": True,
    }


def _run_id(
    *,
    symbol: str,
    strategy_id: str,
    fingerprint: str,
    effective_parameters: dict[str, Any],
    timeframe: str,
    promotion_metadata: dict[str, Any],
) -> str:
    identity = {
        "symbol": symbol,
        "strategy_id": strategy_id,
        "dataset_fingerprint": fingerprint,
        "effective_parameters": effective_parameters,
        "timeframe": timeframe,
        "engine_version": ENGINE_VERSION,
        "validation_profile": VALIDATION_PROFILE,
        "evidence_version": promotion_metadata["evidence_version"],
        "walk_forward_criteria": promotion_metadata["walk_forward_criteria"],
        "statistical_criteria": promotion_metadata["statistical_criteria"],
        "robustness_criteria": promotion_metadata["robustness_validation"]["criteria"],
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"backtest-walk-forward-{digest[:24]}"


def run_nested_hourly_backtest(report_path: Path) -> dict[str, Any]:
    symbols = _symbols_from_env()
    timeframe = os.getenv("BACKTEST_TIMEFRAME", "1d")
    default_start, default_end = _default_date_range()
    start = os.getenv("BACKTEST_START") or default_start
    end = os.getenv("BACKTEST_END") or default_end
    minimum_bars = int(
        os.getenv("BACKTEST_NESTED_MINIMUM_BARS", str(DEFAULT_MINIMUM_BARS))
    )
    bar_limit = int(os.getenv("BACKTEST_BAR_LIMIT", "10000"))
    account_id = os.getenv("BACKTEST_ACCOUNT_ID", "1")
    skill_id = os.getenv("BACKTEST_SKILL_ID", "hourly-sma-crossover")
    publish_to_database = _bool_env("PUBLISH_TO_DATABASE", True)
    correlation_id = (
        f"backtest-nested-{os.getenv('GITHUB_RUN_ID')}"
        if os.getenv("GITHUB_RUN_ID")
        else f"backtest-nested-{uuid4()}"
    )
    provider = AlpacaMarketDataProvider(
        api_key=os.getenv("ALPACA_API_KEY_ID", ""),
        secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        base_url=os.getenv("ALPACA_DATA_API_URL", "https://data.alpaca.markets"),
        feed=os.getenv("ALPACA_DATA_FEED", "iex"),
    )
    database_client = DatabaseAgentClient()

    items: list[dict[str, Any]] = []
    strategy_ids_by_symbol: dict[str, str] = {}
    for symbol in symbols:
        try:
            bars = provider.fetch_bars(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                minimum_bars=minimum_bars,
                limit=bar_limit,
            )
            fingerprint = dataset_fingerprint({symbol: bars})
            request = WalkForwardMultiStrategyRequest(
                **_request_kwargs(symbol=symbol, bars=bars)
            )
            selection = run_walk_forward_multi_strategy_backtest(request)
            if selection.best_eligible is None:
                items.append(
                    {
                        "symbol": symbol,
                        "status": "no_eligible_strategy",
                        "selected_strategy_id": None,
                        "published": False,
                        "promoted": False,
                        "publish_status": "skipped",
                        "selection": selection.model_dump(mode="json"),
                        "error": None,
                    }
                )
                continue

            selected_strategy_id = selection.best_eligible.strategy_id
            candidate = _selected_candidate(request, selected_strategy_id)
            run_request = build_run_request(candidate, request).model_copy(
                deep=True,
                update={"force_close_at_end": True},
            )
            selected_result = run_backtest_with_risk(run_request)
            statistical_evidence = run_statistical_validation(
                selected_result,
                candidate_count=len(request.candidates),
                periods_per_year=request.periods_per_year,
                criteria=request.statistical_criteria,
            )
            robustness_evidence = run_promotion_robustness(run_request)
            metadata = _promotion_metadata(
                selection,
                statistical_evidence,
                robustness_evidence,
                statistical_criteria=request.statistical_criteria,
            )
            run_id = _run_id(
                symbol=symbol,
                strategy_id=selected_strategy_id,
                fingerprint=fingerprint,
                effective_parameters=selection.best_eligible.effective_parameters,
                timeframe=timeframe,
                promotion_metadata=metadata,
            )
            report = {
                "status": "skipped",
                "payload": None,
                "database_response": None,
            }
            promotion_record: dict[str, Any] | None = None
            if publish_to_database:
                report = publish_backtest_result(
                    request=run_request,
                    result=selected_result,
                    account_id=account_id,
                    run_id=run_id,
                    skill_id=skill_id,
                    strategy_id=selected_strategy_id,
                    timeframe=timeframe,
                    correlation_id=correlation_id,
                    metadata={
                        "multi_strategy_selected": True,
                        "multi_strategy_walk_forward_selected": True,
                        "selection_profile": "balanced_v1",
                        "selection_rank": selection.best_eligible.rank,
                        "selection_score": selection.best_eligible.score,
                        "selection_gates": metadata["selection_gates"],
                        "selection_criteria": selection.selection_criteria.model_dump(
                            mode="json"
                        ),
                        "candidate_source": selection.candidate_source,
                        "dataset_fingerprint": fingerprint,
                        "data_start": start,
                        "data_end": end,
                        "bar_count": len(bars),
                        **metadata,
                        "trigger": os.getenv("GITHUB_EVENT_NAME", "manual"),
                        "workflow": os.getenv("GITHUB_WORKFLOW", "hourly-backtest"),
                        "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
                        "workflow_run_id": os.getenv("GITHUB_RUN_ID", "unknown"),
                        "storage_only": True,
                    },
                )
            publish_status = str(report.get("status") or "failed")
            published = publish_to_database and publish_status == "success"
            if publish_to_database and not published:
                raise RuntimeError(
                    "Database publish did not succeed for selected strategy: "
                    f"{publish_status}"
                )
            if published:
                promotion_record = create_and_advance_backtest_promotion(
                    database_client,
                    account_id=account_id,
                    run_id=run_id,
                    skill_id=skill_id,
                    strategy_id=selected_strategy_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    dataset_fingerprint=fingerprint,
                    engine_version=ENGINE_VERSION,
                    validation_profile=VALIDATION_PROFILE,
                    correlation_id=correlation_id,
                    evidence_version=metadata["evidence_version"],
                )
                if promotion_record.get("state") not in {
                    "ROBUSTNESS_PASSED",
                    "APPROVED_FOR_PAPER",
                    "PAPER_OBSERVING",
                }:
                    raise RuntimeError(
                        "Promotion lifecycle did not reach a safe downstream state"
                    )
            promoted = promotion_record is not None
            strategy_ids_by_symbol[symbol] = selected_strategy_id
            items.append(
                {
                    "symbol": symbol,
                    "status": "eligible_strategy_found",
                    "run_id": run_id,
                    "selected_strategy_id": selected_strategy_id,
                    "published": published,
                    "promoted": promoted,
                    "promotion_id": (
                        promotion_record.get("promotion_id")
                        if promotion_record is not None
                        else None
                    ),
                    "promotion_state": (
                        promotion_record.get("state")
                        if promotion_record is not None
                        else None
                    ),
                    "promotion_version": (
                        promotion_record.get("version")
                        if promotion_record is not None
                        else None
                    ),
                    "publish_status": publish_status,
                    "selection": selection.model_dump(mode="json"),
                    "walk_forward": metadata,
                    "result": selected_result.model_dump(mode="json"),
                    "database_payload": report.get("payload"),
                    "database_response": report.get("database_response"),
                    "error": None,
                }
            )
        except Exception as exc:
            items.append(
                {
                    "symbol": symbol,
                    "status": "failed",
                    "selected_strategy_id": None,
                    "published": False,
                    "promoted": False,
                    "publish_status": "failed",
                    "selection": None,
                    "error": str(exc),
                }
            )

    eligible = [
        item["symbol"]
        for item in items
        if item["status"] == "eligible_strategy_found"
    ]
    ineligible = [
        item["symbol"]
        for item in items
        if item["status"] == "no_eligible_strategy"
    ]
    failed = [item["symbol"] for item in items if item["status"] == "failed"]
    published_count = sum(1 for item in items if item.get("published"))
    promoted_count = sum(1 for item in items if item.get("promoted"))
    all_succeeded = not failed
    all_eligible_published = published_count == len(eligible)
    all_eligible_promoted = (
        promoted_count == len(eligible) if publish_to_database else True
    )
    output = {
        "status": "success" if all_succeeded else "error",
        "agent_type": "backtest-agent",
        "correlation_id": correlation_id,
        "data": {
            "mode": "nested_walk_forward_multi_strategy_selection",
            "validation_profile": VALIDATION_PROFILE,
            "selection_method": SELECTION_METHOD,
            "symbols": symbols,
            "strategy_ids_by_symbol": strategy_ids_by_symbol,
            "items": items,
            "eligible_symbols": eligible,
            "ineligible_symbols": ineligible,
            "failed_symbols": failed,
            "eligible_count": len(eligible),
            "ineligible_count": len(ineligible),
            "published_count": published_count,
            "promoted_count": promoted_count,
            "published": all_succeeded
            and all_eligible_published
            and all_eligible_promoted,
            "publish_status": (
                "success"
                if all_succeeded and all_eligible_published and all_eligible_promoted
                else "partial_failure"
                if eligible or ineligible
                else "failed"
            ),
            "all_succeeded": all_succeeded,
            "selection_complete": all_succeeded,
            "walk_forward_required": True,
            "promotion_lifecycle_required": publish_to_database,
            "maximum_backtest_owned_state": "ROBUSTNESS_PASSED",
            "no_trade_is_success": True,
            "history_days": DEFAULT_HISTORY_DAYS,
            "minimum_bars": minimum_bars,
        },
        "error": (
            None
            if all_succeeded
            else "One or more nested walk-forward Backtests failed operationally."
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(output, indent=2, sort_keys=True), encoding="utf-8"
    )
    for item in items:
        item_path = report_path.parent / (
            "hourly-backtest-"
            + re.sub(r"[^a-z0-9]+", "-", item["symbol"].lower()).strip("-")
            + ".json"
        )
        item_path.write_text(
            json.dumps(item, indent=2, sort_keys=True), encoding="utf-8"
        )
    return output


def main() -> None:
    report_path = Path(
        os.getenv("BACKTEST_REPORT_PATH", "reports/hourly-backtest-result.json")
    )
    output = run_nested_hourly_backtest(report_path)
    print(json.dumps(output, indent=2, sort_keys=True))
    if output["status"] != "success":
        raise SystemExit(
            "One or more nested walk-forward Backtests failed; see report."
        )
