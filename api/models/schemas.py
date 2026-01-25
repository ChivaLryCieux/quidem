"""
Pydantic数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal

# 响应模型
class BotStatus(BaseModel):
    """机器人状态"""
    timestamp: int = Field(..., description="时间戳(毫秒)")
    balance: float = Field(..., description="账户余额")
    position_size: float = Field(..., description="持仓数量")
    price: float = Field(..., description="当前价格")
    regime: str = Field(..., description="市场状态")
    ai_conf: float = Field(..., description="AI预测置信度")
    cluster: int = Field(..., description="聚类状态")
    hf_signal: float = Field(..., description="高频信号")

class TradeRecord(BaseModel):
    """交易记录"""
    timestamp: int
    action: str
    price: float
    size: float
    pnl: Optional[float] = None
    balance: float

class PerformanceStats(BaseModel):
    """收益统计"""
    total_trades: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    sharpe_ratio: Optional[float] = None

# 请求模型
class ControlCommand(BaseModel):
    """控制命令"""
    action: Literal["start", "stop", "pause", "close_position"] = Field(..., description="操作类型")
    params: Optional[dict] = Field(default={}, description="额外参数")

class ConfigUpdate(BaseModel):
    """配置更新"""
    leverage: Optional[float] = Field(None, ge=1.0, le=20.0, description="杠杆倍数")
    risk_appetite: Optional[float] = Field(None, ge=0.01, le=0.1, description="风险偏好")
    
# 通用响应
class APIResponse(BaseModel):
    """通用API响应"""
    success: bool
    message: str
    data: Optional[dict] = None
