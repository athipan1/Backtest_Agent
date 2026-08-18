from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app import multi_strategy_walk_forward as legacy
from app.multi_strategy import build_run_request
from app.risk_engine import run_backtest_with_risk


VALIDATION_PROFILE = "nested_walk_forward_v4"
INNER_SELECTION_POLICY = "safety_data_sufficiency_ranked_v1"
INNER_SELECTION_REQUIRED_GATES = (
    "trade_count",
    "max_drawdown",
    "kill_switch_safety",
    "statistical_observation_count",
)
_EXPECTED_REJECTION_PREFIXES = (
    ("selected strategy statistical validation did not pass", "statistical_validation"),
    ("selected strategy statistical gates did not all pass", "statistical_validation"),
    ("selected strategy robustness validation did not pass", "robustness_validation"),
    ("sealed final holdout blocked promotion", "sealed_final_holdout"),
)


def _inner_selection_gates(item: Any) -> dict[str, bool]:
    gates = getattr(item, "gates", {}) or {}
    return {
        gate_name: gates.get(gate_name) is True
        for gate_name in INNER_SELECTION_REQUIRED_GATES
    }


def _select_inner_training_candidate(train_selection: Any) -> tuple[Any | None, dict[str, bool]]:
    """Select the highest-ranked candidate that is safe and sufficiently observed.

    Promotion-grade statistical significance remains non-authoritative inside each
    short training slice. Those gates are still evaluated and retained in the
    candidate evidence, then enforced later on the full research period by the
    existing promotion runner before robustness and the sealed final holdout.
    """

    ranked: Iterable[Any] = getattr(train_selection, "ranked_results", ()) or ()
    for item in ranked:
        safety_gates = _inner_selection_gates(item)
        if safety_gates and all(safety_gates.values()):
            return item, safety_gates
    return None, {}


def run_nested_walk_forward_stability_v4(
    request: legacy.WalkForwardMultiStrategyRequest,
) -> legacy.WalkForwardStabilityResult:
    """Leakage-safe inner selection followed by untouched future OOS evaluation."""

    symbol = request.symbols[0].upper()
    candidates = legacy._candidate_by_strategy_id(request)
    windows: list[legacy.WalkForwardWindowResult] = []

    for window_number, (train_slice, test_slice) in enumerate(
        legacy._window_slices(request),
        start=1,
    ):
        train_request = request.model_copy(
            deep=True,
            update={
                "bars": {symbol: train_slice},
                "force_close_at_end": True,
            },
        )
        train_selection = legacy.run_multi_strategy_backtest(train_request)
        selected_item, safety_gates = _select_inner_training_candidate(train_selection)

        if selected_item is None:
            windows.append(
                legacy.WalkForwardWindowResult(
                    window=window_number,
                    train_start=train_slice[0].timestamp.isoformat(),
                    train_end=train_slice[-1].timestamp.isoformat(),
                    test_start=test_slice[0].timestamp.isoformat(),
                    test_end=test_slice[-1].timestamp.isoformat(),
                    train_bars=len(train_slice),
                    test_bars=len(test_slice),
                    decision="NO_TRADE",
                    selected_strategy_id=None,
                    selected_strategy_name=None,
                    train_selection_eligible=False,
                    train_selection_score=None,
                    train_metrics=None,
                    capital_deployed=False,
                    profitable=False,
                    metrics=legacy._cash_hold_metrics(request.initial_equity),
                    warnings=[
                        "No training candidate passed the v4 inner safety/data-"
                        "sufficiency policy; cash was held through the untouched "
                        "future test window."
                    ],
                )
            )
            continue

        candidate = candidates[selected_item.strategy_id]
        test_request = build_run_request(candidate, request).model_copy(
            deep=True,
            update={
                "bars": {symbol: test_slice},
                "force_close_at_end": True,
            },
        )
        test_result = run_backtest_with_risk(test_request)
        profitable = (
            test_result.metrics.trade_count
            >= request.walk_forward_criteria.min_window_trades
            and test_result.metrics.return_pct > 0
        )
        strict_train_failures = sorted(
            name
            for name, passed in (getattr(selected_item, "gates", {}) or {}).items()
            if not passed
        )
        policy_warning = (
            "Nested v4 selected this candidate using inner safety/data-sufficiency "
            "gates only; promotion-grade train-slice gates remain diagnostic and "
            "are enforced later on full research evidence."
        )
        warnings = list(getattr(selected_item, "warnings", []) or [])
        warnings.extend(test_result.warnings)
        warnings.append(policy_warning)
        if strict_train_failures:
            warnings.append(
                "Non-authoritative train-slice gates not passed: "
                + ", ".join(strict_train_failures)
            )
        warnings.append(
            "Inner safety gates: "
            + ", ".join(
                f"{name}={'pass' if passed else 'fail'}"
                for name, passed in safety_gates.items()
            )
        )

        windows.append(
            legacy.WalkForwardWindowResult(
                window=window_number,
                train_start=train_slice[0].timestamp.isoformat(),
                train_end=train_slice[-1].timestamp.isoformat(),
                test_start=test_slice[0].timestamp.isoformat(),
                test_end=test_slice[-1].timestamp.isoformat(),
                train_bars=len(train_slice),
                test_bars=len(test_slice),
                decision="TRADE",
                selected_strategy_id=selected_item.strategy_id,
                selected_strategy_name=selected_item.name,
                train_selection_eligible=True,
                train_selection_score=selected_item.score,
                train_metrics=selected_item.metrics,
                capital_deployed=True,
                profitable=profitable,
                metrics=test_result.metrics,
                warnings=list(dict.fromkeys(warnings)),
            )
        )

    return legacy._summarize_windows(
        request=request,
        windows=windows,
        selection_method="nested_train_select_test_evaluate",
    )


def run_walk_forward_multi_strategy_backtest_v4(
    request: legacy.WalkForwardMultiStrategyRequest,
) -> legacy.WalkForwardMultiStrategyResult:
    """Preserve v3 outer/promotion semantics while replacing only inner admission."""

    base_result = legacy.run_multi_strategy_backtest(request)
    candidates = legacy._candidate_by_strategy_id(request)
    nested = run_nested_walk_forward_stability_v4(request)
    selected_strategy_id = (
        nested.latest_selected_strategy_id
        if nested.passed and nested.latest_selection_eligible
        else None
    )

    items = [
        legacy._walk_forward_item(
            base_item=base_item,
            stability=legacy.run_candidate_walk_forward_stability(
                request=request,
                candidate=candidates[base_item.strategy_id],
            ),
            promotion_eligible=(base_item.strategy_id == selected_strategy_id),
            nested=nested,
        )
        for base_item in base_result.ranked_results
    ]
    items.sort(
        key=lambda item: (
            -int(item.eligible),
            -item.score,
            -item.walk_forward.stability_score,
            -item.metrics.return_pct,
            item.strategy_id,
        )
    )
    ranked = [
        item.model_copy(update={"rank": rank})
        for rank, item in enumerate(items, start=1)
    ]
    eligible = [item for item in ranked if item.eligible]
    best_overall = ranked[0] if ranked else None
    best_eligible = eligible[0] if eligible else None
    selected_result = None

    if best_eligible is not None:
        selected_candidate = candidates[best_eligible.strategy_id]
        latest_train = legacy._latest_training_slice(request)
        symbol = request.symbols[0].upper()
        if latest_train:
            selected_result = run_backtest_with_risk(
                build_run_request(selected_candidate, request).model_copy(
                    deep=True,
                    update={
                        "bars": {symbol: latest_train},
                        "force_close_at_end": True,
                    },
                )
            )

    warnings = list(base_result.warnings)
    warnings.append(
        f"Validation profile {VALIDATION_PROFILE} uses inner policy "
        f"{INNER_SELECTION_POLICY}; promotion remains controlled by untouched "
        "outer OOS gates, full statistical validation, robustness, and the "
        "sealed final holdout."
    )
    warnings.append(
        "Full-period performance gates remain diagnostic for nested promotion; "
        "they do not replace outer OOS or full-research statistical authority."
    )
    if nested.no_trade_windows:
        warnings.append(
            "Nested windows with no v4 inner-safe candidate were true NO_TRADE "
            "abstentions with cash held and no strategy exposure."
        )
    if best_eligible is None:
        warnings.append(
            "No strategy passed the unchanged nested outer OOS gates and latest "
            "v4 inner-selection check; do not promote this symbol."
        )

    return legacy.WalkForwardMultiStrategyResult(
        symbol=base_result.symbol,
        candidate_source=base_result.candidate_source,
        selection_status=(
            "eligible_strategy_found"
            if best_eligible is not None
            else "no_eligible_strategy"
        ),
        selection_criteria=base_result.selection_criteria,
        walk_forward_criteria=request.walk_forward_criteria,
        nested_walk_forward=nested,
        evaluated_count=len(ranked),
        eligible_count=len(eligible),
        ranked_results=ranked,
        best_overall=best_overall,
        best_eligible=best_eligible,
        selected_result=selected_result,
        warnings=list(dict.fromkeys(warnings)),
    )


def _dump_evidence(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else None
    return dict(value) if isinstance(value, dict) else None


def _result_symbol(value: Any) -> str | None:
    symbols = getattr(value, "symbols", None)
    if isinstance(symbols, (list, tuple)) and symbols:
        symbol = str(symbols[0]).strip().upper()
        return symbol or None
    return None


def _rejection_stage(error: str) -> str | None:
    normalized = str(error or "").strip().lower()
    for prefix, stage in _EXPECTED_REJECTION_PREFIXES:
        if normalized.startswith(prefix):
            return stage
    return None


def _refresh_hourly_summary(output: dict[str, Any]) -> None:
    data = output.get("data")
    if not isinstance(data, dict):
        return
    items = data.get("items")
    if not isinstance(items, list):
        return

    eligible = [
        item.get("symbol")
        for item in items
        if isinstance(item, dict) and item.get("status") == "eligible_strategy_found"
    ]
    ineligible = [
        item.get("symbol")
        for item in items
        if isinstance(item, dict) and item.get("status") == "no_eligible_strategy"
    ]
    failed = [
        item.get("symbol")
        for item in items
        if isinstance(item, dict) and item.get("status") == "failed"
    ]
    published_count = sum(
        1 for item in items if isinstance(item, dict) and item.get("published") is True
    )
    promoted_count = sum(
        1 for item in items if isinstance(item, dict) and item.get("promoted") is True
    )
    publish_required = data.get("promotion_lifecycle_required") is True
    all_succeeded = not failed
    all_eligible_published = published_count == len(eligible)
    all_eligible_promoted = promoted_count == len(eligible) if publish_required else True
    publication_complete = (
        all_succeeded and all_eligible_published and all_eligible_promoted
    )

    data.update(
        {
            "eligible_symbols": eligible,
            "ineligible_symbols": ineligible,
            "failed_symbols": failed,
            "eligible_count": len(eligible),
            "ineligible_count": len(ineligible),
            "published_count": published_count,
            "promoted_count": promoted_count,
            "published": publication_complete,
            "publish_status": (
                "success"
                if publication_complete
                else "partial_failure"
                if eligible or ineligible
                else "failed"
            ),
            "all_succeeded": all_succeeded,
            "selection_complete": all_succeeded,
        }
    )
    output["status"] = "success" if all_succeeded else "error"
    output["error"] = (
        None
        if all_succeeded
        else "One or more nested walk-forward Backtests failed operationally."
    )


def _reclassify_expected_gate_rejections(
    output: dict[str, Any],
    *,
    statistical_by_symbol: dict[str, dict[str, Any]],
    robustness_by_symbol: dict[str, dict[str, Any]],
    holdout_by_symbol: dict[str, dict[str, Any]],
) -> bool:
    data = output.get("data")
    if not isinstance(data, dict):
        return False
    items = data.get("items")
    if not isinstance(items, list):
        return False

    changed = False
    evidence_by_stage = {
        "statistical_validation": statistical_by_symbol,
        "robustness_validation": robustness_by_symbol,
        "sealed_final_holdout": holdout_by_symbol,
    }
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "failed":
            continue
        if item.get("published") is True or item.get("promoted") is True:
            continue
        reason = str(item.get("error") or "")
        stage = _rejection_stage(reason)
        if stage is None:
            continue
        symbol = str(item.get("symbol") or "").upper()
        evidence = evidence_by_stage[stage].get(symbol)
        item.update(
            {
                "status": "no_eligible_strategy",
                "published": False,
                "promoted": False,
                "publish_status": "skipped",
                "rejection_stage": stage,
                "rejection_reason": reason,
                "rejection_evidence": evidence,
                "error": None,
            }
        )
        if stage == "sealed_final_holdout":
            item["sealed_holdout"] = {
                **(evidence or {"enabled": True, "passed": False}),
                "status": "opened_rejected",
            }
        else:
            item["sealed_holdout"] = {
                "enabled": True,
                "status": "sealed_not_opened",
            }
        changed = True

    if changed:
        _refresh_hourly_summary(output)
    return changed


def _rewrite_hourly_reports(report_path: Path, output: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(output, indent=2, sort_keys=True), encoding="utf-8"
    )
    data = output.get("data") or {}
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "unknown").lower()
        safe_symbol = re.sub(r"[^a-z0-9]+", "-", symbol).strip("-") or "unknown"
        item_path = report_path.parent / f"hourly-backtest-{safe_symbol}.json"
        item_path.write_text(
            json.dumps(item, indent=2, sort_keys=True), encoding="utf-8"
        )


def apply_nested_validation_v4(runner_module: Any) -> dict[str, Any]:
    """Install v4 only into the production nested runner adapter.

    The legacy v3 evaluator remains importable for regression and historical
    evidence. The hourly runner receives a distinct validation profile, so run IDs
    and promotion records cannot collide with v3 evidence.
    """

    previous_profile = getattr(runner_module, "VALIDATION_PROFILE", None)
    if previous_profile not in {"nested_walk_forward_v3", VALIDATION_PROFILE}:
        raise RuntimeError(
            "Unsupported base nested validation profile for v4 adapter: "
            f"{previous_profile!r}"
        )
    runner_module.VALIDATION_PROFILE = VALIDATION_PROFILE
    runner_module.run_walk_forward_multi_strategy_backtest = (
        run_walk_forward_multi_strategy_backtest_v4
    )
    runner_module.INNER_SELECTION_POLICY = INNER_SELECTION_POLICY
    runner_module.INNER_SELECTION_REQUIRED_GATES = INNER_SELECTION_REQUIRED_GATES

    if not getattr(runner_module, "_V4_REJECTION_CLASSIFIER_INSTALLED", False):
        statistical_by_symbol: dict[str, dict[str, Any]] = {}
        robustness_by_symbol: dict[str, dict[str, Any]] = {}
        holdout_by_symbol: dict[str, dict[str, Any]] = {}
        original_statistical = runner_module.run_statistical_validation
        original_robustness = runner_module.run_promotion_robustness
        original_holdout = runner_module.evaluate_sealed_final_holdout
        original_hourly = runner_module.run_nested_hourly_backtest

        def capture_statistical(result: Any, *args: Any, **kwargs: Any):
            evidence = original_statistical(result, *args, **kwargs)
            symbol = _result_symbol(result)
            dumped = _dump_evidence(evidence)
            if symbol and dumped is not None:
                statistical_by_symbol[symbol] = dumped
            return evidence

        def capture_robustness(request: Any, *args: Any, **kwargs: Any):
            evidence = original_robustness(request, *args, **kwargs)
            symbol = _result_symbol(request)
            dumped = _dump_evidence(evidence)
            if symbol and dumped is not None:
                robustness_by_symbol[symbol] = dumped
            return evidence

        def capture_holdout(*args: Any, **kwargs: Any):
            evidence = original_holdout(*args, **kwargs)
            result = kwargs.get("result")
            if result is None and args:
                result = args[0]
            symbol = _result_symbol(result)
            dumped = _dump_evidence(evidence)
            if symbol and dumped is not None:
                holdout_by_symbol[symbol] = dumped
            return evidence

        def run_hourly_v4(report_path: Path) -> dict[str, Any]:
            statistical_by_symbol.clear()
            robustness_by_symbol.clear()
            holdout_by_symbol.clear()
            output = original_hourly(report_path)
            changed = _reclassify_expected_gate_rejections(
                output,
                statistical_by_symbol=statistical_by_symbol,
                robustness_by_symbol=robustness_by_symbol,
                holdout_by_symbol=holdout_by_symbol,
            )
            if changed:
                _rewrite_hourly_reports(report_path, output)
            return output

        runner_module.run_statistical_validation = capture_statistical
        runner_module.run_promotion_robustness = capture_robustness
        runner_module.evaluate_sealed_final_holdout = capture_holdout
        runner_module.run_nested_hourly_backtest = run_hourly_v4
        runner_module._V4_REJECTION_CLASSIFIER_INSTALLED = True

    return {
        "validation_profile": VALIDATION_PROFILE,
        "inner_selection_policy": INNER_SELECTION_POLICY,
        "required_inner_gates": list(INNER_SELECTION_REQUIRED_GATES),
        "outer_oos_gates_changed": False,
        "full_statistical_authority_changed": False,
        "robustness_authority_changed": False,
        "sealed_holdout_authority_changed": False,
        "expected_gate_rejections_are_operational_failures": False,
    }
