"""
交易绩效分析模块

计算指标:
- Sharpe Ratio (夏普比率): 风险调整后收益
- Sortino Ratio (索提诺比率): 下行风险调整后收益
- Calmar Ratio (卡尔玛比率): 收益/最大回撤
- Profit Factor (盈亏比): 总盈利/总亏损
- Max Drawdown (最大回撤)
- Win Rate (胜率)
- Average Trade Duration
- Expectancy (期望值)
- Consecutive Wins/Losses
- Recovery Factor (恢复因子)
- Payoff Ratio (收益比)
- Daily/Monthly Returns
- Risk of Ruin (破产风险估计)
"""

import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


class PerformanceAnalyzer:
    """交易绩效分析器"""

    ANNUALIZATION_FACTOR = 365 * 288  # 5分钟K线，一年约365天*288根

    def __init__(self, initial_balance: float = 100.0):
        self.initial_balance = initial_balance
        self.trades: list[dict] = []
        self.equity_curve: list[tuple[float, float]] = []  # (timestamp_ms, equity)

    def add_trade(self, trade: dict):
        """添加一笔交易记录"""
        self.trades.append(trade)

    def add_equity_snapshot(self, timestamp_ms: float, equity: float):
        """添加净值快照"""
        self.equity_curve.append((timestamp_ms, equity))

    def analyze(self) -> dict:
        """运行完整分析，返回所有指标"""
        if not self.trades:
            return self._empty_report()

        real_trades = [t for t in self.trades if t.get('mode') != 'INJECTION']
        if not real_trades:
            return self._empty_report()

        pnls = np.array([t['pnl'] for t in real_trades])
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]

        # 基础统计
        total_trades = len(real_trades)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total_trades if total_trades > 0 else 0.0
        total_pnl = float(pnls.sum())
        avg_pnl = float(pnls.mean())

        # 盈亏比
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses).mean()) if len(losses) > 0 else 0.0
        payoff_ratio = avg_win / (avg_loss + 1e-9)
        profit_factor = float(wins.sum() / (np.abs(losses).sum() + 1e-9)) if len(losses) > 0 else float('inf')

        # 期望值
        expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

        # 收益率序列
        returns = self._calculate_returns(real_trades)
        equity_returns = self._calculate_equity_returns()

        # 风险指标
        max_dd, max_dd_pct = self._max_drawdown()
        sharpe = self._sharpe_ratio(returns)
        sortino = self._sortino_ratio(returns)
        calmar = self._calmar_ratio(total_pnl, max_dd_pct)

        # 连续统计
        max_consec_wins, max_consec_losses = self._consecutive_stats(real_trades)

        # 恢复因子
        recovery_factor = total_pnl / (max_dd + 1e-9) if max_dd > 0 else 0.0

        # 交易时长
        durations = [t.get('duration_min', 0) for t in real_trades if t.get('duration_min', 0) > 0]
        avg_duration = float(np.mean(durations)) if durations else 0.0

        # 破产风险 (简化版: 基于Kelly)
        risk_of_ruin = self._risk_of_ruin(win_rate, payoff_ratio)

        # 日/月收益
        daily_returns = self._daily_returns_from_equity()

        return {
            # 基础统计
            'total_trades': total_trades,
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'final_balance': float(self.equity_curve[-1][1]) if self.equity_curve else self.initial_balance + total_pnl,
            'total_return_pct': (total_pnl / self.initial_balance) * 100,

            # 盈亏指标
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'payoff_ratio': payoff_ratio,
            'profit_factor': profit_factor,
            'expectancy': expectancy,

            # 风险指标
            'max_drawdown': max_dd,
            'max_drawdown_pct': max_dd_pct,
            'sharpe_ratio': sharpe,
            'sortino_ratio': sortino,
            'calmar_ratio': calmar,
            'recovery_factor': recovery_factor,
            'risk_of_ruin': risk_of_ruin,

            # 连续统计
            'max_consecutive_wins': max_consec_wins,
            'max_consecutive_losses': max_consec_losses,

            # 时长
            'avg_trade_duration_min': avg_duration,

            # 方向统计
            'long_trades': sum(1 for t in real_trades if t.get('direction') == 'LONG'),
            'short_trades': sum(1 for t in real_trades if t.get('direction') == 'SHORT'),
            'long_win_rate': self._direction_win_rate(real_trades, 'LONG'),
            'short_win_rate': self._direction_win_rate(real_trades, 'SHORT'),

            # 时间统计
            'daily_returns': daily_returns,
            'equity_curve': self.equity_curve,
        }

    def _calculate_returns(self, trades: list[dict]) -> np.ndarray:
        """计算每笔交易的收益率"""
        returns = []
        for t in trades:
            entry = t.get('entry_price', 0)
            if entry > 0:
                pnl_pct = t['pnl'] / (entry * abs(t.get('amount', 1)) + 1e-9)
                returns.append(pnl_pct)
        return np.array(returns) if returns else np.array([0.0])

    def _calculate_equity_returns(self) -> np.ndarray:
        """从净值曲线计算收益率"""
        if len(self.equity_curve) < 2:
            return np.array([0.0])
        equities = np.array([e[1] for e in self.equity_curve])
        returns = np.diff(equities) / (equities[:-1] + 1e-9)
        return returns

    def _max_drawdown(self) -> tuple[float, float]:
        """计算最大回撤（绝对值和百分比）"""
        if not self.equity_curve:
            return 0.0, 0.0

        equities = np.array([e[1] for e in self.equity_curve])
        peak = np.maximum.accumulate(equities)
        drawdown = peak - equities
        max_dd = float(drawdown.max())
        max_dd_pct = float((drawdown / (peak + 1e-9)).max()) * 100

        return max_dd, max_dd_pct

    def _sharpe_ratio(self, returns: np.ndarray, risk_free_rate: float = 0.0) -> float:
        """夏普比率 = (mean_return - risk_free) / std_return * sqrt(annualization)"""
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / self.ANNUALIZATION_FACTOR
        std = float(np.std(returns, ddof=1))
        if std == 0:
            return 0.0
        return float(np.mean(excess) / std * np.sqrt(self.ANNUALIZATION_FACTOR))

    def _sortino_ratio(self, returns: np.ndarray, risk_free_rate: float = 0.0) -> float:
        """索提诺比率 = (mean_return - risk_free) / downside_std"""
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / self.ANNUALIZATION_FACTOR
        downside = returns[returns < 0]
        if len(downside) == 0:
            return float('inf')
        downside_std = float(np.std(downside, ddof=1))
        if downside_std == 0:
            return 0.0
        return float(np.mean(excess) / downside_std * np.sqrt(self.ANNUALIZATION_FACTOR))

    def _calmar_ratio(self, total_return: float, max_dd_pct: float) -> float:
        """卡尔玛比率 = 年化收益 / 最大回撤"""
        if max_dd_pct == 0:
            return 0.0
        return total_return / (max_dd_pct / 100 * self.initial_balance + 1e-9)

    def _consecutive_stats(self, trades: list[dict]) -> tuple[int, int]:
        """计算最大连续盈利/亏损次数"""
        max_w, max_l = 0, 0
        curr_w, curr_l = 0, 0

        for t in trades:
            if t['pnl'] > 0:
                curr_w += 1
                curr_l = 0
                max_w = max(max_w, curr_w)
            else:
                curr_l += 1
                curr_w = 0
                max_l = max(max_l, curr_l)

        return max_w, max_l

    def _risk_of_ruin(self, win_rate: float, payoff: float) -> float:
        """破产风险估算 (简化Kelly公式)

        RoR ≈ ((1-edge) / (1+edge))^units
        edge = win_rate * payoff - (1 - win_rate)
        """
        edge = win_rate * payoff - (1 - win_rate)
        if edge <= 0:
            return 1.0  # 负期望值 = 必然破产
        if edge >= 1:
            return 0.0
        # 用20个单位作为近似
        return float(((1 - edge) / (1 + edge)) ** 20)

    def _direction_win_rate(self, trades: list[dict], direction: str) -> float:
        """计算特定方向的胜率"""
        dir_trades = [t for t in trades if t.get('direction') == direction]
        if not dir_trades:
            return 0.0
        return sum(1 for t in dir_trades if t['pnl'] > 0) / len(dir_trades)

    def _daily_returns_from_equity(self) -> dict:
        """从净值曲线计算日收益率"""
        if len(self.equity_curve) < 2:
            return {}

        df = pd.DataFrame(self.equity_curve, columns=['ts', 'equity'])
        df['date'] = pd.to_datetime(df['ts'], unit='ms').dt.date
        daily = df.groupby('date')['equity'].last()
        daily_ret = daily.pct_change().dropna()

        return {
            'mean': float(daily_ret.mean()) if len(daily_ret) > 0 else 0.0,
            'std': float(daily_ret.std()) if len(daily_ret) > 0 else 0.0,
            'min': float(daily_ret.min()) if len(daily_ret) > 0 else 0.0,
            'max': float(daily_ret.max()) if len(daily_ret) > 0 else 0.0,
            'positive_days': int((daily_ret > 0).sum()),
            'negative_days': int((daily_ret < 0).sum()),
        }

    def _empty_report(self) -> dict:
        return {
            'total_trades': 0, 'win_count': 0, 'loss_count': 0,
            'win_rate': 0.0, 'total_pnl': 0.0, 'avg_pnl': 0.0,
            'final_balance': self.initial_balance, 'total_return_pct': 0.0,
            'avg_win': 0.0, 'avg_loss': 0.0, 'payoff_ratio': 0.0,
            'profit_factor': 0.0, 'expectancy': 0.0,
            'max_drawdown': 0.0, 'max_drawdown_pct': 0.0,
            'sharpe_ratio': 0.0, 'sortino_ratio': 0.0, 'calmar_ratio': 0.0,
            'recovery_factor': 0.0, 'risk_of_ruin': 0.0,
            'max_consecutive_wins': 0, 'max_consecutive_losses': 0,
            'avg_trade_duration_min': 0.0,
            'long_trades': 0, 'short_trades': 0,
            'long_win_rate': 0.0, 'short_win_rate': 0.0,
            'daily_returns': {}, 'equity_curve': [],
        }

    def format_report(self, report: Optional[dict] = None) -> str:
        """格式化输出分析报告"""
        if report is None:
            report = self.analyze()

        lines = [
            "",
            "=" * 55,
            "  📊 交易绩效分析报告",
            "=" * 55,
            "",
            f"  总交易: {report['total_trades']} (多: {report['long_trades']}, 空: {report['short_trades']})",
            f"  胜率: {report['win_rate']:.1%} (多: {report['long_win_rate']:.1%}, 空: {report['short_win_rate']:.1%})",
            f"  净盈亏: ${report['total_pnl']:.2f} ({report['total_return_pct']:.1f}%)",
            f"  最终权益: ${report['final_balance']:.2f}",
            "",
            "  --- 盈亏指标 ---",
            f"  平均盈利: ${report['avg_win']:.4f}",
            f"  平均亏损: ${report['avg_loss']:.4f}",
            f"  盈亏比(Payoff): {report['payoff_ratio']:.2f}",
            f"  盈利因子(PF): {report['profit_factor']:.2f}",
            f"  期望值: ${report['expectancy']:.4f}",
            "",
            "  --- 风险指标 ---",
            f"  最大回撤: ${report['max_drawdown']:.2f} ({report['max_drawdown_pct']:.1f}%)",
            f"  Sharpe Ratio: {report['sharpe_ratio']:.2f}",
            f"  Sortino Ratio: {report['sortino_ratio']:.2f}",
            f"  Calmar Ratio: {report['calmar_ratio']:.2f}",
            f"  恢复因子: {report['recovery_factor']:.2f}",
            f"  破产风险: {report['risk_of_ruin']:.4f}",
            "",
            "  --- 交易特征 ---",
            f"  最大连胜: {report['max_consecutive_wins']}",
            f"  最大连亏: {report['max_consecutive_losses']}",
            f"  平均持仓: {report['avg_trade_duration_min']:.1f}分钟",
        ]

        daily = report.get('daily_returns', {})
        if daily:
            lines.extend([
                "",
                "  --- 日收益统计 ---",
                f"  日均收益: {daily.get('mean', 0):.4%}",
                f"  日波动率: {daily.get('std', 0):.4%}",
                f"  盈利天数: {daily.get('positive_days', 0)}",
                f"  亏损天数: {daily.get('negative_days', 0)}",
            ])

        lines.extend(["", "=" * 55])
        return "\n".join(lines)
