"""
Redis服务封装
"""
import redis
import json
import logging
from typing import Optional, List, Dict
from ..config import APIConfig

logger = logging.getLogger(__name__)

class RedisService:
    """Redis数据访问服务"""
    
    def __init__(self):
        self.client: Optional[redis.Redis] = None
        self._connect()
    
    def _connect(self):
        """连接Redis"""
        try:
            self.client = redis.Redis(
                host=APIConfig.REDIS_HOST,
                port=APIConfig.REDIS_PORT,
                db=APIConfig.REDIS_DB,
                password=APIConfig.REDIS_PASSWORD,
                socket_timeout=3,
                decode_responses=True
            )
            self.client.ping()
            logger.info(f"Redis连接成功: {APIConfig.REDIS_HOST}:{APIConfig.REDIS_PORT}")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            self.client = None
    
    def get_heartbeat(self) -> Optional[Dict]:
        """获取机器人心跳数据"""
        if not self.client:
            return None
        
        try:
            data = self.client.get('bot_status_heartbeat')
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"获取心跳数据失败: {e}")
            return None
    
    def get_trade_journal(self, limit: int = 100) -> List[Dict]:
        """获取交易记录"""
        if not self.client:
            return []
        
        try:
            records = self.client.lrange('trade_journal_pending', 0, limit - 1)
            return [json.loads(r) for r in records]
        except Exception as e:
            logger.error(f"获取交易记录失败: {e}")
            return []
    
    def send_control_command(self, action: str, params: dict = None) -> bool:
        """发送控制命令"""
        if not self.client:
            return False
        
        try:
            command = {
                "action": action,
                "timestamp": int(time.time() * 1000),
                "params": params or {}
            }
            self.client.set('bot_control_command', json.dumps(command), ex=60)
            logger.info(f"发送控制命令: {action}")
            return True
        except Exception as e:
            logger.error(f"发送控制命令失败: {e}")
            return False
    
    def get_config_cache(self) -> Optional[Dict]:
        """获取配置缓存"""
        if not self.client:
            return None
        
        try:
            data = self.client.get('bot_config_cache')
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"获取配置缓存失败: {e}")
            return None
    
    def update_config_cache(self, config: dict) -> bool:
        """更新配置缓存"""
        if not self.client:
            return False
        
        try:
            self.client.set('bot_config_cache', json.dumps(config))
            logger.info("配置缓存已更新")
            return True
        except Exception as e:
            logger.error(f"更新配置缓存失败: {e}")
            return False

import time
