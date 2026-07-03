from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.models import BacktestMetrics, BacktestRunRequest, BacktestRunResult, EquityPoint, PriceBar, SimulatedTrade
from app.strategies import strategy_signal


@dataclass
class Position:
    quantity: float = 0.0
    average_price: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None

    def reset(self) -> None:
        self.quantity = 0.0
        self.average_price = 0.0
        self.stop_loss = None
        self.take_profit = None


def sma(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def max_drawdown(curve: List[EquityPoint]) -> float:
    if not curve:
        return 0.0
    peak = curve[0].equity
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
    realized_pnl = (exit_price - position.average_price) * position.quantity - fees
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
        return position.stop_loss, "stop_loss"
    if take_profit_hit:
        return position.take_profit, "take_profit"
    return None, None


def _trade_metrics(initial_equity: float, final_equity: float, trades: List[SimulatedTrade], curve: List[EquityPoint]) -> BacktestMetrics:
    realized = [trade.realized_pnl for trade in trades if trade.side == "sell"]
    winners = [pnl for pnl in realized if pnl > 0]
    losers = [pnl for pnl in realized if pnl < 0]
    gross_profit = round(sum(winners), 2)
    gross_loss = round(sum(losers), 2)
    trade_count = len(realized)
    net_profit = round(final_equity - initial_equity, 2)
    if gross_loss == 0:
        profit_factor = None if gross_profit > 0 else 0.0
    else:
        profit_factor = round(gross_profit / abs(gross_loss), 6)
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
        max_drawdown=max_drawdown(curve),
    )


def _bars_for_symbol(request: BacktestRunRequest, symbol: str) -> List[PriceBar]:
    for key, bars in request.bars.items():
        if key.upper() == symbol.upper():
            return sorted(bars, key=lambda bar: bar.timestamp)
    return []


def run_backtest(request: BacktestRunRequest) -> BacktestRunResult:
    cash = float(request.initial_equity)
    positions: Dict[str, Position] = {symbol.upper(): Position() for symbol in request.symbols}
    closes: Dict[str, List[float]] = {symbol.upper(): [] for symbol in request.symbols}
    history: Dict[str, List[PriceBar]] = {symbol.upper(): [] for symbol in request.symbols}
    trades: List[SimulatedTrade] = []
    equity_curve: List[EquityPoint] = []
    warnings: List[str] = []

    timeline = []
    bars_by_symbol = {symbol.upper(): _bars_for_symbol(request, symbol) for symbol in request.symbols}
    for symbol, bars in bars_by_symbol.items():
        if len(bars) < request.slow_window:
            warnings.append(f"{symbol} has fewer bars than slow_window")
        for bar in bars:
            timeline.append((bar.timestamp, symbol, bar))
    timeline.sort(key=lambda row: row[0])

    last_prices: Dict[str, float] = {}
    for _, symbol, bar in timeline:
        last_prices[symbol] = bar.close
        closes[symbol].append(bar.close)
        history[symbol].append(bar)
        signal = strategy_signal(request.strategy, closes[symbol], history[symbol], request.fast_window, request.slow_window)
        position = positions[symbol]

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
            max_position_value = request.initial_equity * request.max_position_pct
            price = _buy_price(bar.close, request.slippage_bps)
            quantity = int(max_position_value / price)
            cost = price * quantity
            fees = _fee(cost, request.fee_bps)
            if quantity > 0 and cash >= cost + fees:
                cash -= cost + fees
                stop_loss = _stop_loss_price(price, request)
                position.quantity = float(quantity)
                position.average_price = price
                position.stop_loss = stop_loss
                position.take_profit = _take_profit_price(price, stop_loss, request)
                trades.append(SimulatedTrade(symbol=symbol, side="buy", quantity=quantity, price=round(price, 4), fees=round(fees, 2), timestamp=bar.timestamp, reason=request.strategy))

        if signal == "sell" and position.quantity > 0:
            price = _sell_price(bar.close, request.slippage_bps)
            cash = _exit_position(
                symbol=symbol,
                position=position,
                cash=cash,
                exit_price=price,
                timestamp=bar.timestamp,
                reason=request.strategy,
                fee_bps=request.fee_bps,
                trades=trades,
            )

        equity = cash + sum(pos.quantity * last_prices.get(sym, pos.average_price) for sym, pos in positions.items())
        equity_curve.append(EquityPoint(timestamp=bar.timestamp, equity=round(equity, 2)))

    final_equity = equity_curve[-1].equity if equity_curve else cash
    metrics = _trade_metrics(request.initial_equity, final_equity, trades, equity_curve)
    return BacktestRunResult(
        strategy=request.strategy,
        symbols=[symbol.upper() for symbol in request.symbols],
        metrics=metrics,
        trades=trades,
        equity_curve=equity_curve,
        warnings=warnings,
    )
