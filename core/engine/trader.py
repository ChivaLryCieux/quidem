
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
        self.max_pnl_pct = 0.0  # 追踪持仓期间最高盈利百分比
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

        # 2. 持仓管理
        if self.position['size'] != 0:
            self._manage_position(curr_price, funding_rate)

        # 3. 开仓逻辑
        self._check_entry(analysis_data, curr_price, funding_rate, timestamp)


    def _manage_position(self, curr_price, funding_rate):
        pos = self.position
        raw_pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price'] * (1 if pos['size'] > 0 else -1)

        # 更新历史最高盈利
        if raw_pnl_pct > self.max_pnl_pct:
            self.max_pnl_pct = raw_pnl_pct

        # ============================================================
        # 保本底线: 盈利曾超过0.2%，SL移至入场价（这笔交易不许亏）
        # ============================================================
        BREAKEVEN_ACTIVATE = 0.002  # 0.2%

        if self.max_pnl_pct >= BREAKEVEN_ACTIVATE:
            if pos['size'] > 0 and pos['sl'] < pos['entry_price']:
                pos['sl'] = pos['entry_price']
                logger.info(f"🛡️ 保本锁定 | Peak={self.max_pnl_pct*100:.2f}% → SL=入场价")
            elif pos['size'] < 0 and pos['sl'] > pos['entry_price']:
                pos['sl'] = pos['entry_price']
                logger.info(f"🛡️ 保本锁定 | Peak={self.max_pnl_pct*100:.2f}% → SL=入场价")

        # ============================================================
        # 追踪止损: 盈利>0.4%后，SL跟踪最高盈利的50%
        # 例: 峰值+0.6% → SL在+0.3%, 反转到+0.3%时止盈
        # ============================================================
        TRAIL_ACTIVATE = 0.004   # 0.4% 激活追踪
        TRAIL_LOCK_RATIO = 0.50  # 锁定最高盈利的50%

        if self.max_pnl_pct >= TRAIL_ACTIVATE:
            locked_pnl = self.max_pnl_pct * TRAIL_LOCK_RATIO
            trail_sl_price = pos['entry_price'] * (1 + locked_pnl) if pos['size'] > 0 else pos['entry_price'] * (1 - locked_pnl)
            
            # 只向有利方向移动SL，永远不会回退
            if pos['size'] > 0 and trail_sl_price > pos['sl']:
                old_sl = pos['sl']
                pos['sl'] = trail_sl_price
                if old_sl <= pos['entry_price']:
                    logger.info(f"🔒 追踪止损激活 | Peak={self.max_pnl_pct*100:.2f}% → SL锁定+{locked_pnl*100:.2f}%")
            elif pos['size'] < 0 and trail_sl_price < pos['sl']:
                old_sl = pos['sl']
                pos['sl'] = trail_sl_price
                if old_sl >= pos['entry_price']:
                    logger.info(f"🔒 追踪止损激活 | Peak={self.max_pnl_pct*100:.2f}% → SL锁定+{locked_pnl*100:.2f}%")

        analysis = self.brain.analyze()
        atr = analysis.get('atr', 0.0) if analysis else 0.0

        # Check Exit (TP/SL/时间防御)
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

        if sig != 0:
            is_risky, fr_msg = self.risk.check_funding_rate_risk(sig, funding_rate)
            if is_risky:
                self.ui.log_msg(f"跳过交易: {fr_msg}", "warning")
                return

            # Calc Amount
            amount = self.exchange.get_precision_amount(
                (self.balance * 0.20) / ((1 / lev) + Config.TAKER_FEE_RATE) / price, price
            )

            if amount > 0:
                side = 'buy' if sig == 1 else 'sell'
                if self.exchange.execute_order(side, amount):
                    self.last_traded_candle_timestamp = timestamp
                    
                    # TP/SL 直接使用 settings 配置
                    sl_dist = price * Config.MAX_SL_DISTANCE
                    tp_dist = price * Config.MIN_TP_DISTANCE

                    self.position = {
                        'size': amount if sig == 1 else -amount,
                        'entry_price': price,
                        'entry_time': time.time() * 1000,
                        'sl': price - sl_dist if sig == 1 else price + sl_dist,
                        'tp': price + tp_dist if sig == 1 else price - tp_dist,
                    }

                    self.ui.log_entry(
                        regime, self.brain.color, sig, lev,
                        price, self.position['sl'], self.position['tp'],
                        macd=data.get('macd_histogram', 0.0),
                        bb_mid=data.get('bb_middle', 0.0),
                        st_val=data.get('supertrend_value', 0.0)
                    )
                    self.profit_flip_count, self.was_in_profit = 0, False
                    self.max_pnl_pct = 0.0

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
            self.max_pnl_pct = 0.0  # 重置追踪
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
