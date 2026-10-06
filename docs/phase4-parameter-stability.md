# Phase 4 parameter stability protocol

Purpose: determine whether Strategy Research v7 evidence forms a local parameter plateau rather than a single lucky optimum.

The analysis is diagnostic-only. It groups preregistered configurations by strategy family and reports each configuration's fast/slow windows, OOS return, Sharpe, profit factor, drawdown, trade count, and eligibility. Family medians are reported as descriptive evidence.

A plateau observation requires at least two evaluated configurations in the family with positive median return, positive median Sharpe, and median profit factor above 1.0. This definition is frozen before Phase 4 evidence is used.

The plateau observation is not a promotion or execution gate and cannot override nested OOS, CSCV/PBO, DSR/statistical validation, cost stress, robustness, Portfolio, or Risk. It does not lower any existing threshold and does not open the sealed holdout.

If a family lacks a plateau, the result is evidence against parameter stability. Do not select the best isolated point and do not retune the definition against the same OOS sample.
