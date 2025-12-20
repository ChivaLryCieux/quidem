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
        # 时间防御机制开关，True为启用，False为禁用
        self.time_defense_enabled = False

    def check_funding_rate_risk(self, direction, funding_rate):
        threshold = Config.MAX_FUNDING_RATE_THRESHOLD
        if direction == 1 and funding_rate > threshold:
            return True, f"费率过高不做多 ({funding_rate * 100:.4f}%)"
        if direction == -1 and funding_rate < -threshold:
            return True, f"费率过高不做空 ({funding_rate * 100:.4f}%)"
        return False, ""

    def check_exit_conditions(self, position_data, current_price, current_time_ms, flips_count, atr=0.0, entry_balance=100.0):
        """
        检查平仓条件
        新的平仓判定器：
        1.如果达到本金+max{最小止盈距离，2倍ATR}，则止盈
        2.利用已有的震荡逃逸
        3.持仓15分钟后仍未平仓，则判定新的15步价差，若依然大于/小于最小止盈距离（和开仓方向一致），则继续持仓，否则，若有盈利则立即平仓，若亏损，依然继续持仓
        4.若启用风险管理类，则按类的内容止损，若未启用，爆仓才止损
        """
        triggered, reason = False, ""
        pos_size = position_data['size']
        entry_price = position_data['entry_price']
        entry_time = position_data['entry_time']
        tp, sl = position_data['tp'], position_data['sl']

        # 基础止损止盈检查
        if pos_size > 0:
            if current_price <= sl: return True, "🛑 SL"
            if current_price >= tp: return True, "💰 TP"
        else:
            if current_price >= sl: return True, "🛑 SL"
            if current_price <= tp: return True, "💰 TP"

        # 计算当前盈亏百分比
        raw_pnl_pct = (current_price - entry_price) / entry_price * (1 if pos_size > 0 else -1)
        duration_ms = current_time_ms - entry_time
        duration_min = duration_ms / 60000.0
        current_equity_pnl = raw_pnl_pct * Config.MAX_LEVERAGE

        # 1. 如果达到本金+max{最小止盈距离，2倍ATR}，则止盈
        profit_threshold = max(Config.MIN_TP_DISTANCE, 2 * atr / entry_price if atr > 0 else Config.MIN_TP_DISTANCE)
        if raw_pnl_pct >= profit_threshold:
            return True, f"💰 TargetProfit({profit_threshold*100:.2f}%)"

        # 2. 时间防御（仅在开关启用时生效）
        if self.time_defense_enabled:
            for time_min, loss_limit in self.time_defense_rules:
                if duration_min >= time_min and current_equity_pnl <= loss_limit:
                    return True, f"⏳ TimeDef({int(duration_min)}m)"

        # 3. 盈利翻转逃逸机制
        # 第一次翻转，止盈距离不变，第二次翻转，止盈距离变为原来的75%，第三次翻转，一有盈利就平仓
        if flips_count >= Config.BAILOUT_ON_NTH_FLIP:
            if flips_count == 1:
                # 第一次翻转，保持原有止盈距离
                if raw_pnl_pct > Config.FEE_BUFFER_PCT:
                    return True, f"🏃 Bailout(Flip{flips_count})"
            elif flips_count == 2:
                # 第二次翻转，止盈距离变为原来的75%
                if raw_pnl_pct > Config.FEE_BUFFER_PCT * 0.75:
                    return True, f"🏃 Bailout(Flip{flips_count},75%)"
            elif flips_count >= 3:
                # 第三次翻转，一有盈利就平仓
                if raw_pnl_pct > 0:
                    return True, f"🏃 Bailout(Flip{flips_count},AnyProfit)"

        # 4. 持仓15分钟后仍未平仓，则判定新的15步价差
        if duration_min >= 15:
            # 这里需要传入新的价差信息，但由于函数签名限制，我们在外部处理这部分逻辑
            # 返回特殊标记，表示需要进一步检查
            return "CHECK_PRICE_DIFF", f"⏱️ 15minCheck({int(duration_min)}m)"

        # 5. 若启用风险管理类，则按类的内容止损，若未启用，爆仓才止损
        # 这部分已经在基础止损止盈检查中处理

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