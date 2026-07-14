from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.database_client import DatabaseAgentClient
from app.models import BacktestRunRequest, BacktestRunResult, SimulatedTrade


ENGINE_VERSION = "backtest-agent-0.3.0"


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _bars_for_symbol(request: BacktestRunRequest, symbol: str) -> list:
    for key, bars in request.bars.items():
        if key.upper() == symbol.upper():
            return sorted(bars, key=lambda bar: bar.timestamp)
    return []


def _time_bounds(request: BacktestRunRequest, symbol: str) -> tuple[str, str]:
    bars = _bars_for_symbol(request, symbol)
    if bars:
        return _iso(bars[0].timestamp), _iso(bars[-1].timestamp)
    now = _iso(datetime.now(timezone.utc))
    return now, now


def _outcome(realized_pl: float) -> str:
    if realized_pl > 0:
        return "win"
    if realized_pl < 0:
        return "loss"
    return "breakeven"


def _trade_pairs(trades: List[SimulatedTrade]) -> List[Dict[str, Any]]:
    """Convert the event-like simulation trades into Database_Agent trade rows.

    The engine records buy/sell events. Database_Agent's backtest foundation is
    happier with closed trade rows, so we pair each sell with the latest open buy
    for the same symbol. Unpaired entries are ignored because they are not closed
    outcomes yet.
    """

    open_entries: Dict[str, SimulatedTrade] = {}
    rows: List[Dict[str, Any]] = []
    for trade in trades:
        symbol = trade.symbol.upper()
        if trade.side == "buy":
            open_entries[symbol] = trade
            continue
        if trade.side != "sell" or symbol not in open_entries:
            continue
        entry = open_entries.pop(symbol)
        rows.append(
            {
                "symbol": symbol,
                "side": entry.side,
                "quantity": entry.quantity,
                "entry_price": entry.price,
                "exit_price": trade.price,
                "realized_pl": trade.realized_pnl,
                "fees": round(entry.fees + trade.fees, 2),
                "outcome": _outcome(trade.realized_pnl),
                "entry_time": _iso(entry.timestamp),
                "exit_time": _iso(trade.timestamp),
                "metadata": {
                    "entry_reason": entry.reason,
                    "exit_reason": trade.reason,
                    "entry_fees": entry.fees,
                    "exit_fees": trade.fees,
                },
            }
        )
    return rows


def _equity_curve_rows(result: BacktestRunResult) -> List[Dict[str, Any]]:
    peak = None
    rows: List[Dict[str, Any]] = []
    for point in result.equity_curve:
        peak = point.equity if peak is None else max(peak, point.equity)
        drawdown = 0.0 if not peak else round((point.equity - peak) / peak, 6)
        rows.append(
            {
                "timestamp": _iso(point.timestamp),
                "equity": point.equity,
                "drawdown": drawdown,
            }
        )
    return rows


def build_database_backtest_payload(
    *,
    request: BacktestRunRequest,
    result: BacktestRunResult,
    account_id: str,
    run_id: Optional[str] = None,
    skill_id: Optional[str] = None,
    strategy_id: Optional[str] = None,
    timeframe: str = "1d",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    primary_symbol = result.symbols[0].upper() if result.symbols else request.symbols[0].upper()
    start_time, end_time = _time_bounds(request, primary_symbol)
    metrics = result.metrics

    return {
        "run_id": run_id or f"backtest-{uuid4().hex}",
        "account_id": str(account_id),
        "skill_id": skill_id,
        "strategy_id": strategy_id or result.strategy,
        "symbol": primary_symbol,
        "timeframe": timeframe,
        "start_time": start_time,
        "end_time": end_time,
        "status": "completed",
        "engine_version": ENGINE_VERSION,
        "parameters": {
            "strategy": result.strategy,
            "fast_window": request.fast_window,
            "slow_window": request.slow_window,
            "risk_per_trade": request.risk_per_trade,
            "max_position_pct": request.max_position_pct,
            "stop_loss_pct": request.stop_loss_pct,
            "reward_risk_ratio": request.reward_risk_ratio,
            "fee_bps": request.fee_bps,
            "slippage_bps": request.slippage_bps,
            "use_risk_agent": request.use_risk_agent,
            "max_trades_per_day": request.max_trades_per_day,
            "force_close_at_end": request.force_close_at_end,
        },
        "metrics": {
            "initial_equity": metrics.initial_equity,
            "final_equity": metrics.final_equity,
            "net_profit": metrics.net_profit,
            "return_pct": metrics.return_pct,
            "win_rate": metrics.win_rate,
            "profit_factor": metrics.profit_factor,
            "expectancy": metrics.expectancy,
            "max_drawdown": metrics.max_drawdown,
            "realized_net_profit": metrics.realized_net_profit,
            "unrealized_pnl": metrics.unrealized_pnl,
            "open_position_count": metrics.open_position_count,
            "total_trades": metrics.trade_count,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "risk_rejections": metrics.risk_rejections,
            "kill_switch_events": metrics.kill_switch_events,
        },
        "trades": _trade_pairs(result.trades),
        "equity_curve": _equity_curve_rows(result),
        "metadata": {
            "source_agent": "backtest-agent",
            "symbols": result.symbols,
            "strategy": result.strategy,
            "execution_model": result.execution_model,
            "position_sizing_model": result.position_sizing_model,
            "force_close_at_end": request.force_close_at_end,
            "warnings": result.warnings,
            **(metadata or {}),
        },
    }


def publish_backtest_result(
    *,
    request: BacktestRunRequest,
    result: BacktestRunResult,
    account_id: str,
    run_id: Optional[str] = None,
    skill_id: Optional[str] = None,
    strategy_id: Optional[str] = None,
    timeframe: str = "1d",
    metadata: Optional[Dict[str, Any]] = None,
    database_client: Optional[DatabaseAgentClient] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = build_database_backtest_payload(
        request=request,
        result=result,
        account_id=account_id,
        run_id=run_id,
        skill_id=skill_id,
        strategy_id=strategy_id,
        timeframe=timeframe,
        metadata=metadata,
    )
    client = database_client or DatabaseAgentClient()
    response = client.publish_backtest_run(payload, correlation_id=correlation_id)
    return {
        "status": response.get("status", "success") if isinstance(response, dict) else "success",
        "database_response": response,
        "payload": payload,
    }
