import concurrent.futures
import json
import logging
import sys
import time

import redis
from colorama import init

from core.config.exchange import ExchangeService
from core.config.settings import Config
from core.engine.trader import TradeExecutor
from core.engine.alert_manager import AlertManager
from core.risk.manager import RiskManager
from core.strategy.brain import StrategyBrain
from core.ui.display import DisplayManager
from core.ui.input import KeyListener
from core.utils.logging_config import setup_logging
from core.web.state import WebState
from core.web.runner import WebRunner

init(autoreset=True)

setup_logging(
    log_level=Config.LOG_LEVEL,
    log_dir=Config.LOG_DIR,
    log_file=Config.LOG_FILE,
    console_output=Config.LOG_TO_CONSOLE,
    max_bytes=Config.LOG_MAX_BYTES,
    backup_count=Config.LOG_BACKUP_COUNT,
)

logger = logging.getLogger(__name__)


class QuantBot:
    WARMUP_TIMEOUT_SECONDS = 30
    LOOP_SLEEP_SECONDS = 0.05

    def __init__(self, mode_override=None):
        Config.setup_proxy()
        self.ui = DisplayManager()
        self.key_listener = KeyListener()

        self.mode = self._get_mode(mode_override)
        if self.mode == '0':
            sys.exit(0)

        self.is_live = self.mode == '2'
        self.mode_name = "实盘" if self.is_live else "模拟盘"
        logger.info(f"Mode Set: {self.mode_name}")
        self._validate_runtime_config()

        self.exchange = ExchangeService(self.is_live)
        self.brain = StrategyBrain()
        self.risk = RiskManager()
        self.trader = TradeExecutor(self.exchange, self.risk, self.ui, self.brain)
        self.alert_manager = AlertManager()

        self.redis_client = self._init_redis()

        # Web GUI
        self.web_state = WebState()
        self.web_runner = None

        # 将 WebState 注入到 trader 和 alert_manager
        self.trader.set_web_state(self.web_state)
        self.alert_manager.set_web_state(self.web_state)

        self.current_candle_timestamp = 0
        self.last_tick_analysis = None
        self.last_tick_price = 0.0
        self.last_btc_price = 0.0

    def _validate_runtime_config(self):
        issues = Config.validate_for_mode(is_live=self.is_live)
        if not issues:
            return

        for issue in issues:
            logger.error("Config validation failed: %s", issue)
        raise SystemExit("配置校验失败，请修正 .env 或 core/config/settings.py 后重试")

    def _get_mode(self, override):
        if override:
            return override

        logger.info("请选择模式: [0] 退出 | [1] 模拟盘 (Paper) | [2] 实盘 (Live)")
        try:
            sys.stdout.flush()
            print("请输入数字: ", end="", flush=True)
            choice = input().strip()
            if choice in ['0', '1', '2']:
                return choice
        except Exception:
            pass
        return '0'

    def _init_redis(self):
        if not Config.ENABLE_MAIL_REPORT:
            return None

        try:
            client = redis.Redis(**Config.redis_kwargs())
            client.ping()
            logger.info("Report Service Connected")
            self.trader.set_redis_client(client)
            return client
        except Exception as exc:
            logger.error(f"Report Service Connection Failed: {exc}")
            return None

    def run(self):
        self.ui.log_startup(self.mode_name)

        ok, msg = self.exchange.connect()
        if not ok:
            self.ui.log_msg(f"Connection Failed: {msg}", "error")
            return
        self.ui.log_msg("Exchange Connected", "success")

        self._fetch_balance()
        self._warmup_models()

        # 启动 Web 服务器
        self._start_web_server()

        self.ui.log_msg("System Started, Listening...", "success")
        self.web_state.set_status("running")

        while True:
            try:
                self._check_user_input()
                self._tick()
                time.sleep(self.LOOP_SLEEP_SECONDS)
            except KeyboardInterrupt:
                self._exit_procedure()
            except Exception as exc:
                logger.error(f"Loop Error: {exc}")
                time.sleep(1)

    def _start_web_server(self):
        """启动 Web 服务器"""
        if not Config.WEB_ENABLED:
            self.ui.log_msg("Web GUI disabled", "info")
            return

        try:
            self.web_runner = WebRunner(
                state=self.web_state,
                host=Config.WEB_HOST,
                port=Config.WEB_PORT,
                auto_open=Config.WEB_AUTO_OPEN,
            )
            self.web_runner.start()

            url = self.web_runner.get_url()
            self.ui.log_msg(f"Web GUI: {url}", "success")

            # 初始化 Web 状态
            self.web_state.update_account(
                balance=self.trader.balance,
                mode="Live" if self.is_live else "Paper",
                symbol=Config.SYMBOL,
            )
            self.web_state.set_ws_connected(True)

        except Exception as exc:
            logger.error(f"Web server start failed: {exc}")
            self.ui.log_msg(f"Web GUI failed: {exc}", "error")

    def _fetch_balance(self):
        try:
            info = self.exchange.fetch_balance()
            if not info:
                self.ui.log_msg("Failed to fetch balance", "error")
                return

            mode_label = "实盘" if self.is_live else "模拟盘"
            self.ui.log_msg(
                f"{mode_label} Balance: Free ${info['free']:.2f} | Total ${info['total']:.2f}",
                "success",
            )
            self.trader.update_balance(info['total'])
        except Exception as exc:
            self.ui.log_msg(f"Fetch Balance Failed: {exc}", "error")

    def _warmup_models(self):
        self.ui.log_msg("Warming up models...", "info")
        try:
            data = self._fetch_warmup_data()
            candles_5m = data.get('5m', [])
            candles_15m = data.get('15m', [])
            candles_1h = data.get('1h', [])

            if not (candles_5m and candles_15m and candles_1h):
                self.ui.log_msg("⚠️ Warmup Data Empty - Starting with minimal state", "warning")
                return

            self._ingest_warmup_candles(candles_5m, '5m', step=20)
            self._ingest_warmup_candles(candles_15m, '15m', step=10)
            self._ingest_warmup_candles(candles_1h, '1h', step=5)
            self.current_candle_timestamp = candles_5m[-1][0]
            self.ui.log_msg("✅ Warmup Complete", "success")
        except Exception as exc:
            self.ui.log_msg(f"❌ Warmup Error: {exc}", "error")
            logger.exception("Warmup traceback")

    def _fetch_warmup_data(self):
        self.ui.log_msg("Fetching historical data from exchange...", "info")

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(self.exchange.fetch_initial_history, 100)
            try:
                return future.result(timeout=self.WARMUP_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                self.ui.log_msg(
                    f"⚠️ Warmup timeout ({self.WARMUP_TIMEOUT_SECONDS}s). Continuing with empty data...",
                    "warning",
                )
                return {'5m': [], '15m': [], '1h': []}

    def _ingest_warmup_candles(self, candles, timeframe, step):
        self.ui.log_msg(f"Processing {len(candles)} {timeframe} candles...", "info")
        for index, candle in enumerate(candles, start=1):
            self.brain.ingest_candle(candle, timeframe)
            if index % step == 0:
                self.ui.log_msg(f"  Processed {index}/{len(candles)} {timeframe} candles", "info")

    def _tick(self):
        c_5m, c_15m, c_1h, book, fr, btc_price = self.exchange.get_latest_data()
        if not c_5m:
            return

        timestamp = c_5m[0]
        curr_price = float(c_5m[4])
        self.last_tick_price = curr_price

        btc_chg = self._calculate_btc_change(btc_price)

        if self.trader.position['size'] != 0:
            self.trader.tick(curr_price, fr, None, timestamp)

        if self.current_candle_timestamp == 0:
            self.current_candle_timestamp = timestamp
            self._ingest_realtime_candles(c_5m, c_15m, c_1h, btc_chg)
            return

        is_new_candle = timestamp > self.current_candle_timestamp
        if not is_new_candle:
            self._update_ui(curr_price, self.last_tick_analysis)
            return

        logger.info(f"[Candle Close] {self.current_candle_timestamp} -> {timestamp}")
        self.current_candle_timestamp = timestamp
        self._ingest_realtime_candles(c_5m, c_15m, c_1h, btc_chg)

        analysis = self.brain.analyze(book) if book else None
        if self.trader.position['size'] == 0 and analysis:
            self.trader.tick(curr_price, fr, analysis, timestamp)

        self._update_ui(curr_price, analysis)
        self.alert_manager.check_and_alert(self.brain.history_5m, analysis)
        self._send_heartbeat(curr_price, analysis)
        if analysis:
            self.last_tick_analysis = analysis

    def _calculate_btc_change(self, btc_price):
        if self.last_btc_price == 0:
            self.last_btc_price = btc_price
            return 0.0

        btc_change = (btc_price - self.last_btc_price) / self.last_btc_price if self.last_btc_price > 0 else 0.0
        self.last_btc_price = btc_price
        return btc_change

    def _ingest_realtime_candles(self, c_5m, c_15m, c_1h, btc_chg):
        if c_15m:
            self.brain.ingest_candle(c_15m, '15m', btc_change_pct=btc_chg)
        if c_1h:
            self.brain.ingest_candle(c_1h, '1h', btc_change_pct=btc_chg)
        self.brain.ingest_candle(c_5m, '5m', btc_change_pct=btc_chg)

    def _update_ui(self, price, analysis):
        pos = self.trader.position
        unrealized = (price - pos['entry_price']) * pos['size'] if pos['size'] != 0 else 0

        if not analysis:
            return

        self.ui.update_status(
            pos['size'],
            self.brain.state,
            self.brain.color,
            unrealized,
            price,
            macd=analysis.get('macd_histogram', 0.0),
            adx=analysis.get('adx', 0.0),
            reversal=analysis.get('reversal_factor', 0.0),
        )

        # 更新 Web 状态
        self._update_web_state(price, analysis, unrealized)

    def _update_web_state(self, price, analysis, unrealized_pnl):
        """更新 Web 共享状态"""
        if not Config.WEB_ENABLED:
            return

        # 更新价格
        self.web_state.update_price(price)

        # 更新策略状态
        self.web_state.update_strategy(
            state=self.brain.state,
            color=self.brain.color,
            adx=analysis.get('adx', 0.0),
            macd=analysis.get('macd_histogram', 0.0),
            reversal=analysis.get('reversal_factor', 0.0),
            supertrend_5m=analysis.get('supertrend_direction', 0),
            supertrend_15m=self.brain.signal_engine.supertrend_15m_direction,
            supertrend_1h=self.brain.signal_engine.supertrend_1h_direction,
        )

        # 更新持仓
        self.web_state.update_position(self.trader.position, unrealized_pnl)

        # 更新余额
        self.web_state.update_balance(self.trader.balance)

    def _send_heartbeat(self, price, analysis):
        if not (Config.ENABLE_MAIL_REPORT and self.redis_client):
            return

        try:
            change_24h = self._calculate_change_24h(price)
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

    def _calculate_change_24h(self, price):
        hist = self.brain.history_5m
        if len(hist) >= 288:
            price_24h_ago = float(hist.iloc[-288]['close'])
            return (price - price_24h_ago) / price_24h_ago * 100
        if len(hist) > 1:
            price_first = float(hist.iloc[0]['close'])
            return (price - price_first) / price_first * 100
        return 0.0

    def _check_user_input(self):
        if self.key_listener.is_q_pressed():
            logger.warning("=== PAUSED === [0] Exit | [Enter] Continue")
            command = self.key_listener.safe_input("Cmd > ").strip()
            if command == '0':
                self._exit_procedure()

    def _exit_procedure(self):
        logger.info("Stopping...")
        self.web_state.set_status("stopping")

        # 停止 Web 服务器
        if self.web_runner:
            self.web_runner.stop()

        self.exchange.close()

        if self.trader.position['size'] != 0:
            price = self.last_tick_price if self.last_tick_price > 0 else self.trader.position['entry_price']
            self.trader.execute_exit("Manual Exit", price)

        sys.exit(0)
