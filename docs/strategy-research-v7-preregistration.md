# Strategy Research v7 preregistration

Status: preregistered research hypothesis. Parameters below are frozen before any v7 OOS result is observed.

## Motivation

Phase 2 failure attribution identified cross-window consistency, median Sharpe, and median profit factor as dominant failure modes. Existing cross-symbol regime descriptors were not strong enough to justify a fitted regime threshold. V7 therefore tests a sparse hypothesis set rather than adding a regime gate or dense parameter optimization.

## Frozen candidate set

Controls remain unchanged:
- sma-crossover-balanced-v1
- trend-following-balanced-v1
- mean-reversion-balanced-v1
- breakout-balanced-v1

New hypotheses:
- sma-crossover-15-45-risk-v7: 15/45, max position 5%, stop 3.5%, reward/risk 2.5
- sma-crossover-20-60-risk-v7: 20/60, max position 5%, stop 4.0%, reward/risk 2.8
- mean-reversion-5-30-risk-v7: 5/30, max position 4%, stop 2.5%, reward/risk 2.0
- mean-reversion-8-35-risk-v7: 8/35, max position 4%, stop 3.0%, reward/risk 2.2

## Validation contract

V7 inherits the v6 fail-closed research stack: sealed final holdout reservation, nested walk-forward selection, cumulative multiple-testing accounting, CSCV/PBO, statistical validation, robustness validation, and conservative transaction-cost stress. The cumulative trial count is 18 unique strategy identities.

No v7 result may change these preregistered parameters. No threshold is reduced. Cross-symbol regime evidence remains diagnostic only and is not a selection gate.

## Authority boundaries

- research only
- database publication disabled
- promotion disabled
- execution disabled
- sealed holdout must remain unopened during pre-holdout research
- no Alpaca order authority

A failed v7 run is evidence against these hypotheses, not permission to tune them against the same OOS sample.
