import json
import logging
import sys
import threading
import concurrent.futures
import time
from datetime import datetime, timezone, timedelta

import ccxt
import requests
import websocket
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
        
        # 提取基础 WS 域名并拼接 streams 参数
        base_ws_url = Config.BINANCE_WS_URL
        if "?" in base_ws_url:
            base_ws_url = base_ws_url.split("?")[0]

        self.url = (
            f"{base_ws_url}?streams="
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
                if Config.PROXY_ENABLED and Config.PROXY_HOST and Config.PROXY_PORT:
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
                logger.warning("WS Disconnected. Reconnecting in %.1fs...", Config.WS_RECONNECT_DELAY_SEC)
                time.sleep(Config.WS_RECONNECT_DELAY_SEC)

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


class DomesticDataStreamer(threading.Thread):
    def __init__(self, symbol):
        super().__init__()
        self.daemon = True
        self.symbol = symbol.lower()
        self.lock = threading.Lock()
        self.running = True
        self.data = {
            'kline_5m': None,
            'kline_15m': None,
            'kline_1h': None,
            'orderbook': None,
            'funding_rate': 0.0,
            'btc_price': 0.0,
            'is_ready': False
        }

    def run(self):
        logger.info(f"Starting DomesticDataStreamer for {self.symbol}...")
        headers = {"Referer": "https://finance.sina.com.cn/"}
        url = f"http://hq.sinajs.cn/list={self.symbol}"
        
        while self.running:
            try:
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    text = resp.content.decode('gbk')
                    if '"' in text:
                        data_str = text.split('"')[1]
                        if data_str.strip():
                            parts = data_str.split(',')
                            if len(parts) >= 32:
                                curr_price = float(parts[3])
                                open_price = float(parts[1]) if float(parts[1]) > 0 else curr_price
                                high_price = float(parts[4]) if float(parts[4]) > 0 else curr_price
                                low_price = float(parts[5]) if float(parts[5]) > 0 else curr_price
                                volume = float(parts[8])
                                date_str = parts[30]
                                time_str = parts[31]
                                
                                tz_bj = timezone(timedelta(hours=8))
                                dt_str = f"{date_str} {time_str}"
                                try:
                                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_bj)
                                except ValueError:
                                    dt = datetime.now(tz_bj)
                                    
                                timestamp_ms = int(dt.timestamp() * 1000)
                                
                                bids = []
                                asks = []
                                for i in range(5):
                                    vol_idx = 10 + i * 2
                                    prc_idx = 11 + i * 2
                                    if float(parts[prc_idx]) > 0:
                                        bids.append([float(parts[prc_idx]), float(parts[vol_idx]) / 100.0])
                                for i in range(5):
                                    vol_idx = 20 + i * 2
                                    prc_idx = 21 + i * 2
                                    if float(parts[prc_idx]) > 0:
                                        asks.append([float(parts[prc_idx]), float(parts[vol_idx]) / 100.0])
                                        
                                orderbook = {
                                    "bids": bids,
                                    "asks": asks
                                }
                                
                                def get_kline_candle(tf_sec):
                                    candle_ts_ms = (timestamp_ms // (tf_sec * 1000)) * (tf_sec * 1000)
                                    return [
                                        candle_ts_ms,
                                        open_price,
                                        high_price,
                                        low_price,
                                        curr_price,
                                        volume,
                                        volume * 0.5
                                    ]
                                    
                                with self.lock:
                                    self.data['orderbook'] = orderbook
                                    self.data['kline_5m'] = get_kline_candle(300)
                                    self.data['kline_15m'] = get_kline_candle(900)
                                    self.data['kline_1h'] = get_kline_candle(3600)
                                    self.data['is_ready'] = True
            except Exception as e:
                logger.error(f"Domestic polling error: {e}")
            time.sleep(2.0)

    def stop(self):
        self.running = False

    def get_latest(self):
        with self.lock:
            return self.data.copy()


class ExchangeService:
    def __init__(self, is_live=False):
        self.is_live = is_live
        self.paper_orders = []
        self.symbol = Config.SYMBOL
        self.is_domestic = self.symbol.lower().startswith(('sh', 'sz'))
        self.is_rest_only = Config.BINANCE_REST_ONLY
        self.api_lock = threading.Lock()

        if self.is_domestic:
            logger.info(f"Initialized domestic ExchangeService for A-shares: {self.symbol}")
            self.client = None
            self.ws_streamer = DomesticDataStreamer(self.symbol)
            return

        # 增加 timeout 防止网络卡死
        conf = {
            'enableRateLimit': True,
            'timeout': Config.HTTP_TIMEOUT_MS,
            'proxies': Config.exchange_proxies(),
            'options': {'defaultType': 'future'}
        }

        if is_live:
            if not Config.API_KEY or not Config.API_SECRET:
                logger.error("Live mode selected but API credentials missing!")
                # 不抛出异常，允许程序继续运行(只读)，但在下单时会失败
            else:
                logger.info("API credentials found, configuring exchange client")
            conf.update({'apiKey': Config.API_KEY, 'secret': Config.API_SECRET})

        self.client = ccxt.binance(conf)
        # 覆盖 CCXT 终结点以支持直连镜像
        if Config.BINANCE_REST_URL:
            self.client.urls['api']['fapi'] = Config.BINANCE_REST_URL
            
        if self.is_rest_only:
            logger.info("REST-only mode enabled for Binance. WS connections will be disabled.")
            self.ws_streamer = None
            self._cached_latest = {
                'kline_5m': None,
                'kline_15m': None,
                'kline_1h': None,
                'orderbook': None,
                'funding_rate': 0.0,
                'btc_price': 0.0,
                'is_ready': False
            }
            # 开启后台轮询线程
            self.polling_thread = threading.Thread(target=self._poll_rest_data, daemon=True)
        else:
            self.ws_streamer = MarketDataStreamer()

    def connect(self):
        if self.is_domestic:
            try:
                logger.info(f"Connecting to domestic data feeds for {self.symbol}...")
                self.ws_streamer.start()
                start_time = time.time()
                while time.time() - start_time < 10:
                    if self.ws_streamer.get_latest().get('is_ready'):
                        logger.info("✅ Domestic data feed ready")
                        return True, "Domestic Feed Ready"
                    time.sleep(0.5)
                return True, "Domestic Feed Started (timeout waiting for first tick)"
            except Exception as e:
                logger.error(f"❌ Domestic connection failed: {e}")
                return False, f"Domestic connection failed: {e}"

        if self.is_rest_only:
            try:
                logger.info("="*50)
                logger.info("Initializing REST API connection (REST-only mode)...")
                sys.stdout.flush()
                with self.api_lock:
                    self.client.load_markets()
                logger.info("✅ REST API connected successfully")
                sys.stdout.flush()
                
                # 初始化缓存数据
                self._update_rest_data()
                
                # 启动后台轮询线程
                self.polling_thread.start()
                logger.info("✅ REST polling thread started")
                logger.info("="*50)
                sys.stdout.flush()
                return True, "Connected & REST Polling Started"
            except Exception as e:
                logger.error(f"❌ Connection Failed: {str(e)}")
                sys.stdout.flush()
                return False, f"Connection Failed: {str(e)}"

        try:
            logger.info("="*50)
            logger.info("Initializing REST API connection...")
            sys.stdout.flush()
            
            with self.api_lock:
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
            max_timeout = Config.WS_READY_TIMEOUT_SEC
            
            while not self.ws_streamer.data['is_ready']:
                time.sleep(1)
                timeout += 1
                
                # 每秒打印进度
                logger.info(f"  Waiting for WS data... {timeout}s / {max_timeout}s")
                sys.stdout.flush()
                
                if timeout >= max_timeout:
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
            logger.error(traceback.format_exc())
            sys.stdout.flush()
            return False, f"Connection Failed: {str(e)}"

    def fetch_initial_history(self, limit=100):
        if self.is_domestic:
            try:
                def fetch_sina(scale, lim):
                    try:
                        return self._fetch_domestic_history(scale, lim)
                    except Exception:
                        return []
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    f_5m = executor.submit(fetch_sina, '5', limit)
                    f_15m = executor.submit(fetch_sina, '15', limit)
                    f_1h = executor.submit(fetch_sina, '60', max(50, limit // 2))
                    f_1d = executor.submit(fetch_sina, '240', 50)
                    
                    ohlcv_5m = f_5m.result()
                    ohlcv_15m = f_15m.result()
                    ohlcv_1h = f_1h.result()
                    ohlcv_1d = f_1d.result()
                return {'5m': ohlcv_5m, '15m': ohlcv_15m, '1h': ohlcv_1h, '1d': ohlcv_1d}
            except Exception as e:
                logger.error(f"Domestic history fetch failed: {e}")
                return {'5m': [], '15m': [], '1h': [], '1d': []}

        """只在启动时调用一次 REST API 获取历史 K 线"""
        # 创建独立的临时客户端以支持并行拉取，避免与轮询线程争抢 API 锁
        conf = {
            'enableRateLimit': True,
            'timeout': Config.HTTP_TIMEOUT_MS,
            'proxies': Config.exchange_proxies(),
            'options': {'defaultType': 'future'}
        }
        if self.is_live:
            conf.update({'apiKey': Config.API_KEY, 'secret': Config.API_SECRET})
        
        temp_client = ccxt.binance(conf)
        if Config.BINANCE_REST_URL:
            temp_client.urls['api']['fapi'] = Config.BINANCE_REST_URL

        def fetch_one(tf, lim):
            try:
                return temp_client.fetch_ohlcv(self.symbol, tf, limit=lim)
            except Exception as ex:
                logger.error(f"[History Fetch One Error] {self.symbol} {tf}: {ex}")
                return []

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                f_5m = executor.submit(fetch_one, '5m', limit)
                f_15m = executor.submit(fetch_one, '15m', limit)
                f_1h = executor.submit(fetch_one, '1h', max(50, limit // 2))
                f_1d = executor.submit(fetch_one, '1d', 50)
                
                ohlcv_5m = f_5m.result()
                ohlcv_15m = f_15m.result()
                ohlcv_1h = f_1h.result()
                ohlcv_1d = f_1d.result()
            
            try:
                temp_client.close()
            except Exception:
                pass
            return {'5m': ohlcv_5m, '15m': ohlcv_15m, '1h': ohlcv_1h, '1d': ohlcv_1d}
        except Exception as e:
            logger.error(f"[History Fetch Error] {e}")
            try:
                temp_client.close()
            except Exception:
                pass
            return {'5m': [], '15m': [], '1h': [], '1d': []}

    def _fetch_domestic_history(self, scale, limit):
        url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={self.symbol}&scale={scale}&ma=no&datalen={limit}"
        headers = {"Referer": "https://finance.sina.com.cn/"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []
            
        tz_bj = timezone(timedelta(hours=8))
        ohlcv = []
        for item in data:
            dt_str = item['day']
            try:
                if len(dt_str) == 10:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=tz_bj)
                else:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_bj)
            except ValueError:
                continue
                
            ts = int(dt.timestamp() * 1000)
            ohlcv.append([
                ts,
                float(item['open']),
                float(item['high']),
                float(item['low']),
                float(item['close']),
                float(item['volume'])
            ])
        return ohlcv

    def _poll_rest_data(self):
        logger.info("Starting REST-only polling loop...")
        while True:
            try:
                self._update_rest_data()
            except Exception as e:
                logger.error(f"REST Polling error: {e}")
            time.sleep(5.0)

    def _update_rest_data(self):
        if self.client is None:
            return
            
        # 1. 获取最新价格与盘口
        try:
            with self.api_lock:
                ticker = self.client.fetch_ticker(self.symbol)
                book_data = self.client.fetch_order_book(self.symbol, limit=5)
            curr_price = float(ticker['last'])
            orderbook = {
                'bids': [[float(p), float(v)] for p, v in book_data['bids']],
                'asks': [[float(p), float(v)] for p, v in book_data['asks']]
            }
        except Exception:
            # 兼容处理单项请求失败
            try:
                with self.api_lock:
                    ticker = self.client.fetch_ticker(self.symbol)
                curr_price = float(ticker['last'])
            except Exception:
                curr_price = 0.0
            orderbook = None
            
        # 3. 构造 5m, 15m, 1h 的最新单个蜡烛
        timestamp_ms = int(time.time() * 1000)
        def get_kline_candle(tf_sec):
            candle_ts_ms = (timestamp_ms // (tf_sec * 1000)) * (tf_sec * 1000)
            return [
                candle_ts_ms,
                curr_price, # open
                curr_price, # high
                curr_price, # low
                curr_price, # close
                float(ticker.get('baseVolume', 0.0) or 0.0),
                float(ticker.get('baseVolume', 0.0) or 0.0) * 0.5
            ]
            
        funding_rate = 0.0
        if 'info' in ticker and ticker['info']:
            try:
                funding_rate = float(ticker['info'].get('lastFundingRate', 0.0))
            except (ValueError, TypeError):
                pass

        self._cached_latest.update({
            'kline_5m': get_kline_candle(300),
            'kline_15m': get_kline_candle(900),
            'kline_1h': get_kline_candle(3600),
            'orderbook': orderbook,
            'funding_rate': funding_rate,
            'btc_price': curr_price if self.symbol.startswith('BTC') else 0.0,
            'is_ready': True
        })

    def get_latest_data(self):
        """
        从 WebSocket 本地缓存或 REST 缓存读取数据
        返回: (最新5m K线列表, 最新15m K线列表, 最新1h K线列表, 订单簿, 资金费率, BTC价格)
        """
        if self.is_domestic:
            data = self.ws_streamer.get_latest()
        elif self.is_rest_only:
            data = self._cached_latest.copy()
        else:
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
        if self.client is None:
            return amount
        try:
            with self.api_lock:
                return float(self.client.amount_to_precision(self.symbol, amount))
        except Exception as e:
            logger.error(f"Precision Error: {e}")
            return amount

    def execute_order(self, side, amount, params=None):
        params = params or {}
        if not self.is_live:
            order = {
                "timestamp": int(time.time() * 1000),
                "symbol": self.symbol,
                "side": side,
                "amount": amount,
                "params": params.copy(),
            }
            self.paper_orders.append(order)
            logger.info(f"[PAPER] Order {side} {amount} {params}")
            return True

        try:
            # 记录下单请求，方便调试
            logger.info(f"[LIVE EXEC] {side.upper()} {amount} | Params: {params}")

            # create_market_order 是同步阻塞的，timeout 由 ccxt 配置控制
            with self.api_lock:
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
        if not self.is_live or self.client is None:
            # 模拟盘或国内直连返回默认余额
            return {
                'free': Config.PAPER_BALANCE,
                'used': 0.0,
                'total': Config.PAPER_BALANCE
            }
            
        try:
            with self.api_lock:
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
        if self.ws_streamer:
            self.ws_streamer.stop()
        try:
            # 部分 CCXT 版本支持 close
            if self.client and hasattr(self.client, 'close'):
                with self.api_lock:
                    self.client.close()
        except Exception:
            pass
