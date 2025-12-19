import time
from config import Config

# ==========================================
# 风险与资金管理器
# ==========================================
class RiskManager:
    def __init__(self):
        self.cooldown_end_time = 0
        self.oscillation_thresholds = {1: 999.0, 2: 0.0025, 3: Config.FEE_BUFFER_PCT}
        self.circuit_breaker_rules = [(-0.20, 48), (-0.10, 24), (0.0, 0)]
        self.time_defense_rules = [(5, -0.01), (30, -0.02)]

    def check_funding_rate_risk(self, direction, funding_rate):
        threshold = Config.MAX_FUNDING_RATE_THRESHOLD
        if direction == 1 and funding_rate > threshold:
            return True, f"费率过高不做多 ({funding_rate * 100:.4f}%)"
        if direction == -1 and funding_rate < -threshold:
            return True, f"费率过高不做空 ({funding_rate * 100:.4f}%)"
        return False, ""

    def check_exit_conditions(self, position_data, current_price, current_time_ms, flips_count):
        triggered, reason = False, ""
        pos_size = position_data['size']
        entry_price = position_data['entry_price']
        entry_time = position_data['entry_time']
        tp, sl = position_data['tp'], position_data['sl']

        if pos_size > 0:
            if current_price <= sl: return True, "🛑 SL"
            if current_price >= tp: return True, "💰 TP"
        else:
            if current_price >= sl: return True, "🛑 SL"
            if current_price <= tp: return True, "💰 TP"

        raw_pnl_pct = (current_price - entry_price) / entry_price * (1 if pos_size > 0 else -1)
        duration_ms = current_time_ms - entry_time
        duration_min = duration_ms / 60000.0
        current_equity_pnl = raw_pnl_pct * Config.MAX_LEVERAGE

        for time_min, loss_limit in self.time_defense_rules:
            if duration_min >= time_min and current_equity_pnl <= loss_limit:
                return True, f"⏳ TimeDef({int(duration_min)}m)"

        if flips_count >= Config.BAILOUT_ON_NTH_FLIP and raw_pnl_pct > Config.FEE_BUFFER_PCT:
            return True, f"🏃 Bailout(Flip{flips_count})"

        return False, ""

    def activate_circuit_breaker(self, net_pnl, margin_used):
        if net_pnl >= 0: return 0, ""
        roi = net_pnl / (margin_used + 1e-9)
        cooldown_hours = 0
        for loss_threshold, hours in self.circuit_breaker_rules:
            if roi < loss_threshold:
                cooldown_hours = hours
                break
        if cooldown_hours > 0:
            self.cooldown_end_time = time.time() * 1000 + (cooldown_hours * 3600 * 1000)
            return cooldown_hours, f"触发熔断: 亏损 {roi * 100:.1f}%, 暂停 {cooldown_hours}h"
        return 0, ""

    def is_in_cooldown(self):
        return (time.time() * 1000) < self.cooldown_end_time