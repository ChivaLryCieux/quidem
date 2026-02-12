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
        """检查资金费率风险"""
        threshold = Config.MAX_FUNDING_RATE_THRESHOLD
        if direction == 1 and funding_rate > threshold:
            return True, f"费率过高不做多 ({funding_rate * 100:.4f}%)"
        if direction == -1 and funding_rate < -threshold:
            return True, f"费率过高不做空 ({funding_rate * 100:.4f}%)"
        return False, ""

    def check_exit_conditions(self, position_data, current_price, current_time_ms, 
                              flips_count, atr=0.0, entry_balance=100.0):
        """
        检查平仓条件
        
        规则:
        1. 显式TP价格检查
        2. 百分比TP兜底
        3. 硬止损
        4. 时间防御 (可选)
        5. 盈利翻转逃逸
        """
        pos_size = position_data['size']
        entry_price = position_data['entry_price']
        entry_time = position_data['entry_time']
        tp, sl = position_data['tp'], position_data['sl']

        # 计算当前盈亏百分比
        raw_pnl_pct = (current_price - entry_price) / entry_price * (1 if pos_size > 0 else -1)
        duration_ms = current_time_ms - entry_time
        duration_min = duration_ms / 60000.0
        current_equity_pnl = raw_pnl_pct * Config.MAX_LEVERAGE

        # ================================================================
        # 1. 显式TP价格检查
        # ================================================================
        if pos_size > 0:
            if current_price >= tp:
                return True, "💰 TP"
        else:
            if current_price <= tp:
                return True, "💰 TP"
        
        # 2. 百分比TP兜底
        if raw_pnl_pct >= Config.MIN_TP_DISTANCE:
            return True, f"💰 TP({Config.MIN_TP_DISTANCE*100:.2f}%)"

        # ================================================================
        # 3. 硬止损
        # ================================================================
        sl_distance = Config.MAX_SL_DISTANCE
        if raw_pnl_pct <= -sl_distance:
            return True, f"🛑 SL({sl_distance*100:.1f}%)"

        # ================================================================
        # 4. 时间防御 (仅在开关启用时生效)
        # ================================================================
        if self.time_defense_enabled:
            for time_min, loss_limit in self.time_defense_rules:
                if duration_min >= time_min and current_equity_pnl <= loss_limit:
                    return True, f"⏳ TimeDef({int(duration_min)}m)"

        # ================================================================
        # 5. 盈利翻转逃逸机制
        # ================================================================
        if flips_count >= Config.BAILOUT_ON_NTH_FLIP:
            if flips_count == 1:
                if raw_pnl_pct > Config.FEE_BUFFER_PCT:
                    return True, f"🏃 Bailout(Flip{flips_count})"
            elif flips_count == 2:
                if raw_pnl_pct > Config.FEE_BUFFER_PCT * 0.75:
                    return True, f"🏃 Bailout(Flip{flips_count},75%)"
            elif flips_count >= 3:
                if raw_pnl_pct > 0:
                    return True, f"🏃 Bailout(Flip{flips_count},AnyProfit)"

        return False, ""

    def activate_circuit_breaker(self, net_pnl, margin_used, now_ms=None):
        """触发熔断机制"""
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
        """检查是否在冷却期"""
        base_ms = float(now_ms) if now_ms is not None else (time.time() * 1000)
        return base_ms < self.cooldown_end_time