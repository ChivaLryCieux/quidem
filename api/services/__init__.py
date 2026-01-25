"""
服务包初始化
"""
from .redis_service import RedisService
from .bot_service import BotService

__all__ = ["RedisService", "BotService"]
