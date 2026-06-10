"""
动态仓位管理器 (Position Sizer)

核心算法:
1. Kelly Criterion: 基于历史胜率和盈亏比计算最优仓位比例
2. 波动率自适应杠杆: ATR高时降低杠杆，ATR低时适度提高
3. 回撤缩仓: 净值回撤时线性降低仓位
4. 信号强度加权: 强共识信号使用更大仓位

数学基础:
  Kelly% = W - (1-W)/R
  其中 W=胜率, R=盈亏比(平均盈利/平均亏损)
  实际使用 Kelly/2 (半Kelly) 以降低波动

  波动率杠杆: leverage = base_lev * (target_vol / current_vol)
  回撤缩仓: alloc = base_alloc * max(0.2, 1 - dd_pct/dd_limit)
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)


class TradeRecord:
    """单条交易记录，用于统计胜率和盈亏比"""
    __slots__ = ('pnl', 'is_win', 'duration_min')

    def __init__(self, pnl: float, duration_min: float = 0.0):
        self.pnl = pnl
        self.is_win = pnl > 0
        self.duration_min = duration_min


class PositionSizer:
    """动态仓位管理器"""

    # 默认参数
    DEFAULT_ALLOC = 0.20           # 默认仓位比例
    MIN_ALLOC = 0.05               # 最小仓位比例
    MAX_ALLOC = 0.40               # 最大仓位比例
    KELLY_FRACTION = 0.5           # 使用半Kelly
    MIN_TRADES_FOR_KELLY = 20      # 最少交易次数才启用Kelly
    TARGET_DAILY_VOL = 0.02        # 目标日波动率 (2%)
    DD_REDUCE_START = 0.05         # 回撤5%开始缩仓
    DD_REDUCE_LIMIT = 0.20         # 回撤20%缩到最小
    BASE_LEVERAGE = 10.0
    MIN_LEVERAGE = 3.0
    MAX_LEVERAGE = 15.0

    def __init__(self):
        self.trade_history: list[TradeRecord] = []
        self.max_history = 200     # 最多保留最近200笔交易
        self.peak_equity = 0.0
        self.current_equity = 0.0

    def update_equity(self, equity: float):
        """更新净值，用于回撤计算"""
        self.current_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity

    def record_trade(self, pnl: float, duration_min: float = 0.0):
        """记录一笔交易结果"""
        self.trade_history.append(TradeRecord(pnl, duration_min))
        if len(self.trade_history) > self.max_history:
            self.trade_history = self.trade_history[-self.max_history:]

    def calculate_kelly(self) -> float:
        """计算Kelly最优仓位比例

        Returns:
            kelly_alloc: 0.0 ~ 0.5 (半Kelly)
        """
        trades = self.trade_history
        if len(trades) < self.MIN_TRADES_FOR_KELLY:
            return self.DEFAULT_ALLOC

        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]

        if not wins or not losses:
            return self.DEFAULT_ALLOC

        win_rate = len(wins) / len(trades)
        avg_win = np.mean([abs(t.pnl) for t in wins])
        avg_loss = np.mean([abs(t.pnl) for t in losses])

        if avg_loss == 0:
            return self.DEFAULT_ALLOC

        win_loss_ratio = avg_win / avg_loss

        # Kelly公式: f* = W - (1-W)/R
        kelly = win_rate - (1 - win_rate) / win_loss_ratio

        # 限制范围，使用半Kelly
        kelly = max(0.0, min(0.5, kelly * self.KELLY_FRACTION))

        return kelly

    def calculate_vol_adjusted_leverage(self, atr: float, price: float) -> float:
        """根据波动率调整杠杆

        ATR高 → 降低杠杆 (风险大)
        ATR低 → 适度提高杠杆 (风险小)

        Args:
            atr: 当前ATR值
            price: 当前价格

        Returns:
            leverage: 调整后的杠杆倍数
        """
        if price <= 0 or atr <= 0:
            return self.BASE_LEVERAGE

        # 当前波动率 = ATR / Price
        current_vol = atr / price

        # 波动率调整因子 = 目标波动率 / 当前波动率
        vol_factor = self.TARGET_DAILY_VOL / (current_vol + 1e-9)
        vol_factor = np.clip(vol_factor, 0.5, 2.0)  # 限制在0.5x~2x

        leverage = self.BASE_LEVERAGE * vol_factor
        return float(np.clip(leverage, self.MIN_LEVERAGE, self.MAX_LEVERAGE))

    def calculate_drawdown_adjustment(self) -> float:
        """根据回撤计算仓位缩放因子

        Returns:
            scale: 0.2 ~ 1.0 (线性缩减)
        """
        if self.peak_equity <= 0:
            return 1.0

        dd_pct = (self.peak_equity - self.current_equity) / self.peak_equity

        if dd_pct <= self.DD_REDUCE_START:
            return 1.0

        # 线性缩减: 从DD_REDUCE_START到DD_REDUCE_LIMIT
        range_dd = self.DD_REDUCE_LIMIT - self.DD_REDUCE_START
        progress = (dd_pct - self.DD_REDUCE_START) / range_dd
        progress = min(1.0, progress)

        scale = 1.0 - progress * 0.8  # 最多缩减到20%
        return max(0.2, scale)

    def get_position_size(
        self,
        price: float,
        atr: float,
        signal_strength: float = 1.0,
        balance: float = 100.0,
        fee_rate: float = 0.0005,
    ) -> tuple[float, float, dict]:
        """计算最优仓位大小和杠杆

        Args:
            price: 当前价格
            atr: 当前ATR
            signal_strength: 信号强度 (1.0=正常, >1.0=强信号)
            balance: 当前余额
            fee_rate: 手续费率

        Returns:
            (amount, leverage, info_dict)
        """
        # 1. Kelly仓位
        kelly_alloc = self.calculate_kelly()

        # 2. 回撤缩放
        dd_scale = self.calculate_drawdown_adjustment()

        # 3. 信号强度加权 (1.0 ~ 1.5)
        signal_scale = min(1.5, max(0.5, signal_strength))

        # 4. 最终仓位比例
        alloc = kelly_alloc * dd_scale * signal_scale
        alloc = float(np.clip(alloc, self.MIN_ALLOC, self.MAX_ALLOC))

        # 5. 波动率自适应杠杆
        leverage = self.calculate_vol_adjusted_leverage(atr, price)

        # 6. 计算下单数量
        margin = balance * alloc
        amount = margin * leverage / price
        fee = amount * price * fee_rate
        amount_after_fee = (margin - fee) * leverage / price

        info = {
            'kelly_alloc': kelly_alloc,
            'dd_scale': dd_scale,
            'signal_scale': signal_scale,
            'final_alloc': alloc,
            'leverage': leverage,
            'margin': margin,
            'drawdown_pct': (self.peak_equity - self.current_equity) / max(self.peak_equity, 1) * 100,
            'trade_count': len(self.trade_history),
            'win_rate': self._win_rate(),
            'avg_rr_ratio': self._avg_rr(),
        }

        return amount_after_fee, leverage, info

    def get_exit_metrics(self) -> dict:
        """获取退出相关的统计指标"""
        trades = self.trade_history
        if not trades:
            return {'consecutive_losses': 0, 'recent_pnl_5': 0.0, 'recent_pnl_10': 0.0}

        consec_losses = 0
        for t in reversed(trades):
            if not t.is_win:
                consec_losses += 1
            else:
                break

        recent_5 = sum(t.pnl for t in trades[-5:])
        recent_10 = sum(t.pnl for t in trades[-10:])

        return {
            'consecutive_losses': consec_losses,
            'recent_pnl_5': recent_5,
            'recent_pnl_10': recent_10,
            'total_trades': len(trades),
        }

    def _win_rate(self) -> float:
        if not self.trade_history:
            return 0.0
        return sum(1 for t in self.trade_history if t.is_win) / len(self.trade_history)

    def _avg_rr(self) -> float:
        wins = [abs(t.pnl) for t in self.trade_history if t.is_win]
        losses = [abs(t.pnl) for t in self.trade_history if not t.is_win]
        if not wins or not losses:
            return 0.0
        return np.mean(wins) / (np.mean(losses) + 1e-9)
