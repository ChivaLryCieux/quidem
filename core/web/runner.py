"""
Web 线程管理器

在独立线程中运行 FastAPI 服务器，并自动打开浏览器。
"""

import logging
import threading
import time
import webbrowser
from typing import Callable, Optional

import uvicorn

from .server import create_app
from .state import WebState

logger = logging.getLogger(__name__)


class WebRunner:
    """Web 服务器运行器"""

    def __init__(
        self,
        state: WebState,
        host: str = "127.0.0.1",
        port: int = 8000,
        auto_open: bool = True,
        control_callback: Optional[Callable] = None,
    ):
        self.state = state
        self.host = host
        self.port = port
        self.auto_open = auto_open
        self.control_callback = control_callback

        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None
        self._ready = threading.Event()

    def start(self) -> None:
        """启动 Web 服务器（非阻塞）"""
        if self._thread and self._thread.is_alive():
            logger.warning("Web server already running")
            return

        self._thread = threading.Thread(
            target=self._run_server,
            name="WebServer",
            daemon=True,
        )
        self._thread.start()

        # 等待服务器启动
        if self._ready.wait(timeout=10):
            logger.info(f"Web server started at http://{self.host}:{self.port}")

            # 自动打开浏览器
            if self.auto_open:
                self._open_browser()
        else:
            logger.error("Web server startup timeout")

    def _run_server(self) -> None:
        """在线程中运行服务器"""
        try:
            # 创建 FastAPI 应用
            app = create_app(
                state=self.state,
                control_callback=self.control_callback,
            )

            # 配置 uvicorn
            config = uvicorn.Config(
                app=app,
                host=self.host,
                port=self.port,
                log_level="warning",  # 减少 uvicorn 日志
                access_log=False,
            )
            self._server = uvicorn.Server(config)

            # 标记服务器就绪
            self._ready.set()

            # 运行服务器
            self._server.run()

        except Exception as e:
            logger.error(f"Web server error: {e}")
            self._ready.set()  # 即使失败也释放等待

    def _open_browser(self) -> None:
        """自动打开浏览器"""
        url = f"http://{self.host}:{self.port}"

        # 延迟打开，等待服务器完全就绪
        def open_in_browser():
            time.sleep(1.5)
            try:
                webbrowser.open(url)
                logger.info(f"Browser opened: {url}")
            except Exception as e:
                logger.warning(f"Failed to open browser: {e}")

        threading.Thread(
            target=open_in_browser,
            name="BrowserOpener",
            daemon=True,
        ).start()

    def stop(self) -> None:
        """停止 Web 服务器"""
        if self._server:
            self._server.should_exit = True
            logger.info("Web server stopping...")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    @property
    def is_running(self) -> bool:
        """检查服务器是否运行中"""
        return self._thread is not None and self._thread.is_alive()

    def get_url(self) -> str:
        """获取服务器 URL"""
        return f"http://{self.host}:{self.port}"
