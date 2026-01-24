
import time
import json
import logging
from core.config.settings import Config

logger = logging.getLogger(__name__)

class TradeExecutor:
    """
    负责具体的交易执行、持仓管理和止盈止损逻辑。
    """
    def __init__(self, exchange_service, risk_manager, ui_manager, brain):
        self.exchange = exchange_service
        self.risk = risk_manager
        self.ui = ui_manager
        self.brain = brain
        
        self.redis_client = None
        self.balance = 100.0
        self.position = {'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 'entry_time': 0}
        
        self.profit_flip_count = 0
        self.was_in_profit = False
        self.trade_snapshots = []
        self.last_snapshot_time = 0
        self.last_traded_candle_timestamp = 0
        self.ENTRY_WINDOW_SECONDS = 45

    def set_redis_client(self, client):
        self.redis_client = client

    def update_balance(self, new_balance):
        self.balance = new_balance

    def tick(self, curr_price, funding_rate, analysis_data, timestamp):
        """每帧调用的核心逻辑"""
        
        # 1. 记录交易快照
        if Config.ENABLE_MAIL_REPORT and self.position['size'] != 0:
            now = time.time()
            if now - self.last_snapshot_time >= 15:
                pnl = (curr_price - self.position['entry_price']) * self.position['size']
                self.trade_snapshots.append({
                    "time": now, "price": curr_price, "pnl": pnl, "regime": self.brain.state
                })
                self.last_snapshot_time = now

        # 2. HMM 状态强制平仓逻辑（优先级最高）
        if analysis_data and self.position['size'] != 0:
            state_id = analysis_data.get('cluster', (99, 0.0))[0]
            
            # State 2: 震荡/噪音 - 强制平掉所有持仓
            if state_id == 2:
                logger.warning(f"⚠️ State 2 震荡检测 - 强制平仓")
                self.execute_exit("State 2 震荡 - 强制平仓", curr_price, funding_rate)
                return
            
            # State 0: 大跌 - 如果持有多单，强制平仓
            if state_id == 0 and self.position['size'] > 0:
                logger.warning(f"⚠️ State 0 大跌检测 - 强制平多单")
                self.execute_exit("State 0 大跌 - 平多单", curr_price, funding_rate)
                return
            
            # State 4: 大涨 - 如果持有空单，强制平仓
            if state_id == 4 and self.position['size'] < 0:
                logger.warning(f"⚠️ State 4 大涨检测 - 强制平空单")
                self.execute_exit("State 4 大涨 - 平空单", curr_price, funding_rate)
                return

        # 3. 持仓管理
        if self.position['size'] != 0:
            self._manage_position(curr_price, funding_rate)

        # 4. 开仓逻辑
        self._check_entry(analysis_data, curr_price, funding_rate, timestamp)


    def _manage_position(self, curr_price, funding_rate):
        pos = self.position
        raw_pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price'] * (1 if pos['size'] > 0 else -1)

        is_prof = raw_pnl_pct > Config.FEE_BUFFER_PCT
        if not self.was_in_profit and is_prof: self.profit_flip_count += 1
        self.was_in_profit = is_prof

        analysis = self.brain.analyze()
        atr = analysis.get('atr', 0.0) if analysis else 0.0

        # Trailing TP
        if self.profit_flip_count >= 1:
            original_tp_distance = max(atr * 2, pos['entry_price'] * Config.MIN_TP_DISTANCE)
            if self.profit_flip_count == 1:
                adj_dist = original_tp_distance
            elif self.profit_flip_count == 2:
                adj_dist = original_tp_distance * 0.75
            else:
                adj_dist = 0.0 # Aggressive exit

            if pos['size'] > 0:
                pos['tp'] = pos['entry_price'] + adj_dist
            else:
                pos['tp'] = pos['entry_price'] - adj_dist

        # Check Exit
        should_exit, reason = self.risk.check_exit_conditions(
            pos, curr_price, time.time() * 1000, self.profit_flip_count, atr, self.balance
        )

        if should_exit:
            self.execute_exit(reason, curr_price, funding_rate)

    def _check_entry(self, analysis, curr_price, funding_rate, timestamp):
        # Conditions:
        # 1. Analysis available
        # 2. No position
        # 3. Not in cooldown
        # 4. In entry window
        # 5. Not traded this candle
        
        if not analysis: return
        if self.position['size'] != 0: return
        if self.risk.is_in_cooldown(): return
        if self.last_traded_candle_timestamp == timestamp: return
        
        time_since_open = (time.time() * 1000) - timestamp
        if time_since_open >= (self.ENTRY_WINDOW_SECONDS * 1000): return

        self._attempt_entry(analysis, curr_price, funding_rate, timestamp)

    def _attempt_entry(self, data, price, funding_rate, timestamp):
        sig, lev = self.brain.get_entry_signal(data, price)
        regime = self.brain.state
        cluster_id = data.get('cluster', (99, 0.0))[0]

        if sig != 0:
            is_risky, fr_msg = self.risk.check_funding_rate_risk(sig, funding_rate)
            if is_risky:
                self.ui.log_msg(f"跳过交易: {fr_msg}", "warning")
                return

            # Calc Amount
            amount = self.exchange.get_precision_amount(
                (self.balance * 0.99) / ((1 / lev) + Config.TAKER_FEE_RATE) / price, price
            )

            if amount > 0:
                side = 'buy' if sig == 1 else 'sell'
                if self.exchange.execute_order(side, amount):
                    self.last_traded_candle_timestamp = timestamp
                    
                    atr = data.get('atr', 0.0)
                    sl_dist = price * (1 / lev) * 0.8
                    tp_dist = max(atr * 2, price * Config.MIN_TP_DISTANCE)

                    self.position = {
                        'size': amount if sig == 1 else -amount,
                        'entry_price': price,
                        'entry_time': time.time() * 1000,
                        'sl': price - sl_dist if sig == 1 else price + sl_dist,
                        'tp': price + tp_dist if sig == 1 else price - tp_dist,
                        'cluster': cluster_id
                    }

                    self.ui.log_entry(
                        regime, self.brain.color, sig, lev,
                        data.get('obi', 0.0), price, self.position['sl'], self.position['tp']
                    )
                    self.profit_flip_count, self.was_in_profit = 0, False

    def execute_exit(self, reason, price, funding_rate=0.0):
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

            # Report Logic
            if Config.ENABLE_MAIL_REPORT and self.redis_client:
                try:
                    trade_record = {
                        "entry_time": self.position['entry_time'],
                        "exit_time": int(time.time() * 1000),
                        "mode": "Live" if self.exchange.is_live else "Paper", # simplified
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
                    logger.error(f"[Report] Redis Error: {e}")

            # Reset
            self.trade_snapshots = []
            self.last_snapshot_time = 0
            self.position = {'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 'entry_time': 0}
