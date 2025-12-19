import os
import time
import json
import copy
import threading
import websocket
import ccxt
from colorama import Fore, Style

# ==========================================
# 1. 配置管理类
# ==========================================
class Config:
    # 代理与网络
    PROXY_PORT = 7897
    PROXY_HOST = "127.0.0.1"
    PROXY_URL = f"http://{PROXY_HOST}:{PROXY_PORT}"

    # 交易所 API
    API_KEY = "YOUR_BINANCE_API_KEY"
    API_SECRET = "YOUR_BINANCE_API_SECRET"

    # 交易标的与参数
    SYMBOL = 'XRP/USDT'
    SYMBOL_WS = 'xrpusdt'  # WebSocket用的全小写无斜杠名称
    TIMEFRAME = '1m'

    # 资金管理
    MIN_LEVERAGE = 5.0
    MAX_LEVERAGE = 5.0
    RISK_APPETITE = 0.03
    TAKER_FEE_RATE = 0.0005

    MAX_FUNDING_RATE_THRESHOLD = 0.0005

    # 策略参数
    BAILOUT_ON_NTH_FLIP = 3
    FEE_BUFFER_PCT = 0.0012
    MIN_ATR_PCT = 0.0020
    MIN_TP_DISTANCE = 0.0065

    # 微观结构
    OBI_THRESHOLD_TREND = -0.2
    OBI_THRESHOLD_BREAKOUT = 0.1
    MAX_SPREAD_PCT = 0.001

    @staticmethod
    def setup_proxy():
        # 如果需要设置系统级代理环境变量
        if Config.PROXY_HOST and Config.PROXY_PORT:
            os.environ["HTTP_PROXY"] = Config.PROXY_URL
            os.environ["HTTPS_PROXY"] = Config.PROXY_URL


# ==========================================
# 2. WebSocket 数据流服务
# ==========================================
class MarketDataStreamer(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.ws = None
        self.url = f"wss://fstream.binance.com/stream?streams={Config.SYMBOL_WS}@kline_{Config.TIMEFRAME}/{Config.SYMBOL_WS}@depth20@100ms/{Config.SYMBOL_WS}@markPrice"

        # 线程安全的数据存储
        self.lock = threading.Lock()
        self.data = {
            'kline': None,  # 最新K线
            'orderbook': None,  # 深度
            'funding_rate': 0.0,  # 资金费率
            'is_ready': False
        }
        self.running = True

    def run(self):
        while self.running:
            try:
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

                self.ws.run_forever(**proxy_opts)
            except Exception as e:
                print(f"{Fore.RED}[WS Error] {e} - Reconnecting in 5s...{Style.RESET_ALL}")
                time.sleep(5)

    def _on_open(self, ws):
        print(f"{Fore.GREEN}[WS] Connected to Binance Futures Stream{Style.RESET_ALL}")

    def _on_message(self, ws, message):
        try:
            msg = json.loads(message)
            stream = msg.get('stream')
            payload = msg.get('data')

            with self.lock:
                # 1. K线数据处理
                if 'kline' in stream:
                    k = payload['k']
                    # 转换成标准格式: [timestamp, open, high, low, close, volume]
                    self.data['kline'] = [
                        k['t'],  # Timestamp
                        float(k['o']),  # Open
                        float(k['h']),  # High
                        float(k['l']),  # Low
                        float(k['c']),  # Close
                        float(k['v'])  # Volume
                    ]

                # 2. 深度数据处理 (@depth20 推送的是全量快照，无需维护增量)
                elif 'depth20' in stream:
                    self.data['orderbook'] = {
                        'bids': [[float(p), float(v)] for p, v in payload['b']],
                        'asks': [[float(p), float(v)] for p, v in payload['a']]
                    }

                # 3. 资金费率
                elif 'markPrice' in stream:
                    if 'r' in payload:
                        self.data['funding_rate'] = float(payload['r'])

                if self.data['kline'] and self.data['orderbook']:
                    self.data['is_ready'] = True

        except Exception as e:
            pass  # 忽略单次解析错误

    def _on_error(self, ws, error):
        print(f"{Fore.YELLOW}[WS Error] {error}{Style.RESET_ALL}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"{Fore.YELLOW}[WS] Closed. Reconnecting...{Style.RESET_ALL}")

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

    def get_latest(self):
        """线程安全地获取最新数据"""
        with self.lock:
            return copy.deepcopy(self.data)


# ==========================================
# 3. 交易所服务类
# ==========================================
class ExchangeService:
    def __init__(self, is_live=False):
        self.is_live = is_live
        conf = {
            'enableRateLimit': True,
            'proxies': {'http': Config.PROXY_URL, 'https': Config.PROXY_URL},
            'options': {'defaultType': 'future'}
        }
        if is_live:
            conf.update({'apiKey': Config.API_KEY, 'secret': Config.API_SECRET})

        self.client = ccxt.binance(conf)
        self.symbol = Config.SYMBOL
        self.ws_streamer = MarketDataStreamer()

    def connect(self):
        try:
            self.client.load_markets()
            # 启动 WebSocket 线程
            self.ws_streamer.start()
            print(f"{Fore.CYAN}[System] Waiting for WS data stream...{Style.RESET_ALL}")

            # 等待 WebSocket 预热
            timeout = 0
            while not self.ws_streamer.data['is_ready']:
                time.sleep(1)
                timeout += 1
                if timeout > 20:
                    return False, "WS Connection Timeout"

            return True, "Connected & WS Stream Ready"
        except Exception as e:
            return False, str(e)

    def fetch_initial_history(self, limit=100):
        """只在启动时调用一次 REST API 获取历史 K 线"""
        try:
            ohlcv = self.client.fetch_ohlcv(self.symbol, Config.TIMEFRAME, limit=limit)
            return ohlcv
        except Exception as e:
            print(f"{Fore.RED}[History Fetch Error] {e}{Style.RESET_ALL}")
            return []

    def get_latest_data(self):
        """
        从 WebSocket 本地缓存读取数据
        返回: (最新K线列表, 订单簿, 资金费率)
        """
        data = self.ws_streamer.get_latest()
        current_candle = data['kline']
        book = data['orderbook']
        funding = data['funding_rate']
        return current_candle, book, funding

    def get_precision_amount(self, amount, price):
        return float(self.client.amount_to_precision(self.symbol, amount))

    def execute_order(self, side, amount, params={}):
        if not self.is_live: return True
        try:
            self.client.create_market_order(self.symbol, side, amount, params=params)
            return True
        except Exception as e:
            print(f"{Fore.RED}[Order Error] {e}{Style.RESET_ALL}")
            return False

    def close(self):
        self.ws_streamer.stop()