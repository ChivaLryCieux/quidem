import concurrent.futures
import json
import logging
import sys
import threading
import time

import redis
from colorama import init

from core.config.exchange import ExchangeService
from core.config.settings import Config
from core.config.mode import TradingMode, can_switch, parse_mode
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

    def __init__(self):
        Config.setup_proxy()
        self.ui = DisplayManager()
        self.key_listener = KeyListener()

        # 默认进入看盘模式（不交易）；模式可由 WebUI 运行时切换
        self.trading_mode = TradingMode.DASHBOARD
        self.is_live = False
        self.mode_name = self.trading_mode.label
        self._mode_lock = threading.Lock()
        logger.info(f"Initial Mode: {self.mode_name} (运行时可在 WebUI 切换)")

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
        self.exchange_connected = False

    def _validate_runtime_config(self):
        # 初始 DASHBOARD 模式不要求 API Key；切换到 LIVE 时由 switch_mode 校验
        issues = Config.validate_for_mode(is_live=self.is_live)
        if not issues:
            return

        for issue in issues:
            logger.error("Config validation failed: %s", issue)
        raise SystemExit("配置校验失败，请修正 .env 或 core/config/settings.py 后重试")

    async def handle_control(self, request):
        """WebUI 控制命令路由（由 /api/control 调用）"""
        action = request.action
        if action == "switch_mode":
            if not request.mode:
                raise ValueError("switch_mode 需要 mode 参数")
            return self.switch_mode(request.mode)
        elif action == "exit":
            self._exit_procedure()
            return "Exiting..."
        elif action in ("pause", "resume"):
            return f"Action {action} acknowledged (no-op)"
        else:
            raise ValueError(f"Unknown action: {action}")

    def switch_mode(self, target_mode_str):
        """切换交易模式（仅允许单向升级：DASHBOARD -> PAPER -> LIVE）

        切换到 LIVE 需校验 API Key；有持仓时禁止切换。
        成功返回 message 字符串；失败抛 ValueError（由 server.py 的 except 捕获）。
        """
        target = parse_mode(target_mode_str)

        with self._mode_lock:
            current = self.trading_mode

            # 1. 单向升级校验
            if not can_switch(current, target):
                msg = f"不允许降级或同级切换: {current.value} -> {target.value}"
                logger.warning(msg)
                raise ValueError(msg)

            # 2. 无持仓校验
            if self.trader.position['size'] != 0:
                msg = f"当前有持仓，禁止切换模式 (size={self.trader.position['size']})"
                logger.warning(msg)
                raise ValueError(msg)

            # 3. LIVE 模式校验 API Key
            if target == TradingMode.LIVE:
                issues = Config.validate_for_mode(is_live=True)
                if issues:
                    msg = f"实盘模式校验失败: {'; '.join(issues)}"
                    logger.error(msg)
                    raise ValueError(msg)

            # 4. 重建 ExchangeService 并重连
            old_exchange = self.exchange
            try:
                self.ui.log_msg(f"正在切换到 {target.label} 模式...", "info")

                new_is_live = (target == TradingMode.LIVE)
                self.exchange = ExchangeService(new_is_live)
                ok, err_msg = self.exchange.connect()
                if not ok:
                    # 回滚：恢复旧 exchange
                    self.exchange = old_exchange
                    msg = f"切换失败: 交易所重连失败 ({err_msg})"
                    logger.error(msg)
                    raise ValueError(msg)

                old_exchange.close()

                self.is_live = new_is_live
                self.trader.exchange = self.exchange
                self.trading_mode = target
                self.mode_name = target.label

                # 5. 更新余额与 Web 状态
                self._fetch_balance()
                self.web_state.set_trading_mode(target.value)
                self.web_state.update_account(
                    balance=self.trader.balance,
                    mode=target.value.capitalize(),
                    symbol=Config.SYMBOL,
                )

                self.ui.log_msg(f"✅ 已切换到 {target.label} 模式", "success")
                logger.info(f"Trading mode switched: {current.value} -> {target.value}")
                return f"已切换到 {target.label} 模式"
            except ValueError:
                # 校验类错误，直接向上抛
                self.exchange = old_exchange
                self.trader.exchange = old_exchange
                raise
            except Exception as exc:
                # 异常回滚
                self.exchange = old_exchange
                self.trader.exchange = old_exchange
                msg = f"切换模式异常: {exc}"
                logger.exception("switch_mode failed")
                raise ValueError(msg) from exc

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
        self.ui.log_startup()

        # 1. 先启动 Web 服务器（无论交易所连接是否成功）
        self._start_web_server()

        # 2. 尝试连接交易所
        ok, msg = self.exchange.connect()
        if not ok:
            self.ui.log_msg(f"Connection Failed: {msg}", "error")
            self.web_state.set_status("exchange_error")
            self.web_state.update_system(
                exchange_connected=False,
                error_message=msg,
            )
            self.ui.log_msg("Web GUI is still running. Press 'q' to exit.", "warning")

            # 即使交易所连接失败，也进入主循环（保持 Web GUI 运行）
            self._run_idle_loop()
            return

        # 交易所连接成功
        self.exchange_connected = True
        self.ui.log_msg("Exchange Connected", "success")
        self.web_state.update_system(exchange_connected=True)

        self._fetch_balance()
        self._warmup_models()

        self.ui.log_msg("System Started, Listening...", "success")
        self.web_state.set_status("running")

        # 正常主循环
        self._run_main_loop()

    def _run_idle_loop(self):
        """交易所连接失败时的空闲循环，保持 Web GUI 运行"""
        while True:
            try:
                self._check_user_input()
                time.sleep(0.5)  # 降低 CPU 占用
            except KeyboardInterrupt:
                self._exit_procedure()
            except Exception as exc:
                logger.error(f"Idle Loop Error: {exc}")
                time.sleep(1)

    def _run_main_loop(self):
        """正常交易主循环"""
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
                control_callback=self.handle_control,
            )
            self.web_runner.start()

            url = self.web_runner.get_url()
            self.ui.log_msg(f"Web GUI: {url}", "success")

            # 初始化 Web 状态
            self.web_state.update_account(
                balance=self.trader.balance,
                mode=self.trading_mode.value.capitalize(),
                symbol=Config.SYMBOL,
            )
            self.web_state.set_status("initializing")
            self.web_state.set_ws_connected(True)
            self.web_state.set_trading_mode(self.trading_mode.value)

        except Exception as exc:
            logger.error(f"Web server start failed: {exc}")
            self.ui.log_msg(f"Web GUI failed: {exc}", "error")

    def _fetch_balance(self):
        try:
            info = self.exchange.fetch_balance()
            if not info:
                self.ui.log_msg("Failed to fetch balance", "error")
                return

            mode_label = self.trading_mode.label
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

            if Config.WEB_ENABLED:
                history_list = self.brain.history_5m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
                self.web_state.update_market(kline_5m=history_list)
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
            if Config.WEB_ENABLED:
                history_list = self.brain.history_5m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
                self.web_state.update_market(kline_5m=history_list)
            return

        is_new_candle = timestamp > self.current_candle_timestamp
        if not is_new_candle:
            self._update_ui(curr_price, self.last_tick_analysis)
            return

        logger.info(f"[Candle Close] {self.current_candle_timestamp} -> {timestamp}")
        self.current_candle_timestamp = timestamp
        self._ingest_realtime_candles(c_5m, c_15m, c_1h, btc_chg)
        if Config.WEB_ENABLED:
            history_list = self.brain.history_5m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
            self.web_state.update_market(kline_5m=history_list)

        analysis = self.brain.analyze(book) if book else None
        # 仅在非看盘模式下尝试开仓；持仓管理（上方）对遗留持仓仍生效
        if (self.trading_mode != TradingMode.DASHBOARD
                and self.trader.position['size'] == 0
                and analysis):
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

        # 更新 Web 状态 (无论是否有策略分析结果，价格和余额都需要实时更新)
        self._update_web_state(price, analysis, unrealized)

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

    def _update_web_state(self, price, analysis, unrealized_pnl):
        """更新 Web 共享状态"""
        if not Config.WEB_ENABLED:
            return

        # 更新价格
        self.web_state.update_price(price)

        # 确保 analysis 至少是个字典，防止 None.get() 报错
        analysis_data = analysis or {}

        # 更新策略状态
        self.web_state.update_strategy(
            state=self.brain.state,
            color=self.brain.color,
            adx=analysis_data.get('adx', 0.0),
            macd=analysis_data.get('macd_histogram', 0.0),
            reversal=analysis_data.get('reversal_factor', 0.0),
            supertrend_5m=analysis_data.get('supertrend_direction', 0),
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
