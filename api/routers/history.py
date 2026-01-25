"""
历史数据路由
"""
from fastapi import APIRouter, Depends, Query
from typing import List
from ..auth import verify_api_key
from ..services import BotService
from ..models.schemas import TradeRecord, PerformanceStats

router = APIRouter(prefix="/history", tags=["历史数据"])

def get_bot_service():
    from ..main import bot_service
    return bot_service

@router.get("/trades", response_model=List[TradeRecord], summary="获取交易历史")
async def get_trade_history(
    limit: int = Query(100, ge=1, le=1000, description="返回记录数量"),
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """
    获取交易历史记录
    
    参数:
    - limit: 返回记录数量(1-1000)
    """
    trades = service.get_trade_history(limit)
    return trades

@router.get("/performance", response_model=PerformanceStats, summary="获取收益统计")
async def get_performance(
    limit: int = Query(100, ge=1, le=1000, description="统计记录数量"),
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """
    获取收益统计数据
    
    返回:
    - total_trades: 总交易次数
    - win_rate: 胜率
    - total_pnl: 总盈亏
    - max_drawdown: 最大回撤
    """
    trades = service.get_trade_history(limit)
    stats = service.calculate_performance(trades)
    return stats
