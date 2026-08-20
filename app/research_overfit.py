from __future__ import annotations

import itertools
import math
from statistics import mean, median
from typing import Literal

from pydantic import BaseModel, Field, model_validator


PBO_SCHEMA_VERSION = "research-pbo.v1"


class PBOCriteria(BaseModel):
    enabled: bool = True
    slice_count: int = Field(default=8, ge=4, le=16)
    min_observations_per_slice: int = Field(default=10, ge=2, le=5000)
    max_probability_of_backtest_overfit: float = Field(default=0.20, ge=0, le=1)

    @model_validator(mode="after")
    def require_even_slice_count(self) -> "PBOCriteria":
        if self.slice_count % 2 != 0:
            raise ValueError("PBO slice_count must be even for CSCV")
        return self


class PBOResult(BaseModel):
    schema_version: Literal["research-pbo.v1"] = PBO_SCHEMA_VERSION
    status: Literal["completed", "insufficient_data", "disabled"]
    passed: bool
    candidate_count: int
    observation_count: int
    slice_count: int
    combination_count: int
    probability_of_backtest_overfit: float | None = None
    median_oos_percentile: float | None = None
    median_logit: float | None = None
    negative_logit_count: int = 0
    criteria: PBOCriteria
    reasons: list[str] = Field(default_factory=list)
    method: str = "combinatorially_symmetric_cross_validation"


def _finite_returns(values: list[float]) -> list[float]:
    return [float(value) for value in values if math.isfinite(float(value))]


def _partition_indices(observation_count: int, slice_count: int) -> list[list[int]]:
    base = observation_count // slice_count
    remainder = observation_count % slice_count
    slices: list[list[int]] = []
    cursor = 0
    for slice_number in range(slice_count):
        size = base + (1 if slice_number < remainder else 0)
        slices.append(list(range(cursor, cursor + size)))
        cursor += size
    return slices


def _score(values: list[float], indices: list[int]) -> float:
    if not indices:
        return float("-inf")
    return mean(values[index] for index in indices)


def _oos_percentile(selected_score: float, all_scores: list[float]) -> float:
    less = sum(score < selected_score for score in all_scores)
    equal = sum(score == selected_score for score in all_scores)
    # Mid-rank percentile in the open interval (0, 1), which keeps the logit finite
    # after clipping and treats exact ties symmetrically.
    return (less + 0.5 * equal) / len(all_scores)


def run_cscv_pbo(
    candidate_returns: dict[str, list[float]],
    *,
    criteria: PBOCriteria,
) -> PBOResult:
    """Estimate Probability of Backtest Overfitting using deterministic CSCV.

    The input must contain one return series per preregistered candidate over the same
    research period. For every symmetric half-split of contiguous slices, the best
    in-sample candidate is identified and then ranked on the complementary OOS data.
    PBO is the fraction of selected candidates whose OOS logit rank is non-positive.
    """

    candidate_ids = sorted(candidate_returns)
    candidate_count = len(candidate_ids)
    if not criteria.enabled:
        observation_count = min(
            (len(candidate_returns[candidate_id]) for candidate_id in candidate_ids),
            default=0,
        )
        return PBOResult(
            status="disabled",
            passed=True,
            candidate_count=candidate_count,
            observation_count=observation_count,
            slice_count=criteria.slice_count,
            combination_count=0,
            criteria=criteria,
        )

    if candidate_count < 2:
        return PBOResult(
            status="insufficient_data",
            passed=False,
            candidate_count=candidate_count,
            observation_count=0,
            slice_count=criteria.slice_count,
            combination_count=0,
            criteria=criteria,
            reasons=["PBO requires at least two preregistered candidates"],
        )

    normalized = {
        candidate_id: _finite_returns(candidate_returns[candidate_id])
        for candidate_id in candidate_ids
    }
    observation_count = min(len(values) for values in normalized.values())
    required = criteria.slice_count * criteria.min_observations_per_slice
    if observation_count < required:
        return PBOResult(
            status="insufficient_data",
            passed=False,
            candidate_count=candidate_count,
            observation_count=observation_count,
            slice_count=criteria.slice_count,
            combination_count=0,
            criteria=criteria,
            reasons=[
                f"PBO requires at least {required} aligned observations; got {observation_count}"
            ],
        )

    normalized = {
        candidate_id: values[-observation_count:]
        for candidate_id, values in normalized.items()
    }
    slices = _partition_indices(observation_count, criteria.slice_count)
    half = criteria.slice_count // 2
    logits: list[float] = []
    percentiles: list[float] = []

    # A split and its complement encode the same symmetric partition. Keeping only
    # combinations containing slice zero removes that duplicate deterministically.
    for in_sample_slices in itertools.combinations(range(criteria.slice_count), half):
        if 0 not in in_sample_slices:
            continue
        in_sample_set = set(in_sample_slices)
        out_sample_slices = [
            index for index in range(criteria.slice_count) if index not in in_sample_set
        ]
        in_indices = [index for part in in_sample_slices for index in slices[part]]
        out_indices = [index for part in out_sample_slices for index in slices[part]]

        in_scores = {
            candidate_id: _score(normalized[candidate_id], in_indices)
            for candidate_id in candidate_ids
        }
        selected_id = max(candidate_ids, key=lambda value: (in_scores[value], value))
        out_scores = {
            candidate_id: _score(normalized[candidate_id], out_indices)
            for candidate_id in candidate_ids
        }
        percentile = _oos_percentile(out_scores[selected_id], list(out_scores.values()))
        clipped = min(max(percentile, 1e-12), 1.0 - 1e-12)
        logits.append(math.log(clipped / (1.0 - clipped)))
        percentiles.append(percentile)

    if not logits:
        return PBOResult(
            status="insufficient_data",
            passed=False,
            candidate_count=candidate_count,
            observation_count=observation_count,
            slice_count=criteria.slice_count,
            combination_count=0,
            criteria=criteria,
            reasons=["PBO could not construct any symmetric CSCV combinations"],
        )

    negative_logit_count = sum(value <= 0.0 for value in logits)
    pbo = negative_logit_count / len(logits)
    passed = pbo <= criteria.max_probability_of_backtest_overfit
    reasons = [] if passed else [
        "Probability of Backtest Overfitting exceeds the configured research limit"
    ]
    return PBOResult(
        status="completed",
        passed=passed,
        candidate_count=candidate_count,
        observation_count=observation_count,
        slice_count=criteria.slice_count,
        combination_count=len(logits),
        probability_of_backtest_overfit=round(pbo, 8),
        median_oos_percentile=round(median(percentiles), 8),
        median_logit=round(median(logits), 8),
        negative_logit_count=negative_logit_count,
        criteria=criteria,
        reasons=reasons,
    )
