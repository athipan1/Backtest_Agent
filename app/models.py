from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator


T = TypeVar("T")


class StandardAgentResponse(BaseModel, Generic[T]):
    status: str
    agent_type: str = "backtest-agent"
    version: str = "0.1.0"
    data: Optional[T] = None
    error: Optional[str] = None


class HealthData(BaseModel):
    status: str = "healthy"
    service: str = "backtest-agent"


class PriceBar(BaseModel):
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0, default=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "PriceBar":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be greater than or equal to open, close, and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be less than or equal to open, close, and high")
        return self


class BacktestRunRequest(BaseModel):
    symbols: List[str] = Field(min_length=1)
    initial_equity: float = Field(gt=0)
    bars: Dict[str, List[PriceBar]]
    strategy: Literal["sma_crossover"] = "sma_crossover"
    fast_window: int = Field(default=3, ge=1)
    slow_window: int = Field(default=5, ge=2)
    risk_per_trade: float = Field(default=0.01, gt=0, le=1)
    max_position_pct: float = Field(default=0.10, gt=0, le=1)
    fee_bps: float = Field(default=10, ge=0)
    slippage_bps: float = Field(default=5, ge=0)
    use_risk_agent: bool = True
    emergency_halt: bool = False
    max_trades_per_day: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def validate_windows(self) -> "BacktestRunRequest":
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be smaller than slow_window")
        missing = [symbol for symbol in self.symbols if symbol.upper() not in {key.upper() for key in self.bars}]
        if missing:
            raise ValueError(f"missing bars for symbols: {missing}")
        return self


class RiskCheckPayload(BaseModel):
    account_id: str = "backtest"
    symbol: str
    side: Literal["buy", "sell"]
    entry_price: float
    protection_price: float
    equity: float
    requested_quantity: float
    current_symbol_exposure: float = 0.0
    current_total_exposure: float = 0.0
    open_orders_exposure: float = 0.0
    margin_multiplier: float = 1.0
    trading_mode: str = "BACKTEST"
    asset_class: str = "stock"
    daily_realized_pnl: float = 0.0
    weekly_realized_pnl: float = 0.0
    consecutive_losses: int = 0
    trades_today: int = 0
    symbol_trades_today: int = 0
    emergency_halt: bool = False


class RiskDecision(BaseModel):
    approved: bool
    final_quantity: float = 0.0
    violations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    kill_switch_active: bool = False
    source: str = "local_backtest_risk"


class SimulatedTrade(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    fees: float
    timestamp: datetime
    realized_pnl: float = 0.0
    reason: str = "signal"


class EquityPoint(BaseModel):
    timestamp: datetime
    equity: float


class RiskRejection(BaseModel):
    symbol: str
    timestamp: datetime
    side: Literal["buy", "sell"]
    requested_quantity: float
    violations: List[str] = Field(default_factory=list)
    kill_switch_active: bool = False
    source: str = "local_backtest_risk"


class BacktestMetrics(BaseModel):
    initial_equity: float
    final_equity: float
    net_profit: float
    return_pct: float
    trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: Optional[float]
    expectancy: float
    max_drawdown: float
    risk_rejections: int = 0
    kill_switch_events: int = 0


class BacktestRunResult(BaseModel):
    strategy: str
    symbols: List[str]
    metrics: BacktestMetrics
    trades: List[SimulatedTrade]
    equity_curve: List[EquityPoint]
    risk_rejections: List[RiskRejection] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
