"""
FastAPI Web 服务器

提供 REST API 和 WebSocket 端点。
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .models import (
    ControlRequest,
    ControlResponse,
    SnapshotResponse,
)
from .state import WebState

logger = logging.getLogger(__name__)

# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"


def create_app(state: WebState, control_callback=None) -> FastAPI:
    """创建 FastAPI 应用"""

    app = FastAPI(
        title="Quidem Trading Bot",
        description="量化交易 CTA 系统 Web 界面",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # CORS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 控制回调函数
    _control_callback = control_callback

    # ==================== REST API ====================

    @app.get("/api/status", response_model=SnapshotResponse)
    async def get_status():
        """获取系统完整状态快照"""
        return state.get_snapshot()

    @app.get("/api/market")
    async def get_market():
        """获取市场数据"""
        return state.get_market()

    @app.get("/api/strategy")
    async def get_strategy():
        """获取策略状态"""
        return state.get_strategy()

    @app.get("/api/position")
    async def get_position():
        """获取持仓信息"""
        return state.get_position()

    @app.get("/api/account")
    async def get_account():
        """获取账户信息"""
        return state.get_account() if hasattr(state, 'get_account') else {}

    @app.get("/api/trades")
    async def get_trades(limit: int = 50):
        """获取交易历史"""
        return state.get_trades(limit)

    @app.get("/api/alerts")
    async def get_alerts(limit: int = 20):
        """获取告警历史"""
        return state.get_alerts(limit)

    @app.get("/api/system")
    async def get_system():
        """获取系统状态"""
        return state.get_system()

    @app.post("/api/control", response_model=ControlResponse)
    async def control(request: ControlRequest):
        """发送控制命令"""
        if _control_callback is None:
            return ControlResponse(
                success=False,
                message="Control callback not configured"
            )

        try:
            result = await _control_callback(request)
            return ControlResponse(
                success=True,
                message=result or f"Action {request.action} executed"
            )
        except Exception as e:
            logger.error(f"Control error: {e}")
            return ControlResponse(
                success=False,
                message=str(e)
            )

    # ==================== WebSocket ====================

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket 实时数据推送"""
        await websocket.accept()
        logger.info("WebSocket client connected")

        # 保存当前的 FastAPI 事件循环
        loop = asyncio.get_running_loop()

        # 添加订阅
        async def send_message(message: str):
            try:
                await websocket.send_text(message)
            except Exception:
                pass

        # 同步回调包装
        def sync_callback(message: str):
            try:
                # 跨线程安全分发协程到 FastAPI 的事件循环执行
                asyncio.run_coroutine_threadsafe(send_message(message), loop)
            except Exception:
                pass

        state.subscribe(sync_callback)

        try:
            # 发送初始快照
            snapshot = state.get_snapshot()
            await websocket.send_json({
                'type': 'snapshot',
                'data': snapshot,
                'timestamp': int(time.time() * 1000),
            })

            # 保持连接
            while True:
                try:
                    # 接收客户端消息（心跳或命令）
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=30
                    )

                    # 处理心跳
                    if data == 'ping':
                        await websocket.send_text('pong')

                except asyncio.TimeoutError:
                    # 发送心跳
                    try:
                        await websocket.send_json({
                            'type': 'heartbeat',
                            'timestamp': int(time.time() * 1000),
                        })
                    except Exception:
                        break

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            state.unsubscribe(sync_callback)

    # ==================== 静态文件 ====================

    # 检查静态文件目录是否存在
    if STATIC_DIR.exists():
        # 挂载静态文件
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    else:
        @app.get("/")
        async def root():
            """根路径 - 开发模式提示"""
            return HTMLResponse(
                content="""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Quidem Trading Bot</title>
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            height: 100vh;
                            margin: 0;
                            background: #1a1a2e;
                            color: #eee;
                        }
                        .container {
                            text-align: center;
                            padding: 2rem;
                        }
                        h1 { color: #00d4ff; }
                        p { color: #888; margin: 1rem 0; }
                        code {
                            background: #16213e;
                            padding: 0.5rem 1rem;
                            border-radius: 4px;
                            color: #00d4ff;
                        }
                        .api-link {
                            color: #00d4ff;
                            text-decoration: none;
                        }
                        .api-link:hover {
                            text-decoration: underline;
                        }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>🤖 Quidem Trading Bot</h1>
                        <p>Web GUI 前端尚未构建</p>
                        <p>请运行以下命令构建前端：</p>
                        <code>cd web && npm run build</code>
                        <p style="margin-top: 2rem;">
                            <a href="/api/docs" class="api-link">API 文档 (Swagger)</a>
                            &nbsp;|&nbsp;
                            <a href="/api/status" class="api-link">系统状态</a>
                        </p>
                    </div>
                </body>
                </html>
                """,
                status_code=200
            )

    return app
