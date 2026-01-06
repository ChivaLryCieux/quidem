import os
import time
import json
import threading
import websocket
import ccxt
import logging
from .settings import Config
from colorama import Fore, Style

logger = logging.getLogger(__name__)


class MarketDataStreamer(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.ws = None

        # [优化] Binance Stream 名称必须小写，强制转换防止配置错误
        symbol_lower = Config.SYMBOL_WS.lower()
        self.url = (
            f"wss://fstream.binance.com/stream?streams="
            f"{symbol_lower}@kline_{Config.TIMEFRAME}/"
            f"{symbol_lower}@kline_15m/"
            f"{symbol_lower}@depth20@100ms/"
            f"{symbol_lower}@markPrice/"
            f"btcusdt@kline_1m"
        )

        # 线程安全的数据存储
        self.lock = threading.Lock()
        self.data = {
            'kline_1m': None,
            'kline_15m': None,
            'orderbook': None,
            'funding_rate': 0.0,
            'btc_price': 0.0,
            'is_ready': False
        }
        self.running = True
        self._last_update_time = time.time()

    def run(self):
        while self.running:
            try:
                logger.info(f"Connecting to WS: {self.url}")
                # 配置 WebSocket
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )

                # 设置代理
                proxy_opts = {}
                if Config.PROXY_HOST and Config.PROXY_PORT:
                    proxy_opts = {
                        "http_proxy_host": Config.PROXY_HOST,
                        "http_proxy_port": Config.PROXY_PORT,
                        "proxy_type": "http"
                    }

                # [优化] Ping/Pong 保持连接活跃
                self.ws.run_forever(ping_interval=30, ping_timeout=10, **proxy_opts)
            except Exception as e:
                logger.error(f"WS Critical Error: {e}")

            if self.running:
                logger.warning("WS Disconnected. Reconnecting in 3s...")
                time.sleep(3)

    def _on_open(self, ws):
        print(f"{Fore.GREEN}[WS] Connected to Binance Futures Stream{Style.RESET_ALL}")

    def _on_message(self, ws, message):
        try:
            # json.loads 比较耗时，放在锁外面执行
            msg = json.loads(message)
            stream = msg.get('stream')
            payload = msg.get('data')

            if not stream or not payload:
                return

            # 准备好数据结构，尽量减少在锁内的时间
            updates = {}

            # 1. K线数据处理
            if 'kline' in stream:
                k = payload['k']
                # 转换为浮点数列表
                kline_data = [
                    k['t'], float(k['o']), float(k['h']), float(k['l']),
                    float(k['c']), float(k['v']), float(k['Q'])
                ]

                if 'btcusdt' in stream:
                    updates['btc_price'] = float(k['c'])
                elif 'kline_1m' in stream:  # 依赖 stream name 包含 timeframe
                    updates['kline_1m'] = kline_data
                elif 'kline_15m' in stream:
                    updates['kline_15m'] = kline_data

            # 2. 深度数据处理
            elif 'depth20' in stream:
                updates['orderbook'] = {
                    'bids': [[float(p), float(v)] for p, v in payload['b']],
                    'asks': [[float(p), float(v)] for p, v in payload['a']]
                }

            # 3. 资金费率
            elif 'markPrice' in stream:
                if 'r' in payload:
                    updates['funding_rate'] = float(payload['r'])

            # [优化] 快速更新，减少锁占用时间
            with self.lock:
                self.data.update(updates)

                # 检查数据是否准备就绪
                if not self.data['is_ready']:
                    if (self.data['kline_15m'] is not None and
                            self.data['orderbook'] is not None):
                        self.data['is_ready'] = True
                        logger.info("Market Data Ready!")

                self._last_update_time = time.time()

        except Exception as e:
            logger.error(f"WS Message Parse Error: {e}")

    def _on_error(self, ws, error):
        logger.error(f"[WS Error] {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"[WS] Closed. Status: {close_status_code}, Msg: {close_msg}")

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

    def get_latest(self):
        """
        线程安全地获取最新数据
        [优化] 移除 deepcopy，改为浅拷贝。
        因为 _on_message 中是整块替换 list/dict 引用，而不是原地修改，
        所以浅拷贝返回的引用指向的数据是安全的，且速度快 100 倍以上。
        """
        with self.lock:
            return self.data.copy()


class ExchangeService:
    def __init__(self, is_live=False):
        self.is_live = is_live

        # [优化] 增加 timeout 防止网络卡死
        conf = {
            'enableRateLimit': True,
            'timeout': 10000,  # 10秒超时
            'proxies': {'http': Config.PROXY_URL, 'https': Config.PROXY_URL},
            'options': {'defaultType': 'future'}
        }

        if is_live:
            if not Config.API_KEY or not Config.API_SECRET:
                logger.error("Live mode selected but API credentials missing!")
                # 不抛出异常，允许程序继续运行(只读)，但在下单时会失败
            conf.update({'apiKey': Config.API_KEY, 'secret': Config.API_SECRET})

        self.client = ccxt.binance(conf)
        self.symbol = Config.SYMBOL
        self.ws_streamer = MarketDataStreamer()

    def connect(self):
        try:
            logger.info("Initializing REST API connection...")
            self.client.load_markets()

            # 启动 WebSocket 线程
            self.ws_streamer.start()
            logger.info("Waiting for WS data stream...")

            # 等待 WebSocket 预热
            timeout = 0
            while not self.ws_streamer.data['is_ready']:
                time.sleep(1)
                timeout += 1
                if timeout > 30:  # 增加超时宽容度
                    return False, "WS Connection Timeout (Check Proxy/Network)"

                # 每5秒打印一次进度
                if timeout % 5 == 0:
                    logger.info(f"Waiting for WS... {timeout}s")

            return True, "Connected & WS Stream Ready"
        except Exception as e:
            return False, f"Connection Failed: {str(e)}"

    def fetch_initial_history(self, limit=100):
        """只在启动时调用一次 REST API 获取历史 K 线"""
        try:
            # 获取1分钟K线历史数据
            ohlcv_1m = self.client.fetch_ohlcv(self.symbol, '1m', limit=limit)
            # 获取15分钟K线历史数据
            ohlcv_15m = self.client.fetch_ohlcv(self.symbol, '15m', limit=limit)
            return {'1m': ohlcv_1m, '15m': ohlcv_15m}
        except Exception as e:
            logger.error(f"[History Fetch Error] {e}")
            # [优化] 如果失败返回空列表，防止 NoneType 错误
            return {'1m': [], '15m': []}

    def get_latest_data(self):
        """
        从 WebSocket 本地缓存读取数据
        返回: (最新1m K线列表, 最新15m K线列表, 订单簿, 资金费率, BTC价格)
        """
        data = self.ws_streamer.get_latest()

        # 使用 .get 安全获取，防止初始化时的 KeyError
        kline_1m = data.get('kline_1m')
        kline_15m = data.get('kline_15m')
        book = data.get('orderbook')
        funding = data.get('funding_rate', 0.0)
        btc_price = data.get('btc_price', 0.0)

        return kline_1m, kline_15m, book, funding, btc_price

    def get_precision_amount(self, amount, price):
        """将数量转换为交易所规定的精度"""
        try:
            return float(self.client.amount_to_precision(self.symbol, amount))
        except Exception as e:
            logger.error(f"Precision Error: {e}")
            return amount

    def execute_order(self, side, amount, params={}):
        if not self.is_live:
            logger.info(f"[PAPER] Order {side} {amount} {params}")
            return True

        try:
            # [优化] 记录下单请求，方便调试
            logger.info(f"[LIVE EXEC] {side.upper()} {amount} | Params: {params}")

            # create_market_order 是同步阻塞的，timeout 由 ccxt 配置控制
            order = self.client.create_market_order(self.symbol, side, amount, params=params)

            # 简单的成交确认
            if order and order.get('status') in ['closed', 'open']:
                return True
            else:
                logger.warning(f"Order status invalid: {order.get('status')}")
                return False

        except ccxt.InsufficientFunds as e:
            logger.error(f"Insufficient Funds: {e}")
            return False
        except ccxt.NetworkError as e:
            logger.error(f"Network Error during order: {e}")
            return False
        except Exception as e:
            logger.error(f"Order Execution Error: {e}")
            return False

    def close(self):
        self.ws_streamer.stop()
        try:
            # 部分 CCXT 版本支持 close
            if hasattr(self.client, 'close'):
                self.client.close()
        except:
            pass