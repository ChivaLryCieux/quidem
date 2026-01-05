import sys
import os
import time
import redis
import json
import logging
from colorama import init, Fore, Style

from core.config.settings import Config
from core.config.exchange import ExchangeService
from core.strategy.brain import StrategyBrain
from core.risk.manager import RiskManager
from core.ui.display import DisplayManager
from core.ui.input import KeyListener
from core.utils.logging_config import setup_logging

init(autoreset=True)

# 配置日志系统
setup_logging(
    log_level=Config.LOG_LEVEL,
    log_dir=Config.LOG_DIR,
    log_file=Config.LOG_FILE,
    console_output=Config.LOG_TO_CONSOLE,
    max_bytes=Config.LOG_MAX_BYTES,
    backup_count=Config.LOG_BACKUP_COUNT
)

logger = logging.getLogger(__name__)


# ==========================================
# 机器人主引擎 (Trading Bot Engine)
# ==========================================
class QuantBot:
    def __init__(self):
        Config.setup_proxy()
        self.ui = DisplayManager()
        self.key_listener = KeyListener()

        # 用户选择模式
        logger.info(f"请选择模式: [0] 退出 | [1] 模拟盘 (Paper) | [2] 实盘 (Live)")
        mode = input("请输入数字: ").strip()
        if mode == '0': sys.exit(0)
        self.is_live = (mode == '2')
        self.mode_name = "实盘" if self.is_live else "模拟盘"

        # 初始化服务
        self.exchange = ExchangeService(self.is_live)
        self.brain = StrategyBrain()
        self.risk = RiskManager()

        # 初始化邮件转发功能 (Redis)
        self.redis_client = None
        self.trade_snapshots = []
        self.last_snapshot_time = 0

        if Config.ENABLE_MAIL_REPORT:
            try:
                self.redis_client = redis.Redis(host='localhost', port=6379, db=0)
                self.redis_client.ping()
                logger.info("邮件服务已连接")
            except Exception as e:
                logger.error(f"邮件服务连接失败 {e}")
                self.redis_client = None

        # 交易状态
        self.balance = 100.0
        self.position = {'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 'entry_time': 0}

        self.profit_flip_count = 0
        self.was_in_profit = False

        # === 初始化时间戳与分析缓存 ===
        self.current_candle_timestamp = 0
        self.last_tick_analysis = None
        self.last_tick_price = 0.0
        self.last_btc_price = 0.0
        # 15分钟开仓检查时间戳 - 每15分钟才检查一次开仓机会
        self.last_position_check_timestamp = 0

    def run(self):
        self.ui.log_startup(self.mode_name)

        # 连接交易所，启动WS
        ok, msg = self.exchange.connect()
        if not ok:
            self.ui.log_msg(f"连接失败: {msg}", "error")
            return
        self.ui.log_msg("交易所及WebSocket连接成功", "success")

        # 预热: 使用 REST API 拉取历史数据
        self.ui.log_msg("正在获取历史数据预热模型...", "info")
        initial_data = self.exchange.fetch_initial_history(limit=100)
        initial_ohlcv_1m = initial_data['1m']
        initial_ohlcv_15m = initial_data['15m']

        if initial_ohlcv_1m and initial_ohlcv_15m:
            # 处理1分钟数据
            for candle in initial_ohlcv_1m:
                self.brain.ingest_candle(candle, '1m')
                # 简单预热训练
                res = self.brain.analyze()
                if res:
                    price_diff = float(candle[4]) - float(candle[1])
                    label = 0
                    if price_diff > Config.MIN_TP_DISTANCE * 0.2:
                        label = 1
                    elif price_diff < -Config.MIN_TP_DISTANCE * 0.2:
                        label = -1
                    self.brain.train_ai(res['features'], label)

            # 处理15分钟数据
            for candle in initial_ohlcv_15m:
                self.brain.ingest_candle(candle, '15m')

            # 初始化时间戳
            self.current_candle_timestamp = initial_ohlcv_1m[-1][0]
        else:
            self.ui.log_msg("预热数据获取失败", "error")
            self.exchange.close()
            return

        self.ui.log_msg("系统启动完成，监听数据流...", "success")

        # 主循环
        while True:
            try:
                self._check_user_input()
                self._tick()
                time.sleep(0.05)  # 50ms 循环
            except KeyboardInterrupt:
                self._exit_procedure()
            except Exception as e:
                import traceback
                logger.error(f"Loop Error: {e}")
                traceback.print_exc()
                time.sleep(1)

    def _tick(self):
        # 1. 从本地缓存获取最新数据
        curr_candle_1m, curr_candle_15m, book, funding_rate, curr_btc_price = self.exchange.get_latest_data()
        if not curr_candle_15m: return  # 现在主要依赖15分钟K线

        # 使用15分钟K线作为主要价格和时间参考
        timestamp = curr_candle_15m[0]
        curr_price = float(curr_candle_15m[4])

        # === K线收盘检测与增量学习 ===

        if self.last_btc_price == 0:
            self.last_btc_price = curr_btc_price

        btc_change_pct = 0.0
        if self.last_btc_price > 0:
            btc_change_pct = (curr_btc_price - self.last_btc_price) / self.last_btc_price

        # 更新记录
        self.last_btc_price = curr_btc_price

        current_obi = 0.0
        if book:
            current_obi, _ = self.brain.state_machine.ob_analyzer.analyze(book)

        if self.current_candle_timestamp == 0:
            self.current_candle_timestamp = timestamp

        if timestamp > self.current_candle_timestamp:
            if self.last_tick_analysis is not None:
                logger.info(f"[Candle Close] K线收盘: {self.current_candle_timestamp} -> {timestamp}")
                self.brain.on_candle_close(self.last_tick_analysis, self.last_tick_price)
            self.current_candle_timestamp = timestamp

        # 2. 实时送入 Brain - 优先处理15分钟K线
        if curr_candle_15m:
            self.brain.ingest_candle(curr_candle_15m, '15m', btc_change_pct=btc_change_pct, obi_value=current_obi)
        if curr_candle_1m:
            self.brain.ingest_candle(curr_candle_1m, '1m', btc_change_pct=btc_change_pct, obi_value=current_obi)

        # 3. 记录交易快照
        if Config.ENABLE_MAIL_REPORT and self.position['size'] != 0:
            now = time.time()
            if now - self.last_snapshot_time >= 15:
                pnl = (curr_price - self.position['entry_price']) * self.position['size']
                self.trade_snapshots.append({
                    "time": now, "price": curr_price, "pnl": pnl, "regime": self.brain.state
                })
                self.last_snapshot_time = now

        # 4. 持仓管理
        if self.position['size'] != 0:
            self._manage_position(curr_price, funding_rate)

        # 5. 开仓逻辑 - 现在每15分钟才检查一次开仓机会
        if book:
            analysis = self.brain.analyze(book)
        else:
            analysis = None

        # 只在15分钟K线收盘时检查开仓机会
        should_check_position = False
        if curr_candle_15m and self.position['size'] == 0:
            # 检查是否是新的15分钟K线
            if self.last_position_check_timestamp != curr_candle_15m[0]:
                should_check_position = True
                self.last_position_check_timestamp = curr_candle_15m[0]
                logger.info(f"[15min Check] 15分钟K线收盘，开始检查开仓机会: {curr_candle_15m[0]}")

        if analysis and should_check_position and not self.risk.is_in_cooldown():
            self._attempt_entry(analysis, curr_price, funding_rate)

        # 6. UI更新
        unrealized_pnl = (curr_price - self.position['entry_price']) * self.position['size'] if self.position['size'] != 0 else 0

        hf_pred_1m = getattr(self.brain.rf_classifier, 'last_hf_prediction', 0.0)
        hf_pred_diff = self.brain.rf_classifier.price_prediction_diff if analysis else 0.0
        ai_conf = analysis.get('ai_prediction', (0, 0.0))[1] if analysis else 0.0
        cluster_data = analysis.get('cluster', (99, 0.0)) if analysis else (99, 0.0)
        cluster_id = cluster_data[0]
        obi = analysis.get('obi', 0.0) if analysis else 0.0

        self.ui.update_status(
            self.position['size'], self.brain.state, self.brain.color,
            obi, unrealized_pnl, curr_price,
            hf_pred_1m, hf_pred_diff, ai_conf, cluster_id
        )

        # Redis 心跳
        if Config.ENABLE_MAIL_REPORT and self.redis_client:
            try:
                heartbeat_data = {
                    "timestamp": int(time.time() * 1000),
                    "balance": self.balance,
                    "position_size": self.position['size'],
                    "price": curr_price,
                    "regime": self.brain.state,
                    "ai_conf": ai_conf,
                    "cluster": cluster_id,
                    "hf_pred": hf_pred_1m
                }
                self.redis_client.set('bot_status_heartbeat', json.dumps(heartbeat_data))
            except Exception:
                pass

        # 缓存当前帧
        if analysis:
            self.last_tick_analysis = analysis
            self.last_tick_price = curr_price

    def _manage_position(self, curr_price, funding_rate):
        pos = self.position
        raw_pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price'] * (1 if pos['size'] > 0 else -1)

        is_prof = raw_pnl_pct > Config.FEE_BUFFER_PCT
        if not self.was_in_profit and is_prof: self.profit_flip_count += 1
        self.was_in_profit = is_prof

        analysis = self.brain.analyze()
        atr = analysis.get('atr', 0.0) if analysis else 0.0

        if self.profit_flip_count >= 1:
            original_tp_distance = max(atr * 2, pos['entry_price'] * Config.MIN_TP_DISTANCE)
            if self.profit_flip_count == 1:
                adjusted_tp_distance = original_tp_distance
            elif self.profit_flip_count == 2:
                adjusted_tp_distance = original_tp_distance * 0.75
            else:
                adjusted_tp_distance = 0.0

            if pos['size'] > 0:
                pos['tp'] = pos['entry_price'] + adjusted_tp_distance
            else:
                pos['tp'] = pos['entry_price'] - adjusted_tp_distance

        should_exit, reason = self.risk.check_exit_conditions(
            pos, curr_price, time.time() * 1000, self.profit_flip_count, atr, self.balance
        )

        if should_exit:
            self._execute_exit(reason, curr_price, funding_rate)

    def _attempt_entry(self, data, price, funding_rate):
        sig, lev = self.brain.get_entry_signal(data, price)
        regime = self.brain.state
        cluster_data = data.get('cluster', (99, 0.0))
        current_cluster_id = cluster_data[0]

        if sig != 0:
            is_risky, fr_msg = self.risk.check_funding_rate_risk(sig, funding_rate)
            if is_risky:
                self.ui.log_msg(f"跳过交易: {fr_msg}", "warning")
                return

            amount = self.exchange.get_precision_amount(
                (self.balance * 0.99) / ((1 / lev) + Config.TAKER_FEE_RATE) / price, price
            )

            if amount > 0:
                side = 'buy' if sig == 1 else 'sell'
                if self.exchange.execute_order(side, amount):
                    atr = data.get('atr', 0.0)
                    sl_dist = price * (1 / lev) * 0.8
                    tp_dist = max(atr * 2, price * Config.MIN_TP_DISTANCE)

                    self.position = {
                        'size': amount if sig == 1 else -amount,
                        'entry_price': price,
                        'entry_time': time.time() * 1000,
                        'sl': price - sl_dist if sig == 1 else price + sl_dist,
                        'tp': price + tp_dist if sig == 1 else price - tp_dist,
                        'cluster': current_cluster_id
                    }

                    self.ui.log_entry(regime, self.brain.color, sig, lev,
                                      data.get('obi', 0.0), price, self.position['sl'], self.position['tp'])
                    self.profit_flip_count, self.was_in_profit = 0, False

    def _execute_exit(self, reason, price, funding_rate):
        pos_size = self.position['size']
        if pos_size == 0: return

        side = 'sell' if pos_size > 0 else 'buy'
        if self.exchange.execute_order(side, abs(pos_size), params={'reduceOnly': True}):
            entry = self.position['entry_price']
            raw_pnl = (price - entry) * pos_size
            fee = abs(pos_size) * (entry + price) * Config.TAKER_FEE_RATE
            net_pnl = raw_pnl - fee

            self.balance += net_pnl
            margin_used = abs(pos_size) * entry / Config.MAX_LEVERAGE
            cd_hrs, cd_msg = self.risk.activate_circuit_breaker(net_pnl, margin_used)

            self.ui.log_exit(reason, price, net_pnl, fee, self.balance, cd_msg)

            if Config.ENABLE_MAIL_REPORT and self.redis_client:
                try:
                    trade_record = {
                        "entry_time": self.position['entry_time'],
                        "exit_time": int(time.time() * 1000),
                        "mode": self.mode_name,
                        "action": "做多" if pos_size > 0 else "做空",
                        "entry_price": entry,
                        "exit_price": price,
                        "amount": abs(pos_size),
                        "leverage": Config.MAX_LEVERAGE,
                        "pnl": net_pnl,
                        "fee": fee,
                        "balance": self.balance,
                        "regime": self.brain.state,
                        "reason": reason,
                        "cluster": self.position.get('cluster', 99),
                        "snapshots": self.trade_snapshots
                    }
                    self.redis_client.rpush('trade_journal_pending', json.dumps(trade_record))
                except Exception as e:
                    logger.error(f"[邮件发送失败] Redis 错误: {e}")

            self.trade_snapshots = []
            self.last_snapshot_time = 0
            self.position = {'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 'entry_time': 0}

    def _check_user_input(self):
        if self.key_listener.is_q_pressed():
            logger.warning("=== ⏸ 暂停 === [0] 平仓退出 | [Enter] 继续")
            choice = self.key_listener.safe_input("指令 > ").strip()
            if choice == '0':
                self._exit_procedure()

    def _exit_procedure(self):
        self.exchange.close()
        if self.position['size'] != 0:
            logger.info("正在平仓并退出...")
            self._execute_exit("手动退出", 0.0, 0.0)
        sys.exit(0)


if __name__ == "__main__":
    bot = QuantBot()
    bot.run()