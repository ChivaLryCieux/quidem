"""
蒙特卡洛模拟器 (Monte Carlo Simulator)

用途:
  1. 交易序列重采样: 打乱交易顺序，模拟不同市场路径
  2. 破产概率估算: 基于历史交易分布
  3. 置信区间: 给出收益/回撤的置信区间
  4. 最优仓位验证: 测试不同仓位比例下的风险收益

数学方法:
  - Bootstrap重采样: 从历史交易中有放回抽样
  - 路径模拟: 生成N条可能的净值曲线
  - 统计分析: 对N条曲线计算分布
"""

import numpy as np
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MonteCarloSimulator:
    """蒙特卡洛策略模拟器"""

    def __init__(self, n_simulations: int = 1000, seed: int = 42):
        self.n_simulations = n_simulations
        self.rng = np.random.RandomState(seed)

    def simulate(
        self,
        trade_pnls: list[float],
        initial_balance: float = 100.0,
        max_drawdown_limit: float = 0.50,
    ) -> dict:
        """运行蒙特卡洛模拟

        Args:
            trade_pnls: 历史交易PnL列表
            initial_balance: 初始资金
            max_drawdown_limit: 破产定义(回撤超过此比例)

        Returns:
            模拟结果字典
        """
        if len(trade_pnls) < 10:
            return self._empty_result()

        pnls = np.array(trade_pnls)
        n_trades = len(pnls)

        # 存储每次模拟的结果
        final_balances = np.zeros(self.n_simulations)
        max_drawdowns = np.zeros(self.n_simulations)
        max_drawdown_pcts = np.zeros(self.n_simulations)
        sharpe_ratios = np.zeros(self.n_simulations)
        bankruptcy_count = 0

        for sim in range(self.n_simulations):
            # Bootstrap重采样
            sampled_pnls = self.rng.choice(pnls, size=n_trades, replace=True)

            # 生成净值曲线
            equity = initial_balance
            peak = initial_balance
            max_dd = 0.0
            max_dd_pct = 0.0
            returns = []

            for pnl in sampled_pnls:
                equity += pnl
                if equity <= 0:
                    bankruptcy_count += 1
                    equity = initial_balance * 0.01  # 保留1%作为"破产后"

                if equity > peak:
                    peak = equity
                dd = peak - equity
                dd_pct = dd / (peak + 1e-9)
                if dd > max_dd:
                    max_dd = dd
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct

                ret = pnl / (equity - pnl + 1e-9)
                returns.append(ret)

            final_balances[sim] = equity
            max_drawdowns[sim] = max_dd
            max_drawdown_pcts[sim] = max_dd_pct

            # 计算Sharpe
            if returns:
                ret_arr = np.array(returns)
                std = np.std(ret_arr)
                sharpe_ratios[sim] = np.mean(ret_arr) / (std + 1e-9) * np.sqrt(365 * 288) if std > 0 else 0.0

        # 统计分析
        percentiles = [5, 10, 25, 50, 75, 90, 95]

        return {
            'n_simulations': self.n_simulations,
            'n_trades': n_trades,
            'initial_balance': initial_balance,

            # 最终权益分布
            'final_balance_mean': float(np.mean(final_balances)),
            'final_balance_median': float(np.median(final_balances)),
            'final_balance_std': float(np.std(final_balances)),
            'final_balance_percentiles': {
                p: float(np.percentile(final_balances, p)) for p in percentiles
            },

            # 最大回撤分布
            'max_dd_mean': float(np.mean(max_drawdowns)),
            'max_dd_median': float(np.median(max_drawdowns)),
            'max_dd_pct_mean': float(np.mean(max_drawdown_pcts)) * 100,
            'max_dd_pct_p95': float(np.percentile(max_drawdown_pcts, 95)) * 100,

            # 夏普比率分布
            'sharpe_mean': float(np.mean(sharpe_ratios)),
            'sharpe_median': float(np.median(sharpe_ratios)),
            'sharpe_p5': float(np.percentile(sharpe_ratios, 5)),
            'sharpe_p95': float(np.percentile(sharpe_ratios, 95)),

            # 破产概率
            'bankruptcy_rate': bankruptcy_count / self.n_simulations,

            # 收益概率
            'prob_profit': float(np.mean(final_balances > initial_balance)),
            'prob_double': float(np.mean(final_balances > initial_balance * 2)),
            'prob_halve': float(np.mean(final_balances < initial_balance * 0.5)),

            # 原始统计
            'trade_mean': float(np.mean(pnls)),
            'trade_std': float(np.std(pnls)),
            'trade_win_rate': float(np.mean(pnls > 0)),
        }

    def simulate_position_sizes(
        self,
        trade_pnls: list[float],
        initial_balance: float = 100.0,
        alloc_range: Optional[list[float]] = None,
    ) -> dict:
        """测试不同仓位比例下的风险收益

        Args:
            trade_pnls: 历史交易PnL列表
            initial_balance: 初始资金
            alloc_range: 测试的仓位比例列表

        Returns:
            各仓位比例下的模拟结果
        """
        if alloc_range is None:
            alloc_range = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40]

        pnls = np.array(trade_pnls)
        base_mean = np.mean(pnls)
        results = {}

        for alloc in alloc_range:
            # 缩放PnL以匹配仓位比例
            scale = alloc / 0.20  # 相对于默认20%
            scaled_pnls = (pnls * scale).tolist()

            sim_result = self.simulate(scaled_pnls, initial_balance)
            results[alloc] = {
                'median_final': sim_result['final_balance_median'],
                'p5_final': sim_result['final_balance_percentiles'].get(5, 0),
                'p95_final': sim_result['final_balance_percentiles'].get(95, 0),
                'max_dd_pct': sim_result['max_dd_pct_mean'],
                'sharpe': sim_result['sharpe_mean'],
                'bankruptcy_rate': sim_result['bankruptcy_rate'],
                'prob_profit': sim_result['prob_profit'],
            }

        return results

    def format_report(self, result: dict) -> str:
        """格式化输出蒙特卡洛报告"""
        lines = [
            "",
            "=" * 55,
            "  🎲 蒙特卡洛模拟报告",
            "=" * 55,
            f"  模拟次数: {result['n_simulations']}",
            f"  交易笔数: {result['n_trades']}",
            f"  初始资金: ${result['initial_balance']:.2f}",
            "",
            "  --- 最终权益分布 ---",
            f"  均值: ${result['final_balance_mean']:.2f}",
            f"  中位数: ${result['final_balance_median']:.2f}",
            f"  5th分位: ${result['final_balance_percentiles'].get(5, 0):.2f}",
            f"  95th分位: ${result['final_balance_percentiles'].get(95, 0):.2f}",
            "",
            "  --- 风险指标 ---",
            f"  平均最大回撤: {result['max_dd_pct_mean']:.1f}%",
            f"  95%回撤上限: {result['max_dd_pct_p95']:.1f}%",
            f"  平均Sharpe: {result['sharpe_mean']:.2f}",
            f"  Sharpe 5%-95%: [{result['sharpe_p5']:.2f}, {result['sharpe_p95']:.2f}]",
            "",
            "  --- 概率统计 ---",
            f"  破产概率: {result['bankruptcy_rate']:.1%}",
            f"  盈利概率: {result['prob_profit']:.1%}",
            f"  翻倍概率: {result['prob_double']:.1%}",
            f"  减半概率: {result['prob_halve']:.1%}",
            "",
            "  --- 原始交易统计 ---",
            f"  平均PnL: ${result['trade_mean']:.4f}",
            f"  PnL标准差: ${result['trade_std']:.4f}",
            f"  胜率: {result['trade_win_rate']:.1%}",
            "=" * 55,
        ]
        return "\n".join(lines)

    @staticmethod
    def _empty_result() -> dict:
        return {
            'n_simulations': 0, 'n_trades': 0, 'initial_balance': 0,
            'final_balance_mean': 0, 'final_balance_median': 0,
            'final_balance_std': 0, 'final_balance_percentiles': {},
            'max_dd_mean': 0, 'max_dd_median': 0,
            'max_dd_pct_mean': 0, 'max_dd_pct_p95': 0,
            'sharpe_mean': 0, 'sharpe_median': 0, 'sharpe_p5': 0, 'sharpe_p95': 0,
            'bankruptcy_rate': 0, 'prob_profit': 0, 'prob_double': 0, 'prob_halve': 0,
            'trade_mean': 0, 'trade_std': 0, 'trade_win_rate': 0,
        }
