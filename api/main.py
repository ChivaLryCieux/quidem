"""
FastAPI主入口文件
"""
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import json

from .config import APIConfig
from .services import RedisService, BotService
from .routers import status, control, history, config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 全局服务实例
redis_service: RedisService = None
bot_service: BotService = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global redis_service, bot_service
    
    # 启动时初始化
    logger.info("正在启动API服务...")
    redis_service = RedisService()
    bot_service = BotService(redis_service)
    logger.info("API服务启动完成")
    
    yield
    
    # 关闭时清理
    logger.info("正在关闭API服务...")

# 创建FastAPI应用
app = FastAPI(
    title=APIConfig.API_TITLE,
    version=APIConfig.API_VERSION,
    description="量化交易机器人API服务",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=APIConfig.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(status.router, prefix="/api")
app.include_router(control.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(config.router, prefix="/api")

# WebSocket连接管理
class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket连接建立,当前连接数: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket连接断开,当前连接数: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                disconnected.append(connection)
        
        # 清理断开的连接
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

manager = ConnectionManager()

@app.websocket("/ws/realtime")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket实时数据推送
    
    客户端连接后,服务器会每秒推送一次机器人状态数据
    """
    await manager.connect(websocket)
    
    try:
        while True:
            # 获取最新状态
            status_data = bot_service.get_current_status()
            
            if status_data:
                await websocket.send_json({
                    "type": "status_update",
                    "data": status_data.dict()
                })
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": "无法获取机器人状态"
                })
            
            # 等待1秒
            await asyncio.sleep(APIConfig.WS_HEARTBEAT_INTERVAL)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        manager.disconnect(websocket)

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Q-Bot Trading API",
        "version": APIConfig.API_VERSION,
        "docs": "/docs",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    redis_ok = redis_service.client is not None
    
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=APIConfig.API_HOST,
        port=APIConfig.API_PORT,
        reload=True
    )
