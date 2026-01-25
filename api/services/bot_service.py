"""
机器人业务逻辑服务
"""
import logging
from typing import Optional, List, Dict
from .redis_service import RedisService
from ..models.schemas import BotStatus, TradeRecord, PerformanceStats

logger = logging.getLogger(__name__)

class BotService:
    """机器人业务逻辑服务"""
    
    def __init__(self, redis_service: RedisService):
        self.redis = redis_service
    
    def get_current_status(self) -> Optional[BotStatus]:
        """获取当前状态"""
        data = self.redis.get_heartbeat()
        if not data:
            return None
        
        try:
            return BotStatus(**data)
        except Exception as e:
            logger.error(f"解析状态数据失败: {e}")
            return None
    
    def get_trade_history(self, limit: int = 100) -> List[TradeRecord]:
        """获取交易历史"""
        records = self.redis.get_trade_journal(limit)
        trade_list = []
        
        for record in records:
            try:
                trade_list.append(TradeRecord(**record))
            except Exception as e:
                logger.error(f"解析交易记录失败: {e}")
                continue
        
        return trade_list
    
    def calculate_performance(self, trades: List[TradeRecord]) -> PerformanceStats:
        """计算收益统计"""
        if not trades:
            return PerformanceStats(
                total_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                max_drawdown=0.0
            )
        
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.pnl and t.pnl > 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        total_pnl = sum(t.pnl for t in trades if t.pnl)
        
        # 计算最大回撤
        peak = 0.0
        max_drawdown = 0.0
        cumulative_pnl = 0.0
        
        for trade in trades:
            if trade.pnl:
                cumulative_pnl += trade.pnl
                if cumulative_pnl > peak:
                    peak = cumulative_pnl
                drawdown = peak - cumulative_pnl
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
        
        return PerformanceStats(
            total_trades=total_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            max_drawdown=max_drawdown
        )
    
    def send_control_command(self, action: str, params: dict = None) -> bool:
        """发送控制命令"""
        return self.redis.send_control_command(action, params)
    
    def get_config(self) -> Optional[Dict]:
        """获取配置"""
        return self.redis.get_config_cache()
    
    def update_config(self, config: dict) -> bool:
        """更新配置"""
        return self.redis.update_config_cache(config)
