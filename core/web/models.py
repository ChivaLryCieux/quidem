"""
Pydantic 数据模型

定义 API 请求和响应的数据结构。
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MarketData(BaseModel):
    """市场数据"""
    price: float = 0.0
    kline_5m: Optional[List[Any]] = None
    kline_15m: Optional[List[Any]] = None
    kline_1h: Optional[List[Any]] = None
    kline_1d: Optional[List[Any]] = None
    orderbook: Optional[Dict[str, Any]] = None
    funding_rate: float = 0.0
    btc_price: float = 0.0
    change_24h: float = 0.0


class StrategyState(BaseModel):
    """策略状态"""
    state: str = '⏳ 等待'
    color: str = 'white'
    adx: float = 0.0
    macd: float = 0.0
    reversal: float = 0.0
    supertrend_5m: int = 0
    supertrend_15m: int = 0
    supertrend_1h: int = 0


class PositionInfo(BaseModel):
    """持仓信息"""
    size: float = 0.0
    entry_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    entry_time: int = 0
    leverage: float = 10.0
    unrealized_pnl: float = 0.0


class AccountInfo(BaseModel):
    """账户信息"""
    balance: float = 0.0
    mode: str = 'Paper'
    symbol: str = 'SOL/USDT'


class TradeRecord(BaseModel):
    """交易记录"""
    type: str  # 'entry' or 'exit'
    time: int
    # 开仓字段
    side: Optional[str] = None
    price: Optional[float] = None
    leverage: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    regime: Optional[str] = None
    # 平仓字段
    reason: Optional[str] = None
    pnl: Optional[float] = None
    fee: Optional[float] = None
    balance: Optional[float] = None


class AlertRecord(BaseModel):
    """告警记录"""
    type: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    time: int


class SystemStatus(BaseModel):
    """系统状态"""
    status: str = 'initializing'
    uptime: int = 0
    start_time: float = 0.0
    ws_connected: bool = False
    exchange_connected: bool = False
    error_message: str = ''
    trading_mode: str = 'dashboard'


class SnapshotResponse(BaseModel):
    """完整快照响应"""
    market: MarketData
    strategy: StrategyState
    position: PositionInfo
    account: AccountInfo
    trades: List[TradeRecord]
    alerts: List[AlertRecord]
    system: SystemStatus


class ControlRequest(BaseModel):
    """控制请求"""
    action: str  # 'switch_mode', 'switch_symbol', 'pause', 'resume', 'exit'
    mode: Optional[str] = None  # 目标模式 'paper'/'live'
    symbol: Optional[str] = None  # 目标标的 'BTC'/'ETH'/'SOL'等


class ControlResponse(BaseModel):
    """控制响应"""
    success: bool
    message: str


class LogEntry(BaseModel):
    """日志条目"""
    timestamp: int
    level: str
    message: str
