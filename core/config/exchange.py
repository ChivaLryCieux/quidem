import os
import time
import json
import copy
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
        # 订阅1m和15m K线，以及深度和标记价格
        self.url = f"wss://fstream.binance.com/stream?streams={Config.SYMBOL_WS}@kline_{Config.TIMEFRAME}/{Config.SYMBOL_WS}@kline_15m/{Config.SYMBOL_WS}@depth20@100ms/{Config.SYMBOL_WS}@markPrice/btcusdt@kline_1m"

        # 线程安全的数据存储
        self.lock = threading.Lock()
        self.data = {
            'kline_1m': None,  # 1分钟K线
            'kline_15m': None,  # 15分钟K线
            'orderbook': None,  # 深度
            'funding_rate': 0.0,  # 资金费率
            'btc_price':0.0,    #BTC实时价格
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
                logger.error(f"WS Error: {e} - Reconnecting in 5s...")
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
                    kline_data = [
                        k['t'], float(k['o']), float(k['h']), float(k['l']),
                        float(k['c']), float(k['v']), float(k['Q'])
                    ]

                    if 'btcusdt' in stream:
                        self.data['btc_price'] = float(k['c'])

                    elif 'kline_1m' in stream:
                        self.data['kline_1m'] = kline_data

                    elif 'kline_15m' in stream:
                        self.data['kline_15m'] = kline_data

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

                # 检查数据是否准备就绪
                if self.data['kline_1m'] and self.data['orderbook']:
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
            logger.info("Waiting for WS data stream...")

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
            # 获取1分钟K线历史数据
            ohlcv_1m = self.client.fetch_ohlcv(self.symbol, Config.TIMEFRAME, limit=limit)
            # 获取15分钟K线历史数据
            ohlcv_15m = self.client.fetch_ohlcv(self.symbol, '15m', limit=limit)
            return {'1m': ohlcv_1m, '15m': ohlcv_15m}
        except Exception as e:
            print(f"{Fore.RED}[History Fetch Error] {e}{Style.RESET_ALL}")
            return {'1m': [], '15m': []}

    def get_latest_data(self):
        """
        从 WebSocket 本地缓存读取数据
        返回: (最新1m K线列表, 最新15m K线列表, 订单簿, 资金费率)
        """
        data = self.ws_streamer.get_latest()
        kline_1m = data['kline_1m']
        kline_15m = data['kline_15m']
        book = data['orderbook']
        funding = data['funding_rate']
        btc_price = data.get('btc_price', 0.0)
        return kline_1m, kline_15m, book, funding, btc_price

    def get_precision_amount(self, amount, price):
        return float(self.client.amount_to_precision(self.symbol, amount))

    def execute_order(self, side, amount, params={}):
        if not self.is_live: return True
        try:
            self.client.create_market_order(self.symbol, side, amount, params=params)
            return True
        except Exception as e:
            logger.error(f"Order Error: {e}")
            return False

    def close(self):
        self.ws_streamer.stop()