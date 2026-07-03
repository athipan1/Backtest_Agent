from __future__ import annotations

from typing import Dict, List

from app.engine import (
    Position,
    _bars_for_symbol,
    _buy_price,
    _exit_position,
    _intrabar_exit_price,
    _portfolio_value,
    _stop_loss_price,
    _take_profit_price,
    _trade_metrics,
)
from app.models import BacktestRunRequest, BacktestRunResult, EquityPoint, RiskCheckPayload, RiskRejection, SimulatedTrade
from app.risk_adapter import LocalRiskAdapter
from app.strategies import strategy_signal


def _portfolio_value(cash: float, positions: Dict[str, Position], prices: Dict[str, float]) -> float:
    return cash + sum(position.quantity * prices.get(symbol, position.average_price) for symbol, position in positions.items())


def run_backtest_with_risk(request: BacktestRunRequest) -> BacktestRunResult:
    cash = float(request.initial_equity)
    positions: Dict[str, Position] = {symbol.upper(): Position() for symbol in request.symbols}
    closes: Dict[str, List[float]] = {symbol.upper(): [] for symbol in request.symbols}
    history = {symbol.upper(): [] for symbol in request.symbols}
    trades: List[SimulatedTrade] = []
    equity_curve: List[EquityPoint] = []
    risk_rejections: List[RiskRejection] = []
    warnings: List[str] = []
    risk_adapter = LocalRiskAdapter()

    timeline = []
    for symbol in [item.upper() for item in request.symbols]:
        symbol_bars = _bars_for_symbol(request, symbol)
        if len(symbol_bars) < request.slow_window:
            warnings.append(f"{symbol} has fewer bars than slow_window")
        for bar in symbol_bars:
            timeline.append((bar.timestamp, symbol, bar))
    timeline.sort(key=lambda item: item[0])

    last_prices: Dict[str, float] = {}
    entries_by_day: Dict[str, int] = {}
    for _, symbol, bar in timeline:
        last_prices[symbol] = bar.close
        closes[symbol].append(bar.close)
        history[symbol].append(bar)
        signal = strategy_signal(request.strategy, closes[symbol], history[symbol], request.fast_window, request.slow_window)
        position = positions[symbol]
        day_key = bar.timestamp.date().isoformat()

        exit_price, exit_reason = _intrabar_exit_price(position, bar)
        if exit_price is not None and exit_reason is not None:
            cash = _exit_position(
                symbol=symbol,
                position=position,
                cash=cash,
                exit_price=exit_price,
                timestamp=bar.timestamp,
                reason=exit_reason,
                fee_bps=request.fee_bps,
                trades=trades,
            )

        if signal == "buy" and position.quantity <= 0:
            entry_price = _buy_price(bar.close, request.slippage_bps)
            stop_loss = _stop_loss_price(entry_price, request)
            quantity = int((request.initial_equity * request.max_position_pct) / entry_price)
            decision = risk_adapter.evaluate(
                RiskCheckPayload(
                    symbol=symbol,
                    side="buy",
                    entry_price=entry_price,
                    protection_price=stop_loss,
                    equity=request.initial_equity,
                    requested_quantity=quantity,
                    current_symbol_exposure=0.0,
                    current_total_exposure=_portfolio_value(0.0, positions, last_prices),
                    trades_today=entries_by_day.get(day_key, 0),
                    emergency_halt=request.emergency_halt,
                ),
                max_position_pct=request.max_position_pct,
                max_trades_per_day=request.max_trades_per_day,
            ) if request.use_risk_agent else None

            if decision is not None and not decision.approved:
                risk_rejections.append(
                    RiskRejection(
                        symbol=symbol,
                        timestamp=bar.timestamp,
                        side="buy",
                        requested_quantity=quantity,
                        violations=decision.violations,
                        kill_switch_active=decision.kill_switch_active,
                        source=decision.source,
                    )
                )
            else:
                if decision is not None:
                    quantity = int(decision.final_quantity)
                cost = entry_price * quantity
                fees = _fee(cost, request.fee_bps)
                if quantity > 0 and cash >= cost + fees:
                    cash -= cost + fees
                    entries_by_day[day_key] = entries_by_day.get(day_key, 0) + 1
                    position.quantity = float(quantity)
                    position.average_price = entry_price
                    position.stop_loss = stop_loss
                    position.take_profit = _take_profit_price(entry_price, stop_loss, request)
                    trades.append(SimulatedTrade(symbol=symbol, side="buy", quantity=quantity, price=round(entry_price, 4), fees=round(fees, 2), timestamp=bar.timestamp, reason=request.strategy))

        if signal == "sell" and position.quantity > 0:
            exit_price = _sell_price(bar.close, request.slippage_bps)
            cash = _exit_position(
                symbol=symbol,
                position=position,
                cash=cash,
                exit_price=exit_price,
                timestamp=bar.timestamp,
                reason=request.strategy,
                fee_bps=request.fee_bps,
                trades=trades,
            )

        equity_curve.append(EquityPoint(timestamp=bar.timestamp, equity=round(_portfolio_value(cash, positions, last_prices), 2)))

    final_equity = equity_curve[-1].equity if equity_curve else cash
    metrics = _trade_metrics(request.initial_equity, final_equity, trades, equity_curve)
    metrics.risk_rejections = len(risk_rejections)
    metrics.kill_switch_events = sum(1 for item in risk_rejections if item.kill_switch_active)
    return BacktestRunResult(
        strategy=request.strategy,
        symbols=[symbol.upper() for symbol in request.symbols],
        metrics=metrics,
        trades=trades,
        equity_curve=equity_curve,
        risk_rejections=risk_rejections,
        warnings=warnings,
    )
