from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.models import BacktestMetrics, BacktestRunRequest, BacktestRunResult, EquityPoint, PriceBar, SimulatedTrade


@dataclass
class Position:
    quantity: float = 0.0
    average_price: float = 0.0


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
        fast = sma(closes[symbol], request.fast_window)
        slow = sma(closes[symbol], request.slow_window)
        position = positions[symbol]

        if fast is not None and slow is not None and fast > slow and position.quantity <= 0:
            max_position_value = request.initial_equity * request.max_position_pct
            price = _buy_price(bar.close, request.slippage_bps)
            quantity = int(max_position_value / price)
            cost = price * quantity
            fees = _fee(cost, request.fee_bps)
            if quantity > 0 and cash >= cost + fees:
                cash -= cost + fees
                position.quantity = float(quantity)
                position.average_price = price
                trades.append(SimulatedTrade(symbol=symbol, side="buy", quantity=quantity, price=round(price, 4), fees=round(fees, 2), timestamp=bar.timestamp))

        if fast is not None and slow is not None and fast < slow and position.quantity > 0:
            price = _sell_price(bar.close, request.slippage_bps)
            proceeds = price * position.quantity
            fees = _fee(proceeds, request.fee_bps)
            realized_pnl = (price - position.average_price) * position.quantity - fees
            cash += proceeds - fees
            trades.append(SimulatedTrade(symbol=symbol, side="sell", quantity=position.quantity, price=round(price, 4), fees=round(fees, 2), timestamp=bar.timestamp, realized_pnl=round(realized_pnl, 2)))
            position.quantity = 0.0
            position.average_price = 0.0

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
