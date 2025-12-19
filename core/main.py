import sys
import time
import redis
import json
from colorama import init, Fore, Style

# 导入所有拆分后的模块
from config import Config, ExchangeService
from strategy import StrategyBrain
from risk_manager import RiskManager
from ui import DisplayManager, KeyListener

init(autoreset=True)

# ==========================================
# 机器人主引擎 (Trading Bot Engine)
# ==========================================
class QuantBot:
    def __init__(self):
        Config.setup_proxy()
        self.ui = DisplayManager()
        self.key_listener = KeyListener()

        # 用户选择模式
        print(f"请选择模式: [0] 退出 | [1] 模拟盘 (Paper) | [2] 实盘 (Live)")
        mode = input("请输入数字: ").strip()
        if mode == '0': sys.exit(0)
        self.is_live = (mode == '2')
        self.mode_name = "实盘" if self.is_live else "模拟盘"

        # 初始化服务
        self.exchange = ExchangeService(self.is_live)
        self.brain = StrategyBrain()
        self.risk = RiskManager()

        #初始化邮件转发功能
        self.redis_client = None
        self.trade_snapshots = []  # 用于记录资金曲线
        self.last_snapshot_time = 0

        if Config.ENABLE_MAIL_REPORT:
            try:
                # 尝试连接 Redis
                self.redis_client = redis.Redis(host='localhost', port=6379, db=0)
                self.redis_client.ping()  # 测试连接
                print(f"{Fore.GREEN}邮件服务已连接 {Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}邮件服务连接失败 {e}{Style.RESET_ALL}")
                self.redis_client = None

        # 交易状态
        self.balance = 100.0
        self.position = {'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 'entry_time': 0}
        # last_candle_closed_time 用于判断新K线是否生成
        self.last_candle_closed_time = 0
        self.profit_flip_count = 0
        self.was_in_profit = False

    def run(self):
        self.ui.log_startup(self.mode_name)

        # 连接交易所 (启动 WS)
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
                res = self.brain.analyze()
                if res:
                    label = 1 if float(candle[4]) - float(candle[1]) > 0 else -1
                    self.brain.train_ai(res['features'], label)

            # 处理15分钟数据
            for candle in initial_ohlcv_15m:
                self.brain.ingest_candle(candle, '15m')

            # 设置最近一根收盘K线的时间
            self.last_candle_closed_time = initial_ohlcv_1m[-2][0]
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
                self.ui.log_msg(f"Loop Error: {e}", "error")
                time.sleep(1)

    def _tick(self):
        # 1. 从本地缓存获取最新数据 (非阻塞)
        curr_candle_1m, curr_candle_15m, book, funding_rate = self.exchange.get_latest_data()
        if not curr_candle_1m: return

        # curr_candle_1m 格式: [t, o, h, l, c, v]
        # WebSocket 推送的是"当前正在进行"的K线。
        curr_time = curr_candle_1m[0]
        curr_price = curr_candle_1m[4]

        # 实时送入 Brain 进行计算 (即便是未收盘的K线也可以用来计算实时指标)
        self.brain.ingest_candle(curr_candle_1m, '1m')
        
        # 如果有15分钟数据，也送入Brain
        if curr_candle_15m:
            self.brain.ingest_candle(curr_candle_15m, '15m')

        # 记录交易快照 (用于邮件画微型走势图)
        if Config.ENABLE_MAIL_REPORT and self.position['size'] != 0:
            now = time.time()
            if now - self.last_snapshot_time >= 15:
                pnl = (curr_price - self.position['entry_price']) * self.position['size']

                self.trade_snapshots.append({
                    "time": now,
                    "price": curr_price,
                    "pnl": pnl,
                    "regime": self.brain.state
                })
                self.last_snapshot_time = now

        # 2. 持仓管理 (实时监控价格)
        if self.position['size'] != 0:
            self._manage_position(curr_price, funding_rate)

        # 3. 开仓逻辑
        analysis = self.brain.analyze(book)

        # 只有当数据足够新，且不在CD中
        if analysis and not self.risk.is_in_cooldown():
            if self.position['size'] == 0:
                self._attempt_entry(analysis, curr_price, funding_rate)

        # 4. UI更新
        unrealized_pnl = (curr_price - self.position['entry_price']) * self.position['size'] if self.position[
                                                                                                    'size'] != 0 else 0
        self.ui.update_status(self.position['size'], self.brain.state, self.brain.color, 
                             analysis.get('obi', 0.0) if analysis else 0.0, 
                             unrealized_pnl, curr_price, funding_rate)

    def _manage_position(self, curr_price, funding_rate):
        pos = self.position
        raw_pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price'] * (1 if pos['size'] > 0 else -1)

        is_prof = raw_pnl_pct > Config.FEE_BUFFER_PCT
        if not self.was_in_profit and is_prof: self.profit_flip_count += 1
        self.was_in_profit = is_prof

        should_exit, reason = self.risk.check_exit_conditions(
            pos, curr_price, time.time() * 1000, self.profit_flip_count
        )

        if should_exit:
            self._execute_exit(reason, curr_price, funding_rate)

    def _attempt_entry(self, data, price, funding_rate):
        # 将复杂的信号判断逻辑委托给 strategy 模块
        sig, lev = self.brain.get_entry_signal(data, price)
        regime = self.brain.state

        # 如果收到有效信号 (sig != 0)，执行风控检查与下单
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
                # 交易执行仍然走 REST API
                if self.exchange.execute_order(side, amount):
                    self.position = {
                        'size': amount if sig == 1 else -amount,
                        'entry_price': price,
                        'entry_time': time.time() * 1000,
                        'sl': price * (1 - 0.005) if sig == 1 else price * (1 + 0.005),
                        'tp': price * (1 + 0.01) if sig == 1 else price * (1 - 0.01)
                    }
                    dist = price * (1 / lev) * 0.8
                    self.position['sl'] = price - dist if sig == 1 else price + dist
                    tp_mult = 3.0 if regime == "🚀 TREND" else 1.5
                    self.position['tp'] = price + max(data['atr'] * tp_mult, price * Config.MIN_TP_DISTANCE) * sig

                    self.ui.log_entry(regime, self.brain.color, sig, lev, 
                                     data.get('obi', 0.0), price, self.position['sl'],
                                     self.position['tp'], funding_rate)
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

            #发送邮件报告数据
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
                        "snapshots": self.trade_snapshots
                    }
                    self.redis_client.rpush('trade_journal_pending', json.dumps(trade_record))
                except Exception as e:
                    print(f"{Fore.RED}[邮件发送失败] Redis 错误: {e}{Style.RESET_ALL}")
            self.trade_snapshots = []
            self.last_snapshot_time = 0

            self.position = {'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 'entry_time': 0}

    def _check_user_input(self):
        if self.key_listener.is_q_pressed():
            print(f"\n{Fore.YELLOW}=== ⏸ 暂停 === [0] 平仓退出 | [Enter] 继续{Style.RESET_ALL}")
            choice = self.key_listener.safe_input("指令 > ").strip()
            if choice == '0':
                self._exit_procedure()

    def _exit_procedure(self):
        self.exchange.close()  # 关闭WS
        if self.position['size'] != 0:
            print("正在平仓并退出...")
            self._execute_exit("手动退出", 0.0, 0.0)
        sys.exit(0)


if __name__ == "__main__":
    bot = QuantBot()
    bot.run()