from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.analytics import equal_weight_buy_and_hold_return, portfolio_analytics
from app.models import (
    AllocationRejection,
    BacktestMetrics,
    BacktestRunRequest,
    BacktestRunResult,
    EquityPoint,
    PriceBar,
    RiskCheckPayload,
    RiskRejection,
    SimulatedTrade,
)
from app.strategies import strategy_signal


@dataclass
class Position:
    quantity: float = 0.0
    average_price: float = 0.0
    entry_fees: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None

    def reset(self) -> None:
        self.quantity = 0.0
        self.average_price = 0.0
        self.entry_fees = 0.0
        self.stop_loss = None
        self.take_profit = None


def sma(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def max_drawdown(
    curve: List[EquityPoint],
    initial_equity: float | None = None,
) -> float:
    if not curve:
        return 0.0
    peak = initial_equity if initial_equity is not None else curve[0].equity
    worst = 0.0
    for point in curve:
        peak = max(peak, point.equity)
        if peak > 0:
            worst = min(worst, (point.equity - peak) / peak)
    return round(worst, 6)


def _fee(value: float, fee_bps: float) -> float:
    return value * fee_bps / 10000.0


def _buy_price(close: float, slippage_bps: float) -> float:
    return close * (1.0 + slippage_bps / 10000.0)


def _sell_price(close: float, slippage_bps: float) -> float:
    return close * (1.0 - slippage_bps / 10000.0)


def _stop_loss_price(entry_price: float, request: BacktestRunRequest) -> float:
    return entry_price * (1.0 - request.stop_loss_pct)


def _take_profit_price(entry_price: float, stop_loss: float, request: BacktestRunRequest) -> float:
    risk_per_share = entry_price - stop_loss
    return entry_price + (risk_per_share * request.reward_risk_ratio)


def _position_size(
    *,
    cash: float,
    current_equity: float,
    entry_price: float,
    stop_loss: float,
    risk_per_trade: float,
    max_position_pct: float,
    fee_bps: float,
) -> int:
    """Return a long quantity bounded by risk, allocation, and available cash."""
    if cash <= 0 or current_equity <= 0 or entry_price <= 0:
        return 0
    risk_per_share = entry_price - stop_loss
    if risk_per_share <= 0:
        return 0

    quantity_by_risk = int((current_equity * risk_per_trade) / risk_per_share)
    quantity_by_position_cap = int(
        (current_equity * max_position_pct) / entry_price
    )
    entry_cost_per_share = entry_price * (1.0 + fee_bps / 10000.0)
    quantity_by_cash = int(cash / entry_cost_per_share)
    return max(
        0,
        min(quantity_by_risk, quantity_by_position_cap, quantity_by_cash),
    )


def _exit_position(
    *,
    symbol: str,
    position: Position,
    cash: float,
    exit_price: float,
    timestamp,
    reason: str,
    fee_bps: float,
    trades: List[SimulatedTrade],
) -> float:
    proceeds = exit_price * position.quantity
    fees = _fee(proceeds, fee_bps)
    realized_pnl = (
        (exit_price - position.average_price) * position.quantity
        - position.entry_fees
        - fees
    )
    cash += proceeds - fees
    trades.append(
        SimulatedTrade(
            symbol=symbol,
            side="sell",
            quantity=position.quantity,
            price=round(exit_price, 4),
            fees=round(fees, 2),
            timestamp=timestamp,
            realized_pnl=round(realized_pnl, 2),
            reason=reason,
        )
    )
    position.reset()
    return cash


def _intrabar_exit_price(position: Position, bar: PriceBar) -> tuple[float | None, str | None]:
    """Return exit price/reason if a long position's broker-side exits are hit.

    If stop loss and take profit are both touched in the same candle, assume the
    stop loss fills first. This conservative rule prevents overly optimistic
    backtests when intrabar path is unknown.
    """
    if position.quantity <= 0:
        return None, None

    stop_hit = position.stop_loss is not None and bar.low <= position.stop_loss
    take_profit_hit = position.take_profit is not None and bar.high >= position.take_profit

    if stop_hit:
        # A sell stop becomes a market order. If price gaps through it, the
        # opening price is the first executable reference rather than the more
        # favorable stop price.
        return min(position.stop_loss, bar.open), "stop_loss"
    if take_profit_hit:
        # A take-profit limit may receive price improvement on a favorable gap.
        return max(position.take_profit, bar.open), "take_profit"
    return None, None


def _trade_metrics(
    initial_equity: float,
    final_equity: float,
    trades: List[SimulatedTrade],
    curve: List[EquityPoint],
    *,
    positions: Dict[str, Position] | None = None,
    last_prices: Dict[str, float] | None = None,
    periods_per_year: int = 252,
    annual_risk_free_rate: float = 0.0,
    benchmark_return_pct: float | None = None,
) -> BacktestMetrics:
    realized = [trade.realized_pnl for trade in trades if trade.side == "sell"]
    winners = [pnl for pnl in realized if pnl > 0]
    losers = [pnl for pnl in realized if pnl < 0]
    gross_profit = round(sum(winners), 2)
    gross_loss = round(sum(losers), 2)
    trade_count = len(realized)
    net_profit = round(final_equity - initial_equity, 2)
    open_positions = positions or {}
    marks = last_prices or {}
    unrealized_pnl = round(
        sum(
            (marks.get(symbol, position.average_price) - position.average_price)
            * position.quantity
            - position.entry_fees
            for symbol, position in open_positions.items()
            if position.quantity > 0
        ),
        2,
    )
    realized_net_profit = round(sum(realized), 2)
    if gross_loss == 0:
        profit_factor = None if gross_profit > 0 else 0.0
    else:
        profit_factor = round(gross_profit / abs(gross_loss), 6)
    drawdown = max_drawdown(curve, initial_equity)
    analytics = portfolio_analytics(
        initial_equity=initial_equity,
        final_equity=final_equity,
        curve=curve,
        max_drawdown=drawdown,
        periods_per_year=periods_per_year,
        annual_risk_free_rate=annual_risk_free_rate,
        benchmark_return_pct=benchmark_return_pct,
    )
    return BacktestMetrics(
        initial_equity=round(initial_equity, 2),
        final_equity=round(final_equity, 2),
        net_profit=net_profit,
        return_pct=round(net_profit / initial_equity, 6),
        trade_count=trade_count,
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate=round(0.0 if trade_count == 0 else len(winners) / trade_count, 6),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        expectancy=round(0.0 if trade_count == 0 else sum(realized) / trade_count, 2),
        max_drawdown=drawdown,
        annualized_return=analytics.annualized_return,
        annualized_volatility=analytics.annualized_volatility,
        sharpe_ratio=analytics.sharpe_ratio,
        sortino_ratio=analytics.sortino_ratio,
        calmar_ratio=analytics.calmar_ratio,
        benchmark_return_pct=analytics.benchmark_return_pct,
        excess_return_pct=analytics.excess_return_pct,
        realized_net_profit=realized_net_profit,
        unrealized_pnl=unrealized_pnl,
        open_position_count=sum(1 for position in open_positions.values() if position.quantity > 0),
    )


def _bars_for_symbol(request: BacktestRunRequest, symbol: str) -> List[PriceBar]:
    for key, bars in request.bars.items():
        if key.upper() == symbol.upper():
            return sorted(bars, key=lambda bar: bar.timestamp)
    return []


def _portfolio_value(
    cash: float,
    positions: Dict[str, Position],
    prices: Dict[str, float],
) -> float:
    return cash + sum(
        position.quantity * prices.get(symbol, position.average_price)
        for symbol, position in positions.items()
    )


def _invested_value(
    positions: Dict[str, Position],
    prices: Dict[str, float],
) -> float:
    return sum(
        position.quantity * prices.get(symbol, position.average_price)
        for symbol, position in positions.items()
    )


def _bars_grouped_by_timestamp(
    request: BacktestRunRequest,
) -> List[tuple[Any, Dict[str, PriceBar]]]:
    groups: Dict[Any, Dict[str, PriceBar]] = {}
    for symbol in [item.upper() for item in request.symbols]:
        for bar in _bars_for_symbol(request, symbol):
            groups.setdefault(bar.timestamp, {})[symbol] = bar
    return [(timestamp, groups[timestamp]) for timestamp in sorted(groups)]


def _gap_exit_price(
    position: Position,
    bar: PriceBar,
) -> tuple[float | None, str | None]:
    if position.quantity <= 0:
        return None, None
    if position.stop_loss is not None and bar.open <= position.stop_loss:
        return bar.open, "stop_loss"
    if position.take_profit is not None and bar.open >= position.take_profit:
        return bar.open, "take_profit"
    return None, None


def _allocation_rejection_reason(
    *,
    open_positions: int,
    new_positions: int,
    remaining_exposure: float,
    remaining_cash: float,
    entry_price: float,
    request: BacktestRunRequest,
) -> str:
    if open_positions >= request.max_open_positions:
        return "max_open_positions"
    if new_positions >= request.max_new_positions_per_bar:
        return "max_new_positions_per_bar"
    if remaining_exposure < entry_price:
        return "portfolio_exposure_limit"
    if remaining_cash < entry_price * (1.0 + request.fee_bps / 10000.0):
        return "cash_reserve_limit"
    return "position_size_below_one_share"


def _run_backtest(
    request: BacktestRunRequest,
    *,
    risk_adapter=None,
) -> BacktestRunResult:
    cash = float(request.initial_equity)
    positions: Dict[str, Position] = {symbol.upper(): Position() for symbol in request.symbols}
    closes: Dict[str, List[float]] = {symbol.upper(): [] for symbol in request.symbols}
    history: Dict[str, List[PriceBar]] = {symbol.upper(): [] for symbol in request.symbols}
    trades: List[SimulatedTrade] = []
    equity_curve: List[EquityPoint] = []
    risk_rejections: List[RiskRejection] = []
    allocation_rejections: List[AllocationRejection] = []
    warnings: List[str] = []
    pending_signals: Dict[str, str] = {symbol.upper(): "hold" for symbol in request.symbols}

    bars_by_symbol = {symbol.upper(): _bars_for_symbol(request, symbol) for symbol in request.symbols}
    for symbol, bars in bars_by_symbol.items():
        if len(bars) < request.slow_window:
            warnings.append(f"{symbol} has fewer bars than slow_window")

    last_prices: Dict[str, float] = {}
    last_bars: Dict[str, PriceBar] = {}
    entries_by_day: Dict[str, int] = {}
    for timestamp, bars_at_timestamp in _bars_grouped_by_timestamp(request):
        symbols = sorted(bars_at_timestamp)
        exited_at_open: set[str] = set()

        # Every symbol in the batch sees the same timestamp-level open snapshot.
        for symbol in symbols:
            bar = bars_at_timestamp[symbol]
            last_prices[symbol] = bar.open
            last_bars[symbol] = bar

        # Broker-side protection that gaps through its trigger executes first.
        for symbol in symbols:
            bar = bars_at_timestamp[symbol]
            position = positions[symbol]
            exit_price, exit_reason = _gap_exit_price(position, bar)
            if exit_price is None or exit_reason is None:
                continue
            cash = _exit_position(
                symbol=symbol,
                position=position,
                cash=cash,
                exit_price=_sell_price(exit_price, request.slippage_bps),
                timestamp=timestamp,
                reason=exit_reason,
                fee_bps=request.fee_bps,
                trades=trades,
            )
            exited_at_open.add(symbol)

        # Pending close-generated sell signals also execute at this open.
        for symbol in symbols:
            position = positions[symbol]
            if pending_signals[symbol] != "sell" or position.quantity <= 0:
                continue
            cash = _exit_position(
                symbol=symbol,
                position=position,
                cash=cash,
                exit_price=_sell_price(
                    bars_at_timestamp[symbol].open,
                    request.slippage_bps,
                ),
                timestamp=timestamp,
                reason=request.strategy,
                fee_bps=request.fee_bps,
                trades=trades,
            )
            exited_at_open.add(symbol)

        portfolio_equity = _portfolio_value(cash, positions, last_prices)
        reserve_value = portfolio_equity * request.cash_reserve_pct
        max_exposure_value = portfolio_equity * request.max_total_exposure_pct
        candidates: List[tuple[str, float, float, int]] = []

        for symbol in symbols:
            if (
                pending_signals[symbol] != "buy"
                or positions[symbol].quantity > 0
                or symbol in exited_at_open
            ):
                continue
            entry_price = _buy_price(
                bars_at_timestamp[symbol].open,
                request.slippage_bps,
            )
            stop_loss = _stop_loss_price(entry_price, request)
            requested_quantity = _position_size(
                cash=max(0.0, cash - reserve_value),
                current_equity=portfolio_equity,
                entry_price=entry_price,
                stop_loss=stop_loss,
                risk_per_trade=request.risk_per_trade,
                max_position_pct=request.max_position_pct,
                fee_bps=request.fee_bps,
            )
            candidates.append(
                (symbol, entry_price, stop_loss, requested_quantity)
            )

        # The stable symbol order makes allocation independent of request order.
        candidates.sort(key=lambda item: item[0])
        new_positions = 0
        for symbol, entry_price, stop_loss, requested_quantity in candidates:
            open_positions = sum(
                1 for position in positions.values() if position.quantity > 0
            )
            remaining_exposure = max(
                0.0,
                max_exposure_value - _invested_value(positions, last_prices),
            )
            remaining_cash = max(0.0, cash - reserve_value)
            quantity_by_exposure = int(remaining_exposure / entry_price)
            quantity_by_cash = int(
                remaining_cash
                / (entry_price * (1.0 + request.fee_bps / 10000.0))
            )
            approved_quantity = min(
                requested_quantity,
                quantity_by_exposure,
                quantity_by_cash,
            )

            limit_hit = (
                open_positions >= request.max_open_positions
                or new_positions >= request.max_new_positions_per_bar
            )
            if limit_hit or approved_quantity <= 0:
                allocation_rejections.append(
                    AllocationRejection(
                        symbol=symbol,
                        timestamp=timestamp,
                        requested_quantity=requested_quantity,
                        reason=_allocation_rejection_reason(
                            open_positions=open_positions,
                            new_positions=new_positions,
                            remaining_exposure=remaining_exposure,
                            remaining_cash=remaining_cash,
                            entry_price=entry_price,
                            request=request,
                        ),
                    )
                )
                continue

            day_key = timestamp.date().isoformat()
            if risk_adapter is not None:
                decision = risk_adapter.evaluate(
                    RiskCheckPayload(
                        symbol=symbol,
                        side="buy",
                        entry_price=entry_price,
                        protection_price=stop_loss,
                        equity=portfolio_equity,
                        requested_quantity=approved_quantity,
                        current_symbol_exposure=0.0,
                        current_total_exposure=_invested_value(
                            positions,
                            last_prices,
                        ),
                        trades_today=entries_by_day.get(day_key, 0),
                        emergency_halt=request.emergency_halt,
                    ),
                    max_position_pct=request.max_position_pct,
                    max_trades_per_day=request.max_trades_per_day,
                    risk_per_trade=request.risk_per_trade,
                )
                if not decision.approved:
                    risk_rejections.append(
                        RiskRejection(
                            symbol=symbol,
                            timestamp=timestamp,
                            side="buy",
                            requested_quantity=approved_quantity,
                            violations=decision.violations,
                            kill_switch_active=decision.kill_switch_active,
                            source=decision.source,
                        )
                    )
                    continue
                approved_quantity = int(decision.final_quantity)

            cost = entry_price * approved_quantity
            fees = _fee(cost, request.fee_bps)
            if approved_quantity <= 0 or cash < cost + fees:
                allocation_rejections.append(
                    AllocationRejection(
                        symbol=symbol,
                        timestamp=timestamp,
                        requested_quantity=requested_quantity,
                        reason="insufficient_cash",
                    )
                )
                continue

            cash -= cost + fees
            entries_by_day[day_key] = entries_by_day.get(day_key, 0) + 1
            new_positions += 1
            position = positions[symbol]
            position.quantity = float(approved_quantity)
            position.average_price = entry_price
            position.entry_fees = fees
            position.stop_loss = stop_loss
            position.take_profit = _take_profit_price(
                entry_price,
                stop_loss,
                request,
            )
            trades.append(
                SimulatedTrade(
                    symbol=symbol,
                    side="buy",
                    quantity=approved_quantity,
                    price=round(entry_price, 4),
                    fees=round(fees, 2),
                    timestamp=timestamp,
                    reason=request.strategy,
                )
            )

        # Intrabar protection is evaluated after all open-time allocations.
        for symbol in symbols:
            bar = bars_at_timestamp[symbol]
            position = positions[symbol]
            exit_price, exit_reason = _intrabar_exit_price(position, bar)
            if exit_price is None or exit_reason is None:
                continue
            cash = _exit_position(
                symbol=symbol,
                position=position,
                cash=cash,
                exit_price=_sell_price(exit_price, request.slippage_bps),
                timestamp=timestamp,
                reason=exit_reason,
                fee_bps=request.fee_bps,
                trades=trades,
            )

        for symbol in symbols:
            bar = bars_at_timestamp[symbol]
            closes[symbol].append(bar.close)
            history[symbol].append(bar)
            pending_signals[symbol] = strategy_signal(
                request.strategy,
                closes[symbol],
                history[symbol],
                request.fast_window,
                request.slow_window,
            )
            last_prices[symbol] = bar.close

        equity_curve.append(
            EquityPoint(
                timestamp=timestamp,
                equity=round(_portfolio_value(cash, positions, last_prices), 2),
            )
        )

    if request.force_close_at_end:
        for symbol, position in positions.items():
            if position.quantity <= 0 or symbol not in last_bars:
                continue
            last_bar = last_bars[symbol]
            cash = _exit_position(
                symbol=symbol,
                position=position,
                cash=cash,
                exit_price=_sell_price(last_bar.close, request.slippage_bps),
                timestamp=last_bar.timestamp,
                reason="end_of_data",
                fee_bps=request.fee_bps,
                trades=trades,
            )
        if last_bars:
            final_timestamp = max(bar.timestamp for bar in last_bars.values())
            final_point = EquityPoint(
                timestamp=final_timestamp,
                equity=round(cash, 2),
            )
            if equity_curve and equity_curve[-1].timestamp == final_timestamp:
                equity_curve[-1] = final_point
            else:
                equity_curve.append(final_point)

    final_equity = equity_curve[-1].equity if equity_curve else cash
    metrics = _trade_metrics(
        request.initial_equity,
        final_equity,
        trades,
        equity_curve,
        positions=positions,
        last_prices=last_prices,
        periods_per_year=request.periods_per_year,
        annual_risk_free_rate=request.annual_risk_free_rate,
        benchmark_return_pct=equal_weight_buy_and_hold_return(
            request.symbols,
            bars_by_symbol,
        ),
    )
    metrics.risk_rejections = len(risk_rejections)
    metrics.kill_switch_events = sum(
        1 for item in risk_rejections if item.kill_switch_active
    )
    metrics.allocation_rejections = len(allocation_rejections)
    return BacktestRunResult(
        strategy=request.strategy,
        symbols=[symbol.upper() for symbol in request.symbols],
        metrics=metrics,
        trades=trades,
        equity_curve=equity_curve,
        risk_rejections=risk_rejections,
        allocation_rejections=allocation_rejections,
        warnings=warnings,
    )


def run_backtest(request: BacktestRunRequest) -> BacktestRunResult:
    return _run_backtest(request)
