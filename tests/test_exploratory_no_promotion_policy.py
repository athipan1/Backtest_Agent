from types import SimpleNamespace

from app.exploratory_no_promotion_policy import (
    BLOCK_REASON,
    apply_exploratory_no_promotion_policy,
)


class Copyable(SimpleNamespace):
    def model_copy(self, *, update):
        values = dict(self.__dict__)
        values.update(update)
        return Copyable(**values)


def test_exploratory_strategy_is_forced_observation_only_even_if_upstream_eligible():
    upstream_item = Copyable(
        eligible=True,
        gates={"oos": True},
        disqualification_reasons=[],
    )
    upstream_result = Copyable(
        selection_status="eligible_strategy_found",
        eligible_count=1,
        ranked_results=[upstream_item],
        best_overall=upstream_item,
        best_eligible=upstream_item,
        selected_result={"would_promote": True},
        warnings=[],
    )
    runner = SimpleNamespace(
        STRATEGY_BUCKET_CANDIDATE_POLICY={
            "symbol_buckets": {"NVDA": "exploratory"}
        },
        run_walk_forward_multi_strategy_backtest=lambda request: upstream_result,
    )

    policy = apply_exploratory_no_promotion_policy(runner)
    result = runner.run_walk_forward_multi_strategy_backtest(
        SimpleNamespace(symbols=["NVDA"])
    )

    assert policy["production_promotion_authorized"] is False
    assert policy["broker_order_authorized"] is False
    assert result.selection_status == "no_eligible_strategy"
    assert result.eligible_count == 0
    assert result.best_eligible is None
    assert result.selected_result is None
    assert result.ranked_results[0].eligible is False
    assert result.ranked_results[0].gates["production_classification"] is False
    assert BLOCK_REASON in result.ranked_results[0].disqualification_reasons
    assert BLOCK_REASON in result.warnings


def test_normal_bucket_preserves_upstream_selection():
    upstream_result = Copyable(
        selection_status="eligible_strategy_found",
        eligible_count=1,
        ranked_results=[],
        best_overall=None,
        best_eligible={"ok": True},
        selected_result={"ok": True},
        warnings=[],
    )
    runner = SimpleNamespace(
        STRATEGY_BUCKET_CANDIDATE_POLICY={
            "symbol_buckets": {"TCOM": "value_rebound"}
        },
        run_walk_forward_multi_strategy_backtest=lambda request: upstream_result,
    )
    apply_exploratory_no_promotion_policy(runner)

    result = runner.run_walk_forward_multi_strategy_backtest(
        SimpleNamespace(symbols=["TCOM"])
    )
    assert result is upstream_result
    assert result.selection_status == "eligible_strategy_found"
