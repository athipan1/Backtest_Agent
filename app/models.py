from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator


T = TypeVar("T")
StrategyName = Literal["sma_crossover", "trend_following", "mean_reversion", "breakout"]


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
    strategy: StrategyName = "sma_crossover"
    fast_window: int = Field(default=3, ge=1)
    slow_window: int = Field(default=5, ge=2)
    risk_per_trade: float = Field(default=0.01, gt=0, le=1)
    max_position_pct: float = Field(default=0.10, gt=0, le=1)
    stop_loss_pct: float = Field(default=0.03, gt=0, lt=1)
    reward_risk_ratio: float = Field(default=2.0, gt=0)
    fee_bps: float = Field(default=10, ge=0)
    slippage_bps: float = Field(default=5, ge=0)
    use_risk_agent: bool = True
    emergency_halt: bool = False
    max_trades_per_day: int = Field(default=5, ge=1)
    force_close_at_end: bool = False
    max_total_exposure_pct: float = Field(default=1.0, gt=0, le=1)
    max_open_positions: int = Field(default=25, ge=1)
    cash_reserve_pct: float = Field(default=0.0, ge=0, lt=1)
    max_new_positions_per_bar: int = Field(default=25, ge=1)

    @model_validator(mode="after")
    def validate_windows(self) -> "BacktestRunRequest":
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be smaller than slow_window")
        missing = [symbol for symbol in self.symbols if symbol.upper() not in {key.upper() for key in self.bars}]
        if missing:
            raise ValueError(f"missing bars for symbols: {missing}")
        return self


class StrategyCandidate(BaseModel):
    name: str = Field(default="sma_crossover")
    strategy: StrategyName = "sma_crossover"
    fast_window: int = Field(default=3, ge=1)
    slow_window: int = Field(default=5, ge=2)
    max_position_pct: Optional[float] = Field(default=None, gt=0, le=1)
    stop_loss_pct: Optional[float] = Field(default=None, gt=0, lt=1)
    reward_risk_ratio: Optional[float] = Field(default=None, gt=0)
    fee_bps: Optional[float] = Field(default=None, ge=0)
    slippage_bps: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_candidate_windows(self) -> "StrategyCandidate":
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be smaller than slow_window")
        return self


class BacktestCompareRequest(BaseModel):
    symbols: List[str] = Field(min_length=1)
    initial_equity: float = Field(gt=0)
    bars: Dict[str, List[PriceBar]]
    candidates: List[StrategyCandidate] = Field(min_length=1, max_length=25)
    risk_per_trade: float = Field(default=0.01, gt=0, le=1)
    max_position_pct: float = Field(default=0.10, gt=0, le=1)
    stop_loss_pct: float = Field(default=0.03, gt=0, lt=1)
    reward_risk_ratio: float = Field(default=2.0, gt=0)
    fee_bps: float = Field(default=10, ge=0)
    slippage_bps: float = Field(default=5, ge=0)
    use_risk_agent: bool = True
    emergency_halt: bool = False
    max_trades_per_day: int = Field(default=5, ge=1)
    force_close_at_end: bool = False
    max_total_exposure_pct: float = Field(default=1.0, gt=0, le=1)
    max_open_positions: int = Field(default=25, ge=1)
    cash_reserve_pct: float = Field(default=0.0, ge=0, lt=1)
    max_new_positions_per_bar: int = Field(default=25, ge=1)

    @model_validator(mode="after")
    def validate_compare_bars(self) -> "BacktestCompareRequest":
        missing = [symbol for symbol in self.symbols if symbol.upper() not in {key.upper() for key in self.bars}]
        if missing:
            raise ValueError(f"missing bars for symbols: {missing}")
        return self


class WalkForwardRequest(BaseModel):
    symbols: List[str] = Field(min_length=1)
    initial_equity: float = Field(gt=0)
    bars: Dict[str, List[PriceBar]]
    candidates: List[StrategyCandidate] = Field(min_length=1, max_length=25)
    train_ratio: float = Field(default=0.70, gt=0.1, lt=0.9)
    min_train_bars: int = Field(default=10, ge=3)
    min_test_bars: int = Field(default=5, ge=2)
    risk_per_trade: float = Field(default=0.01, gt=0, le=1)
    max_position_pct: float = Field(default=0.10, gt=0, le=1)
    stop_loss_pct: float = Field(default=0.03, gt=0, lt=1)
    reward_risk_ratio: float = Field(default=2.0, gt=0)
    fee_bps: float = Field(default=10, ge=0)
    slippage_bps: float = Field(default=5, ge=0)
    use_risk_agent: bool = True
    emergency_halt: bool = False
    max_trades_per_day: int = Field(default=5, ge=1)
    force_close_at_end: bool = False
    max_total_exposure_pct: float = Field(default=1.0, gt=0, le=1)
    max_open_positions: int = Field(default=25, ge=1)
    cash_reserve_pct: float = Field(default=0.0, ge=0, lt=1)
    max_new_positions_per_bar: int = Field(default=25, ge=1)

    @model_validator(mode="after")
    def validate_walk_forward_bars(self) -> "WalkForwardRequest":
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


class AllocationRejection(BaseModel):
    symbol: str
    timestamp: datetime
    requested_quantity: float
    approved_quantity: float = 0.0
    reason: str
    source: str = "synchronous_portfolio_allocator"


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
    realized_net_profit: float = 0.0
    unrealized_pnl: float = 0.0
    open_position_count: int = 0
    allocation_rejections: int = 0
    risk_rejections: int = 0
    kill_switch_events: int = 0


class BacktestRunResult(BaseModel):
    strategy: str
    symbols: List[str]
    execution_model: str = "next_bar_open"
    position_sizing_model: str = "current_equity_risk_and_position_cap"
    allocation_policy: str = "timestamp_batch_symbol_ascending"
    metrics: BacktestMetrics
    trades: List[SimulatedTrade]
    equity_curve: List[EquityPoint]
    risk_rejections: List[RiskRejection] = Field(default_factory=list)
    allocation_rejections: List[AllocationRejection] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class StrategyComparisonResult(BaseModel):
    rank: int
    name: str
    strategy: str
    fast_window: int
    slow_window: int
    score: float
    metrics: BacktestMetrics
    warnings: List[str] = Field(default_factory=list)


class BacktestCompareResult(BaseModel):
    symbols: List[str]
    ranked_results: List[StrategyComparisonResult]
    best: Optional[StrategyComparisonResult] = None


class WalkForwardResult(BaseModel):
    symbols: List[str]
    train_ratio: float
    train_bars: Dict[str, int]
    test_bars: Dict[str, int]
    selected_candidate: Optional[StrategyComparisonResult] = None
    train_ranking: List[StrategyComparisonResult]
    test_result: Optional[BacktestRunResult] = None
    passed: bool
    reasons: List[str] = Field(default_factory=list)


class PerformanceReportRequest(BaseModel):
    result: BacktestRunResult
    min_trades: int = Field(default=10, ge=1)
    min_profit_factor: float = Field(default=1.30, gt=0)
    max_drawdown_floor: float = Field(default=-0.10, lt=0)
    min_expectancy: float = Field(default=0.0)


class PerformanceReport(BaseModel):
    verdict: Literal["paper_ready", "needs_improvement", "blocked"]
    score: float
    summary: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    gates: Dict[str, bool]
    metrics: BacktestMetrics
