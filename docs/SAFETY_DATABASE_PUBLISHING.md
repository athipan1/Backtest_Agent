# Safety Note: Database Publishing

The database publishing flow is intentionally storage-only.

Allowed:

- Run historical simulation
- Build normalized backtest result payloads
- Send completed backtest results to `Database_Agent`

Not allowed in this flow:

- Submit broker orders
- Cancel broker orders
- Replace broker orders
- Approve risk decisions
- Bypass Manager, Risk, or Execution agents

`Manager_Agent` and `Curator_Agent` may later read the stored backtest status as an advisory or gate signal, but this PR does not enforce live or paper execution decisions.
