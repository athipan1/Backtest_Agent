from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app import hourly_promotion_runner as promotion
from app.nested_validation_v4 import (
    VALIDATION_PROFILE as NESTED_VALIDATION_PROFILE,
    run_walk_forward_multi_strategy_backtest_v4,
)
from app.research_candidate_profiles import (
    STRATEGY_RESEARCH_V6_PROFILE_ID,
    research_profile,
)
from app.research_overfit import PBOCriteria, run_cscv_pbo
from app.research_trial_registry import (
    build_trial_registry_snapshot,
    statistical_trial_count,
)
from app.statistical_validation import equity_returns


EXPECTED_PRE_HOLDOUT_REJECTIONS: tuple[tuple[str, str], ...] = (
    ("nested selection method mismatch", "nested_validation"),
    ("nested walk-forward validation is incomplete", "nested_validation"),
    (
        "new production promotion requires statistical-validation.v2 evidence",
        "statistical_validation",
    ),
    ("selected strategy statistical validation did not pass", "statistical_validation"),
    ("selected strategy statistical gates did not all pass", "statistical_validation"),
    ("selected strategy robustness validation did not pass", "robustness_validation"),
    ("nested promotion gates failed", "nested_validation"),
)


def _expected_rejection_stage(error: Exception) -> str | None:
    message = str(error).lower()
    for fragment, stage in EXPECTED_PRE_HOLDOUT_REJECTIONS:
        if fragment in message:
            return stage
    return None


def _profile_metadata(profile_id: str, candidates: list[Any]) -> dict[str, Any]:
    try:
        trial_count = statistical_trial_count(profile_id)
    except ValueError:
        trial_count = len(candidates)
    return {
        "profile_id": profile_id,
        "candidate_count": len(candidates),
        "candidate_ids": [candidate.strategy_id for candidate in candidates],
        "strategy_families": [candidate.strategy for candidate in candidates],
        "statistical_trial_count": trial_count,
    }


def _write_reports(report_path: Path, output: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(output, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    data = output.get("data") if isinstance(output.get("data"), dict) else {}
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "unknown").lower()
        safe_symbol = "".join(
            character if character.isalnum() else "-" for character in symbol
        )
        safe_symbol = safe_symbol.strip("-") or "unknown"
        (report_path.parent / f"research-{safe_symbol}.json").write_text(
            json.dumps(item, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _pbo_criteria_from_env() -> PBOCriteria:
    return PBOCriteria(
        enabled=True,
        slice_count=int(os.getenv("BACKTEST_RESEARCH_PBO_SLICES", "8")),
        min_observations_per_slice=int(
            os.getenv("BACKTEST_RESEARCH_PBO_MIN_OBSERVATIONS_PER_SLICE", "10")
        ),
        max_probability_of_backtest_overfit=float(
            os.getenv("BACKTEST_RESEARCH_MAX_PBO", "0.20")
        ),
    )


def _candidate_return_series(request: Any) -> dict[str, list[float]]:
    series: dict[str, list[float]] = {}
    for candidate in request.candidates:
        if not candidate.strategy_id:
            raise RuntimeError("PBO research requires explicit candidate strategy_id")
        run_request = promotion.build_run_request(candidate, request).model_copy(
            deep=True,
            update={"force_close_at_end": True},
        )
        result = promotion.run_backtest_with_risk(run_request)
        series[candidate.strategy_id] = equity_returns(result)
    return series


def _cost_stress_multipliers() -> tuple[float, ...]:
    raw = os.getenv("BACKTEST_RESEARCH_COST_STRESS_MULTIPLIERS", "1.0,1.5,2.0")
    values = tuple(sorted({float(value.strip()) for value in raw.split(",") if value.strip()}))
    if not values or any(value <= 0 for value in values):
        raise RuntimeError("Research cost stress multipliers must contain positive values")
    return values


def _run_cost_stress(candidate: Any, request: Any) -> dict[str, Any]:
    base_request = promotion.build_run_request(candidate, request).model_copy(
        deep=True,
        update={"force_close_at_end": True},
    )
    minimum_fee_bps = float(os.getenv("BACKTEST_RESEARCH_MIN_FEE_BPS", "1.0"))
    minimum_slippage_bps = float(
        os.getenv("BACKTEST_RESEARCH_MIN_SLIPPAGE_BPS", "5.0")
    )
    minimum_market_impact_bps = float(
        os.getenv("BACKTEST_RESEARCH_MIN_MARKET_IMPACT_BPS", "2.0")
    )
    scenarios: list[dict[str, Any]] = []
    min_trades = int(request.statistical_criteria.min_trades)

    for multiplier in _cost_stress_multipliers():
        stressed_request = base_request.model_copy(
            deep=True,
            update={
                "fee_bps": max(base_request.fee_bps, minimum_fee_bps) * multiplier,
                "slippage_bps": max(
                    base_request.slippage_bps,
                    minimum_slippage_bps,
                )
                * multiplier,
                "market_impact_bps": max(
                    base_request.market_impact_bps,
                    minimum_market_impact_bps,
                )
                * multiplier,
            },
        )
        result = promotion.run_backtest_with_risk(stressed_request)
        metrics = result.metrics
        positive_return = metrics.return_pct > 0
        profit_factor_gate = metrics.profit_factor >= 1.0
        trade_count_gate = metrics.trade_count >= min_trades
        scenario_passed = positive_return and profit_factor_gate and trade_count_gate
        scenarios.append(
            {
                "multiplier": multiplier,
                "fee_bps": stressed_request.fee_bps,
                "slippage_bps": stressed_request.slippage_bps,
                "market_impact_bps": stressed_request.market_impact_bps,
                "return_pct": metrics.return_pct,
                "profit_factor": metrics.profit_factor,
                "trade_count": metrics.trade_count,
                "gates": {
                    "positive_net_return": positive_return,
                    "profit_factor": profit_factor_gate,
                    "trade_count": trade_count_gate,
                },
                "passed": scenario_passed,
            }
        )

    passed = all(scenario["passed"] for scenario in scenarios)
    return {
        "schema_version": "research-cost-stress.v1",
        "passed": passed,
        "min_fee_bps": minimum_fee_bps,
        "min_slippage_bps": minimum_slippage_bps,
        "min_market_impact_bps": minimum_market_impact_bps,
        "scenarios": scenarios,
        "reasons": []
        if passed
        else ["Selected strategy did not preserve positive net edge under cost stress"],
    }


def _trial_snapshot(
    *,
    profile_id: str,
    candidates: list[Any],
    dataset_fingerprint: str,
) -> dict[str, Any] | None:
    try:
        return build_trial_registry_snapshot(
            profile_id=profile_id,
            candidate_ids=[candidate.strategy_id for candidate in candidates],
            dataset_fingerprint=dataset_fingerprint,
        )
    except ValueError:
        return None


def run_pre_holdout_research(
    *,
    profile_id: str,
    report_path: Path,
) -> dict[str, Any]:
    """Evaluate a research profile while keeping the sealed holdout unopened.

    This path deliberately owns no Database client, publication call, promotion
    lifecycle, Risk/Execution hand-off, or final-holdout evaluation. It fetches
    enough history to reserve the production holdout, then exposes only the
    earlier research slice to nested v4 selection, full statistical validation,
    robustness validation and, for v6+, preregistered overfit/cost controls.
    """

    if os.getenv("PUBLISH_TO_DATABASE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }:
        raise RuntimeError("Research evaluator refuses PUBLISH_TO_DATABASE=true")
    os.environ["PUBLISH_TO_DATABASE"] = "false"

    candidates = research_profile(profile_id)
    profile = _profile_metadata(profile_id, candidates)
    pbo_required = profile_id == STRATEGY_RESEARCH_V6_PROFILE_ID
    symbols = promotion._symbols_from_env()
    timeframe = os.getenv("BACKTEST_TIMEFRAME", "1d")
    default_start, default_end = promotion._default_date_range()
    start = os.getenv("BACKTEST_START") or default_start
    end = os.getenv("BACKTEST_END") or default_end
    minimum_research_bars = int(
        os.getenv(
            "BACKTEST_NESTED_MINIMUM_BARS",
            str(promotion.DEFAULT_MINIMUM_BARS),
        )
    )
    holdout_criteria = promotion._final_holdout_criteria()
    if not holdout_criteria.enabled:
        raise RuntimeError(
            "Pre-holdout research requires BACKTEST_FINAL_HOLDOUT_ENABLED=true "
            "so the production holdout can be reserved without being evaluated"
        )
    minimum_bars = minimum_research_bars + holdout_criteria.bars
    bar_limit = int(os.getenv("BACKTEST_BAR_LIMIT", "10000"))

    provider = promotion.AlpacaMarketDataProvider(
        api_key=os.getenv("ALPACA_API_KEY_ID", ""),
        secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        base_url=os.getenv("ALPACA_DATA_API_URL", "https://data.alpaca.markets"),
        feed=os.getenv("ALPACA_DATA_FEED", "iex"),
    )

    items: list[dict[str, Any]] = []
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
            research_bars, sealed_holdout_bars = promotion.split_sealed_final_holdout(
                bars,
                criteria=holdout_criteria,
                minimum_research_bars=minimum_research_bars,
            )
            research_fingerprint = promotion.dataset_fingerprint({symbol: research_bars})
            trial_registry = _trial_snapshot(
                profile_id=profile_id,
                candidates=candidates,
                dataset_fingerprint=research_fingerprint,
            )
            request = promotion.WalkForwardMultiStrategyRequest(
                candidates=[candidate.model_copy(deep=True) for candidate in candidates],
                **promotion._request_kwargs(symbol=symbol, bars=research_bars),
            )
            pbo_evidence = None
            if pbo_required:
                pbo_evidence = run_cscv_pbo(
                    _candidate_return_series(request),
                    criteria=_pbo_criteria_from_env(),
                )
            selection = run_walk_forward_multi_strategy_backtest_v4(request)
            sealed_holdout = {
                "enabled": True,
                "status": "sealed_not_opened",
                "bar_count": len(sealed_holdout_bars),
                "evaluation_allowed": False,
            }

            if selection.best_eligible is None:
                items.append(
                    {
                        "symbol": symbol,
                        "status": "no_eligible_strategy",
                        "selected_strategy_id": None,
                        "pre_holdout_passed": False,
                        "rejection_stage": "nested_selection",
                        "rejection_reason": "no candidate passed nested v4 selection",
                        "research_dataset_fingerprint": research_fingerprint,
                        "trial_registry": trial_registry,
                        "pbo_evidence": (
                            pbo_evidence.model_dump(mode="json") if pbo_evidence else None
                        ),
                        "cost_stress_evidence": None,
                        "selection": selection.model_dump(mode="json"),
                        "statistical_evidence": None,
                        "robustness_evidence": None,
                        "pre_holdout_metadata": None,
                        "sealed_holdout": sealed_holdout,
                        "published": False,
                        "promoted": False,
                        "error": None,
                    }
                )
                continue

            selected_strategy_id = selection.best_eligible.strategy_id
            candidate = promotion._selected_candidate(request, selected_strategy_id)
            run_request = promotion.build_run_request(candidate, request).model_copy(
                deep=True,
                update={"force_close_at_end": True},
            )
            selected_result = promotion.run_backtest_with_risk(run_request)
            statistical_evidence = promotion.run_statistical_validation(
                selected_result,
                candidate_count=int(profile["statistical_trial_count"]),
                periods_per_year=request.periods_per_year,
                criteria=request.statistical_criteria,
            )
            robustness_evidence = promotion.run_promotion_robustness(run_request)

            if pbo_evidence is not None and not pbo_evidence.passed:
                items.append(
                    {
                        "symbol": symbol,
                        "status": "no_eligible_strategy",
                        "selected_strategy_id": selected_strategy_id,
                        "pre_holdout_passed": False,
                        "rejection_stage": "overfit_probability",
                        "rejection_reason": "CSCV Probability of Backtest Overfitting gate did not pass",
                        "research_dataset_fingerprint": research_fingerprint,
                        "trial_registry": trial_registry,
                        "pbo_evidence": pbo_evidence.model_dump(mode="json"),
                        "cost_stress_evidence": None,
                        "selection": selection.model_dump(mode="json"),
                        "statistical_evidence": statistical_evidence.model_dump(mode="json"),
                        "robustness_evidence": robustness_evidence.model_dump(mode="json"),
                        "pre_holdout_metadata": None,
                        "sealed_holdout": sealed_holdout,
                        "result": selected_result.model_dump(mode="json"),
                        "published": False,
                        "promoted": False,
                        "error": None,
                    }
                )
                continue

            cost_stress_evidence = _run_cost_stress(candidate, request) if pbo_required else None
            if cost_stress_evidence is not None and not cost_stress_evidence["passed"]:
                items.append(
                    {
                        "symbol": symbol,
                        "status": "no_eligible_strategy",
                        "selected_strategy_id": selected_strategy_id,
                        "pre_holdout_passed": False,
                        "rejection_stage": "cost_stress",
                        "rejection_reason": "Selected strategy failed conservative transaction-cost stress",
                        "research_dataset_fingerprint": research_fingerprint,
                        "trial_registry": trial_registry,
                        "pbo_evidence": pbo_evidence.model_dump(mode="json") if pbo_evidence else None,
                        "cost_stress_evidence": cost_stress_evidence,
                        "selection": selection.model_dump(mode="json"),
                        "statistical_evidence": statistical_evidence.model_dump(mode="json"),
                        "robustness_evidence": robustness_evidence.model_dump(mode="json"),
                        "pre_holdout_metadata": None,
                        "sealed_holdout": sealed_holdout,
                        "result": selected_result.model_dump(mode="json"),
                        "published": False,
                        "promoted": False,
                        "error": None,
                    }
                )
                continue

            try:
                pre_holdout_metadata = promotion._pre_holdout_metadata(
                    selection,
                    statistical_evidence,
                    robustness_evidence,
                    statistical_criteria=request.statistical_criteria,
                )
            except RuntimeError as exc:
                stage = _expected_rejection_stage(exc)
                if stage is None:
                    raise
                items.append(
                    {
                        "symbol": symbol,
                        "status": "no_eligible_strategy",
                        "selected_strategy_id": selected_strategy_id,
                        "pre_holdout_passed": False,
                        "rejection_stage": stage,
                        "rejection_reason": str(exc),
                        "research_dataset_fingerprint": research_fingerprint,
                        "trial_registry": trial_registry,
                        "pbo_evidence": pbo_evidence.model_dump(mode="json") if pbo_evidence else None,
                        "cost_stress_evidence": cost_stress_evidence,
                        "selection": selection.model_dump(mode="json"),
                        "statistical_evidence": statistical_evidence.model_dump(mode="json"),
                        "robustness_evidence": robustness_evidence.model_dump(mode="json"),
                        "pre_holdout_metadata": None,
                        "sealed_holdout": sealed_holdout,
                        "result": selected_result.model_dump(mode="json"),
                        "published": False,
                        "promoted": False,
                        "error": None,
                    }
                )
                continue

            pre_holdout_metadata = dict(pre_holdout_metadata)
            pre_holdout_metadata["validation_profile"] = NESTED_VALIDATION_PROFILE
            items.append(
                {
                    "symbol": symbol,
                    "status": "pre_holdout_candidate",
                    "selected_strategy_id": selected_strategy_id,
                    "pre_holdout_passed": True,
                    "rejection_stage": None,
                    "rejection_reason": None,
                    "research_dataset_fingerprint": research_fingerprint,
                    "trial_registry": trial_registry,
                    "pbo_evidence": pbo_evidence.model_dump(mode="json") if pbo_evidence else None,
                    "cost_stress_evidence": cost_stress_evidence,
                    "selection": selection.model_dump(mode="json"),
                    "statistical_evidence": statistical_evidence.model_dump(mode="json"),
                    "robustness_evidence": robustness_evidence.model_dump(mode="json"),
                    "pre_holdout_metadata": pre_holdout_metadata,
                    "sealed_holdout": sealed_holdout,
                    "result": selected_result.model_dump(mode="json"),
                    "published": False,
                    "promoted": False,
                    "error": None,
                }
            )
        except Exception as exc:
            items.append(
                {
                    "symbol": symbol,
                    "status": "failed",
                    "selected_strategy_id": None,
                    "pre_holdout_passed": False,
                    "published": False,
                    "promoted": False,
                    "sealed_holdout": {
                        "enabled": True,
                        "status": "sealed_not_opened",
                        "evaluation_allowed": False,
                    },
                    "error": str(exc),
                }
            )

    pre_holdout_candidates = [
        item["symbol"] for item in items if item["status"] == "pre_holdout_candidate"
    ]
    ineligible = [
        item["symbol"] for item in items if item["status"] == "no_eligible_strategy"
    ]
    failed = [item["symbol"] for item in items if item["status"] == "failed"]
    output = {
        "status": "success" if not failed else "error",
        "agent_type": "backtest-agent",
        "data": {
            "mode": "sealed_pre_holdout_research",
            "validation_profile": NESTED_VALIDATION_PROFILE,
            "research_only": True,
            "research_profile": profile,
            "symbols": symbols,
            "items": items,
            "pre_holdout_candidate_symbols": pre_holdout_candidates,
            "ineligible_symbols": ineligible,
            "failed_symbols": failed,
            "pre_holdout_candidate_count": len(pre_holdout_candidates),
            "ineligible_count": len(ineligible),
            "failed_count": len(failed),
            "holdout_reserved": True,
            "holdout_opened_count": 0,
            "final_holdout_bars": holdout_criteria.bars,
            "minimum_research_bars": minimum_research_bars,
            "minimum_bars": minimum_bars,
            "pbo_required": pbo_required,
            "cost_stress_required": pbo_required,
            "database_publish_allowed": False,
            "promotion_allowed": False,
            "execution_allowed": False,
            "no_trade_is_success": True,
        },
        "error": None if not failed else "One or more research symbols failed operationally.",
    }
    _write_reports(report_path, output)
    return output
