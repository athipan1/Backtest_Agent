from app.research_overfit import PBOCriteria, run_cscv_pbo


def test_pbo_passes_when_same_candidate_generalizes_across_all_slices():
    result = run_cscv_pbo(
        {
            "robust": [0.01] * 80,
            "weak": [0.0] * 80,
        },
        criteria=PBOCriteria(slice_count=8, min_observations_per_slice=10),
    )

    assert result.status == "completed"
    assert result.probability_of_backtest_overfit == 0.0
    assert result.passed is True
    assert result.combination_count == 35


def test_pbo_rejects_candidate_that_reverses_out_of_sample():
    result = run_cscv_pbo(
        {
            "first_half": [0.02] * 40 + [-0.02] * 40,
            "second_half": [-0.02] * 40 + [0.02] * 40,
        },
        criteria=PBOCriteria(
            slice_count=8,
            min_observations_per_slice=10,
            max_probability_of_backtest_overfit=0.20,
        ),
    )

    assert result.status == "completed"
    assert result.probability_of_backtest_overfit is not None
    assert result.probability_of_backtest_overfit > 0.20
    assert result.passed is False


def test_pbo_fails_closed_when_research_history_is_too_short():
    result = run_cscv_pbo(
        {"a": [0.01] * 20, "b": [0.0] * 20},
        criteria=PBOCriteria(slice_count=8, min_observations_per_slice=10),
    )

    assert result.status == "insufficient_data"
    assert result.passed is False
    assert result.combination_count == 0
