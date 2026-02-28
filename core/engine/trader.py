import json
import logging
import time

from core.config.settings import Config

logger = logging.getLogger(__name__)


class TradeExecutor:
    """负责具体的交易执行、持仓管理和止盈止损逻辑。"""

    BREAKEVEN_ACTIVATE = 0.002
    TRAIL_ACTIVATE = 0.004
    TRAIL_LOCK_RATIO = 0.50
    POSITION_ALLOC_RATIO = 0.20

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
        self.max_pnl_pct = 0.0
        self.trade_snapshots = []
        self.last_snapshot_time = 0
        self.last_traded_candle_timestamp = 0
        self.ENTRY_WINDOW_SECONDS = 45

    def set_redis_client(self, client):
        self.redis_client = client

    def update_balance(self, new_balance):
        self.balance = new_balance

    def tick(self, curr_price, funding_rate, analysis_data, timestamp):
        self._record_trade_snapshot(curr_price)

        if self.position['size'] != 0:
            self._manage_position(curr_price, funding_rate)

        self._check_entry(analysis_data, curr_price, funding_rate, timestamp)

    def _record_trade_snapshot(self, curr_price):
        if not (Config.ENABLE_MAIL_REPORT and self.position['size'] != 0):
            return

        now = time.time()
        if now - self.last_snapshot_time < 15:
            return

        pnl = (curr_price - self.position['entry_price']) * self.position['size']
        self.trade_snapshots.append({
            "time": now,
            "price": curr_price,
            "pnl": pnl,
            "regime": self.brain.state,
        })
        self.last_snapshot_time = now

    def _manage_position(self, curr_price, funding_rate):
        pos = self.position
        raw_pnl_pct = self._calculate_raw_pnl_pct(curr_price)

        if raw_pnl_pct > self.max_pnl_pct:
            self.max_pnl_pct = raw_pnl_pct

        self._apply_breakeven(pos)
        self._apply_trailing_stop(pos)

        analysis = self.brain.analyze()
        atr = analysis.get('atr', 0.0) if analysis else 0.0

        reversal_factor = analysis.get('reversal_factor', 0.0) if analysis else 0.0

        should_exit, reason = self.risk.check_exit_conditions(
            pos,
            curr_price,
            time.time() * 1000,
            self.profit_flip_count,
            atr,
            self.balance,
            reversal_factor,
        )
        if should_exit:
            self.execute_exit(reason, curr_price, funding_rate)

    def _apply_breakeven(self, pos):
        if self.max_pnl_pct < self.BREAKEVEN_ACTIVATE:
            return

        if pos['size'] > 0 and pos['sl'] < pos['entry_price']:
            pos['sl'] = pos['entry_price']
            logger.info(f"🛡️ 保本锁定 | Peak={self.max_pnl_pct*100:.2f}% → SL=入场价")
        elif pos['size'] < 0 and pos['sl'] > pos['entry_price']:
            pos['sl'] = pos['entry_price']
            logger.info(f"🛡️ 保本锁定 | Peak={self.max_pnl_pct*100:.2f}% → SL=入场价")

    def _apply_trailing_stop(self, pos):
        if self.max_pnl_pct < self.TRAIL_ACTIVATE:
            return

        locked_pnl = self.max_pnl_pct * self.TRAIL_LOCK_RATIO
        trail_sl_price = (
            pos['entry_price'] * (1 + locked_pnl)
            if pos['size'] > 0
            else pos['entry_price'] * (1 - locked_pnl)
        )

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

    def _check_entry(self, analysis, curr_price, funding_rate, timestamp):
        if not analysis:
            return
        if self.position['size'] != 0:
            return
        if self.risk.is_in_cooldown():
            return
        if self.last_traded_candle_timestamp == timestamp:
            return

        time_since_open = (time.time() * 1000) - timestamp
        if time_since_open >= (self.ENTRY_WINDOW_SECONDS * 1000):
            return

        self._attempt_entry(analysis, curr_price, funding_rate, timestamp)

    def _attempt_entry(self, data, price, funding_rate, timestamp):
        sig, lev = self.brain.get_entry_signal(data, price)
        regime = self.brain.state

        if sig == 0:
            return

        is_risky, fr_msg = self.risk.check_funding_rate_risk(sig, funding_rate)
        if is_risky:
            self.ui.log_msg(f"跳过交易: {fr_msg}", "warning")
            return

        amount = self._calculate_order_amount(price, lev)
        if amount <= 0:
            return

        side = 'buy' if sig == 1 else 'sell'
        if not self.exchange.execute_order(side, amount):
            return

        self.last_traded_candle_timestamp = timestamp
        self.position = self._build_position(sig, amount, price, data)

        self.ui.log_entry(
            regime,
            self.brain.color,
            sig,
            lev,
            price,
            self.position['sl'],
            self.position['tp'],
            macd=data.get('macd_histogram', 0.0),
            bb_mid=data.get('bb_middle', 0.0),
            st_val=data.get('supertrend_value', 0.0),
        )
        self.profit_flip_count, self.was_in_profit = 0, False
        self.max_pnl_pct = 0.0

    def _calculate_order_amount(self, price, leverage):
        raw_amount = (self.balance * self.POSITION_ALLOC_RATIO) / ((1 / leverage) + Config.TAKER_FEE_RATE) / price
        return self.exchange.get_precision_amount(raw_amount, price)

    def _build_position(self, signal, amount, price, analysis_data):
        atr = float(analysis_data.get('atr', 0.0)) if analysis_data else 0.0
        reversal = float(analysis_data.get('reversal_factor', 0.0)) if analysis_data else 0.0

        atr_scale = min(1.4, max(0.85, 1.0 + atr * 18.0))
        rev_scale = min(1.25, max(0.9, 1.0 + abs(reversal) * 0.2))
        sl_dist = price * Config.MAX_SL_DISTANCE * atr_scale
        tp_dist = price * Config.MIN_TP_DISTANCE * atr_scale * rev_scale
        is_long = signal == 1

        return {
            'size': amount if is_long else -amount,
            'entry_price': price,
            'entry_time': time.time() * 1000,
            'sl': price - sl_dist if is_long else price + sl_dist,
            'tp': price + tp_dist if is_long else price - tp_dist,
        }

    def _calculate_raw_pnl_pct(self, curr_price):
        pos = self.position
        direction = 1 if pos['size'] > 0 else -1
        return (curr_price - pos['entry_price']) / pos['entry_price'] * direction

    def execute_exit(self, reason, price, funding_rate=0.0):
        pos_size = self.position['size']
        if pos_size == 0:
            return

        side = 'sell' if pos_size > 0 else 'buy'
        if not self.exchange.execute_order(side, abs(pos_size), params={'reduceOnly': True}):
            return

        entry = self.position['entry_price']
        raw_pnl = (price - entry) * pos_size
        fee = abs(pos_size) * (entry + price) * Config.TAKER_FEE_RATE
        net_pnl = raw_pnl - fee

        self.balance += net_pnl
        self.max_pnl_pct = 0.0
        margin_used = abs(pos_size) * entry / Config.MAX_LEVERAGE
        _, cd_msg = self.risk.activate_circuit_breaker(net_pnl, margin_used)

        self.ui.log_exit(reason, price, net_pnl, fee, self.balance, cd_msg)
        self._report_trade_exit(pos_size, entry, price, net_pnl, fee, reason)

        self.trade_snapshots = []
        self.last_snapshot_time = 0
        self.position = {'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 'entry_time': 0}

    def _report_trade_exit(self, pos_size, entry, price, net_pnl, fee, reason):
        if not (Config.ENABLE_MAIL_REPORT and self.redis_client):
            return

        try:
            trade_record = {
                "entry_time": self.position['entry_time'],
                "exit_time": int(time.time() * 1000),
                "mode": "Live" if self.exchange.is_live else "Paper",
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
                "snapshots": self.trade_snapshots,
            }
            self.redis_client.rpush('trade_journal_pending', json.dumps(trade_record))
        except Exception as exc:
            logger.error(f"[Report] Redis Error: {exc}")
