
import sys
import time
import redis
import json
import logging
from colorama import init

from core.config.settings import Config
from core.config.exchange import ExchangeService
from core.strategy.brain import StrategyBrain
from core.risk.manager import RiskManager
from core.ui.display import DisplayManager
from core.ui.input import KeyListener
from core.utils.logging_config import setup_logging
from core.engine.trader import TradeExecutor

init(autoreset=True)

# Configure Logging
setup_logging(
    log_level=Config.LOG_LEVEL,
    log_dir=Config.LOG_DIR,
    log_file=Config.LOG_FILE,
    console_output=Config.LOG_TO_CONSOLE,
    max_bytes=Config.LOG_MAX_BYTES,
    backup_count=Config.LOG_BACKUP_COUNT
)

logger = logging.getLogger(__name__)

class QuantBot:
    def __init__(self, mode_override=None):
        Config.setup_proxy()
        self.ui = DisplayManager()
        self.key_listener = KeyListener()

        # Mode Selection
        self.mode = self._get_mode(mode_override)
        if self.mode == '0': sys.exit(0)
        
        self.is_live = (self.mode == '2')
        self.mode_name = "实盘" if self.is_live else "模拟盘"
        logger.info(f"Mode Set: {self.mode_name}")

        # Initialize Services
        self.exchange = ExchangeService(self.is_live)
        self.brain = StrategyBrain()
        self.risk = RiskManager()
        
        # Initialize Trader
        self.trader = TradeExecutor(self.exchange, self.risk, self.ui, self.brain)

        # Initialize Redis for Reporting
        self._init_redis()
        
        # State Variables
        self.current_candle_timestamp = 0
        self.last_tick_analysis = None
        self.last_tick_price = 0.0
        self.last_btc_price = 0.0

    def _get_mode(self, override):
        if override: return override
        
        logger.info(f"请选择模式: [0] 退出 | [1] 模拟盘 (Paper) | [2] 实盘 (Live)")
        try:
            sys.stdout.flush()
            print("请输入数字: ", end="", flush=True)
            choice = input().strip()
            if choice in ['0', '1', '2']: return choice
        except Exception:
            pass
        return '0'

    def _init_redis(self):
        self.redis_client = None
        if Config.ENABLE_MAIL_REPORT:
            try:
                self.redis_client = redis.Redis(host='localhost', port=6379, db=0, socket_timeout=1)
                self.redis_client.ping()
                logger.info("Report Service Connected")
                self.trader.set_redis_client(self.redis_client)
            except Exception as e:
                logger.error(f"Report Service Connection Failed: {e}")

    def run(self):
        self.ui.log_startup(self.mode_name)

        # Connect Exchange
        ok, msg = self.exchange.connect()
        if not ok:
            self.ui.log_msg(f"Connection Failed: {msg}", "error")
            return
        self.ui.log_msg("Exchange Connected", "success")

        # Fetch Balance (both live and paper)
        self._fetch_balance()

        # Warmup
        self._warmup_models()
        self.ui.log_msg("System Started, Listening...", "success")

        # Main Loop
        while True:
            try:
                self._check_user_input()
                self._tick()
                time.sleep(0.05)
            except KeyboardInterrupt:
                self._exit_procedure()
            except Exception as e:
                logger.error(f"Loop Error: {e}")
                time.sleep(1)

    def _fetch_balance(self):
        try:
            info = self.exchange.fetch_balance()
            if info:
                mode_label = "实盘" if self.is_live else "模拟盘"
                self.ui.log_msg(f"{mode_label} Balance: Free ${info['free']:.2f} | Total ${info['total']:.2f}", "success")
                self.trader.update_balance(info['total'])
            else:
                self.ui.log_msg("Failed to fetch balance", "error")
        except Exception as e:
            self.ui.log_msg(f"Fetch Balance Failed: {e}", "error")

    def _warmup_models(self):
        self.ui.log_msg("Warming up models...", "info")
        try:
            self.ui.log_msg("Fetching historical data from exchange...", "info")
            
            import concurrent.futures
            
            def fetch_with_timeout():
                return self.exchange.fetch_initial_history(limit=100)
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(fetch_with_timeout)
                try:
                    data = future.result(timeout=30)
                except concurrent.futures.TimeoutError:
                    self.ui.log_msg("⚠️ Warmup timeout (30s). Continuing with empty data...", "warning")
                    data = {'5m': [], '15m': []}
            
            candles_5m = data.get('5m', [])
            candles_15m = data.get('15m', [])

            if candles_5m and candles_15m:
                self.ui.log_msg(f"Processing {len(candles_5m)} 5m candles...", "info")
                for i, candle in enumerate(candles_5m):
                    self.brain.ingest_candle(candle, '5m')
                    if (i + 1) % 20 == 0:
                        self.ui.log_msg(f"  Processed {i + 1}/{len(candles_5m)} 5m candles", "info")

                self.ui.log_msg(f"Processing {len(candles_15m)} 15m candles...", "info")
                for i, candle in enumerate(candles_15m):
                    self.brain.ingest_candle(candle, '15m')
                    if (i + 1) % 10 == 0:
                        self.ui.log_msg(f"  Processed {i + 1}/{len(candles_15m)} 15m candles", "info")

                self.current_candle_timestamp = candles_5m[-1][0]
                self.ui.log_msg("✅ Warmup Complete", "success")
            else:
                self.ui.log_msg("⚠️ Warmup Data Empty - Starting with minimal state", "warning")
        except Exception as e:
            self.ui.log_msg(f"❌ Warmup Error: {e}", "error")
            import traceback
            logger.error(f"Warmup traceback: {traceback.format_exc()}")

    def _tick(self):
        # 1. Get Data (5m + 15m)
        c_5m, c_15m, book, fr, btc_price = self.exchange.get_latest_data()
        if not c_5m: return

        timestamp = c_5m[0]
        curr_price = float(c_5m[4])
        self.last_tick_price = curr_price

        # 2. BTC Correlation
        if self.last_btc_price == 0: self.last_btc_price = btc_price
        btc_chg = (btc_price - self.last_btc_price) / self.last_btc_price if self.last_btc_price > 0 else 0.0
        self.last_btc_price = btc_price

        # 4. Ingest to Brain (5m for signals, 15m for trend filter)
        if self.current_candle_timestamp != 0 and timestamp > self.current_candle_timestamp:
            logger.info(f"[Candle Close] {self.current_candle_timestamp} -> {timestamp}")
            self.current_candle_timestamp = timestamp

        # Ingest 15m for trend filtering
        if c_15m:
            self.brain.ingest_candle(c_15m, '15m', btc_change_pct=btc_chg)
        
        # Ingest 5m for signal generation
        self.brain.ingest_candle(c_5m, '5m', btc_change_pct=btc_chg)

        # 5. Analyze
        analysis = self.brain.analyze(book) if book else None
        
        # 6. Trade Execution (Delegated)
        self.trader.tick(curr_price, fr, analysis, timestamp)

        # 7. UI Update
        self._update_ui(curr_price, analysis)

        # 8. Heartbeat
        self._send_heartbeat(curr_price, analysis)

        # 9. Cache State
        if analysis:
            self.last_tick_analysis = analysis

    def _update_ui(self, price, analysis):
        pos = self.trader.position
        unrealized = (price - pos['entry_price']) * pos['size'] if pos['size'] != 0 else 0
        
        # Update UI with MACD, BB distance, SuperTrend
        if analysis:
            macd_hist = analysis.get('macd_histogram', 0.0)
            bb_dist = analysis.get('bb_distance', 0.0)
            st_val = analysis.get('supertrend_value', 0.0)
            self.ui.update_status(
                pos['size'], self.brain.state, self.brain.color,
                unrealized, price,
                macd=macd_hist, bb_dist=bb_dist, st_val=st_val
            )

    def _send_heartbeat(self, price, analysis):
        if not (Config.ENABLE_MAIL_REPORT and self.redis_client): return
        try:
            # 计算24h涨跌幅 (从5m历史中取288根前的价格)
            change_24h = 0.0
            hist = self.brain.history_5m
            if len(hist) >= 288:
                price_24h_ago = float(hist.iloc[-288]['close'])
                change_24h = (price - price_24h_ago) / price_24h_ago * 100
            elif len(hist) > 1:
                price_first = float(hist.iloc[0]['close'])
                change_24h = (price - price_first) / price_first * 100
            
            data = {
                "timestamp": int(time.time() * 1000),
                "balance": self.trader.balance,
                "position_size": self.trader.position['size'],
                "price": price,
                "regime": self.brain.state,
                "change_24h": round(change_24h, 2),
            }
            self.redis_client.set('bot_status_heartbeat', json.dumps(data), ex=10)
        except Exception:
            pass

    def _check_user_input(self):
        if self.key_listener.is_q_pressed():
            logger.warning("=== PAUSED === [0] Exit | [Enter] Continue")
            c = self.key_listener.safe_input("Cmd > ").strip()
            if c == '0': self._exit_procedure()

    def _exit_procedure(self):
        logger.info("Stopping...")
        self.exchange.close()
        
        # Close positions if any
        if self.trader.position['size'] != 0:
            price = self.last_tick_price if self.last_tick_price > 0 else self.trader.position['entry_price']
            self.trader.execute_exit("Manual Exit", price)

        sys.exit(0)
