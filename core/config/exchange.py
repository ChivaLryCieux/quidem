import os
import sys
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

        # Binance Stream 名称必须小写，强制转换防止配置错误
        symbol_lower = Config.SYMBOL_WS.lower()
        self.url = (
            f"wss://fstream.binance.com/stream?streams="
            f"{symbol_lower}@kline_5m/"
            f"{symbol_lower}@kline_15m/"
            f"{symbol_lower}@kline_1h/"
            f"{symbol_lower}@depth20@100ms/"
            f"{symbol_lower}@markPrice/"
            f"btcusdt@kline_1m"
        )

        # 线程安全的数据存储
        self.lock = threading.Lock()
        self.data = {
            'kline_5m': None,
            'kline_15m': None,
            'kline_1h': None,
            'orderbook': None,
            'funding_rate': 0.0,
            'btc_price': 0.0,
            'is_ready': False
        }
        self.running = True
        self._last_update_time = time.time()
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

                # Ping/Pong 保持连接活跃
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
                elif 'kline_5m' in stream:
                    updates['kline_5m'] = kline_data
                elif 'kline_15m' in stream:
                    updates['kline_15m'] = kline_data
                elif 'kline_1h' in stream:
                    updates['kline_1h'] = kline_data

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

            # 快速更新，减少锁占用时间
            with self.lock:
                self.data.update(updates)

                # 检查数据是否准备就绪
                if not self.data['is_ready']:
                    if (self.data['kline_5m'] is not None and
                            self.data['kline_15m'] is not None and
                            self.data['kline_1h'] is not None and
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
        with self.lock:
            return self.data.copy()


class ExchangeService:
    def __init__(self, is_live=False):
        self.is_live = is_live

        # 增加 timeout 防止网络卡死
        conf = {
            'enableRateLimit': True,
            'timeout': 10000,  # 10秒超时
            'proxies': {'http': Config.PROXY_URL, 'https': Config.PROXY_URL},
            'options': {'defaultType': 'future'}
        }

        if is_live:
            # 添加调试信息验证API密钥加载
            logger.info(f"API_KEY loaded: {Config.API_KEY is not None}")
            logger.info(f"API_SECRET loaded: {Config.API_SECRET is not None}")
            logger.info(f"API_KEY length: {len(Config.API_KEY) if Config.API_KEY else 0}")
            logger.info(f"API_SECRET length: {len(Config.API_SECRET) if Config.API_SECRET else 0}")
            
            if not Config.API_KEY or not Config.API_SECRET:
                logger.error("Live mode selected but API credentials missing!")
                # 不抛出异常，允许程序继续运行(只读)，但在下单时会失败
            else:
                logger.info("API credentials found, configuring exchange client")
            conf.update({'apiKey': Config.API_KEY, 'secret': Config.API_SECRET})

        self.client = ccxt.binance(conf)
        self.symbol = Config.SYMBOL
        self.ws_streamer = MarketDataStreamer()

    def connect(self):
        try:
            logger.info("="*50)
            logger.info("Initializing REST API connection...")
            sys.stdout.flush()
            
            self.client.load_markets()
            logger.info("✅ REST API connected successfully")
            sys.stdout.flush()

            # 启动 WebSocket 线程
            logger.info("Starting WebSocket thread...")
            sys.stdout.flush()
            
            self.ws_streamer.start()
            logger.info("✅ WebSocket thread started")
            logger.info("Waiting for WS data stream...")
            sys.stdout.flush()

            # 等待 WebSocket 预热
            timeout = 0
            max_timeout = 30  # 最大等待30秒
            
            while not self.ws_streamer.data['is_ready']:
                time.sleep(1)
                timeout += 1
                
                # 每秒打印进度
                logger.info(f"  Waiting for WS data... {timeout}s / {max_timeout}s")
                sys.stdout.flush()
                
                if timeout > max_timeout:
                    logger.error(f"❌ WS Connection Timeout ({max_timeout}s)")
                    logger.error("Please check:")
                    logger.error("  1. Proxy is running (port 7890)")
                    logger.error("  2. Network connection")
                    logger.error("  3. Firewall settings")
                    sys.stdout.flush()
                    return False, f"WS Connection Timeout ({max_timeout}s) - Check Proxy/Network"

            logger.info("✅ WebSocket data stream ready")
            logger.info("="*50)
            sys.stdout.flush()
            return True, "Connected & WS Stream Ready"
            
        except Exception as e:
            logger.error(f"❌ Connection Failed: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            sys.stdout.flush()
            return False, f"Connection Failed: {str(e)}"

    def fetch_initial_history(self, limit=100):
        """只在启动时调用一次 REST API 获取历史 K 线"""
        try:
            # 获取5分钟K线历史数据
            ohlcv_5m = self.client.fetch_ohlcv(self.symbol, '5m', limit=limit)
            # 获取15分钟K线历史数据
            ohlcv_15m = self.client.fetch_ohlcv(self.symbol, '15m', limit=limit)
            # 获取1小时K线历史数据（刻时模型）
            ohlcv_1h = self.client.fetch_ohlcv(self.symbol, '1h', limit=max(50, limit // 2))
            return {'5m': ohlcv_5m, '15m': ohlcv_15m, '1h': ohlcv_1h}
        except Exception as e:
            logger.error(f"[History Fetch Error] {e}")
            return {'5m': [], '15m': [], '1h': []}

    def get_latest_data(self):
        """
        从 WebSocket 本地缓存读取数据
        返回: (最新5m K线列表, 最新15m K线列表, 最新1h K线列表, 订单簿, 资金费率, BTC价格)
        """
        data = self.ws_streamer.get_latest()

        # 使用 .get 安全获取，防止初始化时的 KeyError
        kline_5m = data.get('kline_5m')
        kline_15m = data.get('kline_15m')
        kline_1h = data.get('kline_1h')
        book = data.get('orderbook')
        funding = data.get('funding_rate', 0.0)
        btc_price = data.get('btc_price', 0.0)

        return kline_5m, kline_15m, kline_1h, book, funding, btc_price

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
            # 记录下单请求，方便调试
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

    def fetch_balance(self):
        """获取账户余额信息"""
        if not self.is_live:
            # 模拟盘返回默认余额100 USDT
            return {
                'free': 100.0,
                'used': 0.0,
                'total': 100.0
            }
            
        try:
            balance = self.client.fetch_balance()
            # 返回USDT余额和总权益
            usdt_balance = balance.get('USDT', {})
            return {
                'free': usdt_balance.get('free', 0.0),
                'used': usdt_balance.get('used', 0.0),
                'total': usdt_balance.get('total', 0.0)
            }
        except Exception as e:
            logger.error(f"获取账户余额失败: {e}")
            return None

    def close(self):
        self.ws_streamer.stop()
        try:
            # 部分 CCXT 版本支持 close
            if hasattr(self.client, 'close'):
                self.client.close()
        except:
            pass