"""
风险管理器

负责:
1. 止盈止损检查
2. 资金费率风险检查
3. 熔断机制
4. 时间防御
5. 盈利翻转逃逸

止盈止损规则:
- 止盈: 0.6% 价格波动 (10x杠杆=6%本金)
- 硬止损: 0.5% 价格反向 (10x杠杆=5%本金)
"""

import time

from core.config import Config


class RiskManager:
    def __init__(self):
        self.cooldown_end_time = 0
        self.circuit_breaker_rules = [(-0.20, 48), (-0.10, 24), (0.0, 0)]
        self.time_defense_rules = [(5, -0.01), (30, -0.02)]
        self.time_defense_enabled = False

    def check_funding_rate_risk(self, direction, funding_rate):
        """检查资金费率风险。"""
        threshold = Config.MAX_FUNDING_RATE_THRESHOLD
        if direction == 1 and funding_rate > threshold:
            return True, f"费率过高不做多 ({funding_rate * 100:.4f}%)"
        if direction == -1 and funding_rate < -threshold:
            return True, f"费率过高不做空 ({funding_rate * 100:.4f}%)"
        return False, ""

    def check_exit_conditions(self, position_data, current_price, current_time_ms, flips_count, atr=0.0, entry_balance=100.0):
        """检查平仓条件。"""
        pos_size = position_data['size']
        entry_price = position_data['entry_price']
        entry_time = position_data['entry_time']
        tp = position_data['tp']

        raw_pnl_pct = self._calculate_raw_pnl_pct(pos_size, entry_price, current_price)
        duration_min = (current_time_ms - entry_time) / 60000.0
        current_equity_pnl = raw_pnl_pct * Config.MAX_LEVERAGE

        should_exit, reason = self._check_take_profit(pos_size, tp, current_price, raw_pnl_pct)
        if should_exit:
            return True, reason

        should_exit, reason = self._check_stop_loss(raw_pnl_pct)
        if should_exit:
            return True, reason

        should_exit, reason = self._check_time_defense(duration_min, current_equity_pnl)
        if should_exit:
            return True, reason

        should_exit, reason = self._check_bailout(flips_count, raw_pnl_pct)
        if should_exit:
            return True, reason

        return False, ""

    @staticmethod
    def _calculate_raw_pnl_pct(pos_size, entry_price, current_price):
        direction = 1 if pos_size > 0 else -1
        return (current_price - entry_price) / entry_price * direction

    def _check_take_profit(self, pos_size, tp, current_price, raw_pnl_pct):
        if pos_size > 0 and current_price >= tp:
            return True, "💰 TP"
        if pos_size < 0 and current_price <= tp:
            return True, "💰 TP"
        if raw_pnl_pct >= Config.MIN_TP_DISTANCE:
            return True, f"💰 TP({Config.MIN_TP_DISTANCE*100:.2f}%)"
        return False, ""

    @staticmethod
    def _check_stop_loss(raw_pnl_pct):
        sl_distance = Config.MAX_SL_DISTANCE
        if raw_pnl_pct <= -sl_distance:
            return True, f"🛑 SL({sl_distance*100:.1f}%)"
        return False, ""

    def _check_time_defense(self, duration_min, current_equity_pnl):
        if not self.time_defense_enabled:
            return False, ""

        for time_min, loss_limit in self.time_defense_rules:
            if duration_min >= time_min and current_equity_pnl <= loss_limit:
                return True, f"⏳ TimeDef({int(duration_min)}m)"
        return False, ""

    @staticmethod
    def _check_bailout(flips_count, raw_pnl_pct):
        if flips_count < Config.BAILOUT_ON_NTH_FLIP:
            return False, ""

        if flips_count == 1 and raw_pnl_pct > Config.FEE_BUFFER_PCT:
            return True, f"🏃 Bailout(Flip{flips_count})"
        if flips_count == 2 and raw_pnl_pct > Config.FEE_BUFFER_PCT * 0.75:
            return True, f"🏃 Bailout(Flip{flips_count},75%)"
        if flips_count >= 3 and raw_pnl_pct > 0:
            return True, f"🏃 Bailout(Flip{flips_count},AnyProfit)"
        return False, ""

    def activate_circuit_breaker(self, net_pnl, margin_used, now_ms=None):
        """触发熔断机制。"""
        if net_pnl >= 0:
            return 0, ""

        roi = net_pnl / (margin_used + 1e-9)
        cooldown_hours = 0
        for loss_threshold, hours in self.circuit_breaker_rules:
            if roi < loss_threshold:
                cooldown_hours = hours
                break

        if cooldown_hours > 0:
            base_ms = float(now_ms) if now_ms is not None else (time.time() * 1000)
            self.cooldown_end_time = base_ms + (cooldown_hours * 3600 * 1000)
            return cooldown_hours, f"触发熔断: 亏损 {roi * 100:.1f}%, 暂停 {cooldown_hours}h"

        return 0, ""

    def is_in_cooldown(self, now_ms=None):
        """检查是否在冷却期。"""
        base_ms = float(now_ms) if now_ms is not None else (time.time() * 1000)
        return base_ms < self.cooldown_end_time
