"""
FastAPI配置文件
"""
import os
from dotenv import load_dotenv

load_dotenv()

class APIConfig:
    # API服务配置
    API_HOST = "0.0.0.0"  # 监听所有网络接口
    API_PORT = 8000
    API_TITLE = "Q-Bot Trading API"
    API_VERSION = "1.0.0"
    
    # Redis配置
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB = int(os.getenv("REDIS_DB", 0))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
    
    # 安全配置
    API_KEY = os.getenv("API_KEY", "your-secret-api-key-change-this")
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5173",  # Vite默认端口
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    
    # WebSocket配置
    WS_HEARTBEAT_INTERVAL = 1  # 秒
