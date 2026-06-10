"""Tests for Phase 2-7 new modules: indicators, regime, position sizer, performance, monte carlo."""

import unittest
import numpy as np
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_df(n=200, seed=42):
    """生成测试用K线DataFrame"""
    rng = np.random.RandomState(seed)
    close = 100 + np.cumsum(rng.randn(n) * 0.5)
    high = close + rng.rand(n) * 0.3
    low = close - rng.rand(n) * 0.3
    opn = close + rng.randn(n) * 0.1
    volume = rng.rand(n) * 1000 + 100
    taker_buy = volume * 0.5
    ts = np.arange(n) * 300000  # 5min intervals
    return pd.DataFrame({
        'timestamp': ts, 'open': opn, 'high': high, 'low': low,
        'close': close, 'volume': volume, 'taker_buy': taker_buy
    })


class TestNewIndicators(unittest.TestCase):
    """测试Phase 2新增指标"""

    def test_ichimoku(self):
        from core.analysis.indicators import IchimokuCloud
        df = _make_df(200)
        ich = IchimokuCloud()
        result = ich.calculate(df)
        self.assertIn('tenkan', result)
        self.assertIn('kijun', result)
        self.assertIn('cloud_signal', result)
        self.assertIn(result['cloud_signal'], [-1, 0, 1])

    def test_stochastic_rsi(self):
        from core.analysis.indicators import StochasticRSI
        df = _make_df(200)
        srsi = StochasticRSI()
        result = srsi.calculate(df)
        self.assertIn('stoch_rsi_k', result)
        self.assertIn('stoch_rsi_d', result)
        self.assertTrue(0 <= result['stoch_rsi_k'] <= 100)

    def test_obv(self):
        from core.analysis.indicators import OBVCalculator
        df = _make_df(200)
        obv = OBVCalculator()
        result = obv.calculate(df)
        self.assertIn('obv', result)
        self.assertIn('obv_trend', result)

    def test_cci(self):
        from core.analysis.indicators import CCICalculator
        df = _make_df(200)
        cci = CCICalculator()
        result = cci.calculate(df)
        self.assertIn('cci', result)
        self.assertIn('cci_overbought', result)

    def test_williams_r(self):
        from core.analysis.indicators import WilliamsPercentR
        df = _make_df(200)
        wr = WilliamsPercentR()
        result = wr.calculate(df)
        self.assertIn('williams_r', result)
        self.assertTrue(-105 <= result['williams_r'] <= 5)

    def test_psar(self):
        from core.analysis.indicators import ParabolicSAR
        df = _make_df(200)
        psar = ParabolicSAR()
        result = psar.calculate(df)
        self.assertIn('sar', result)
        self.assertIn('sar_direction', result)
        self.assertIn(result['sar_direction'], [-1, 1])

    def test_vwma(self):
        from core.analysis.indicators import VWMACalculator
        df = _make_df(200)
        vwma = VWMACalculator()
        result = vwma.calculate(df)
        self.assertIn('vwma', result)
        self.assertIn('vwma_sma_deviation', result)

    def test_cmf(self):
        from core.analysis.indicators import ChaikinMoneyFlow
        df = _make_df(200)
        cmf = ChaikinMoneyFlow()
        result = cmf.calculate(df)
        self.assertIn('cmf', result)
        self.assertTrue(-1.1 <= result['cmf'] <= 1.1)

    def test_volume_profile(self):
        from core.analysis.indicators import VolumeProfile
        df = _make_df(200)
        vp = VolumeProfile()
        result = vp.calculate(df)
        self.assertIn('poc', result)
        self.assertIn('vah', result)
        self.assertIn('val', result)
        self.assertTrue(result['val'] <= result['poc'] <= result['vah'])


class TestRegimeDetector(unittest.TestCase):
    """测试HMM状态检测器"""

    def test_init(self):
        from core.analysis.regime import RegimeDetector
        rd = RegimeDetector(n_states=4)
        self.assertEqual(rd.current_state, -1)
        self.assertFalse(rd.is_fitted)

    def test_strategy_params(self):
        from core.analysis.regime import RegimeDetector, MarketRegime
        rd = RegimeDetector()
        rd.current_state = MarketRegime.TRENDING_UP
        params = rd.get_strategy_params()
        self.assertEqual(params['mode'], 'trend_follow')
        self.assertEqual(params['direction_bias'], 1)
        self.assertGreater(params['position_scale'], 1.0)

    def test_labels(self):
        from core.analysis.regime import MarketRegime
        self.assertIn("趋势", MarketRegime.label(MarketRegime.TRENDING_UP))
        self.assertIn("震荡", MarketRegime.label(MarketRegime.RANGING_LOW))


class TestPositionSizer(unittest.TestCase):
    """测试动态仓位管理器"""

    def test_init(self):
        from core.risk.position_sizer import PositionSizer
        ps = PositionSizer()
        self.assertEqual(len(ps.trade_history), 0)

    def test_kelly_with_history(self):
        from core.risk.position_sizer import PositionSizer
        ps = PositionSizer()
        # 添加20笔交易: 60%胜率
        for i in range(20):
            pnl = 2.0 if i < 12 else -1.0
            ps.record_trade(pnl)
        kelly = ps.calculate_kelly()
        self.assertGreater(kelly, 0)
        self.assertLessEqual(kelly, 0.5)

    def test_drawdown_adjustment(self):
        from core.risk.position_sizer import PositionSizer
        ps = PositionSizer()
        ps.update_equity(100)
        ps.update_equity(110)  # peak = 110
        ps.update_equity(99)   # dd = 10%
        scale = ps.calculate_drawdown_adjustment()
        self.assertLess(scale, 1.0)
        self.assertGreater(scale, 0.1)

    def test_position_size(self):
        from core.risk.position_sizer import PositionSizer
        ps = PositionSizer()
        ps.update_equity(100)
        amount, lev, info = ps.get_position_size(
            price=150.0, atr=3.0, balance=100.0
        )
        self.assertGreater(amount, 0)
        self.assertGreater(lev, 0)
        self.assertIn('kelly_alloc', info)


class TestPerformanceAnalyzer(unittest.TestCase):
    """测试绩效分析器"""

    def test_empty(self):
        from core.analysis.performance import PerformanceAnalyzer
        pa = PerformanceAnalyzer()
        report = pa.analyze()
        self.assertEqual(report['total_trades'], 0)

    def test_with_trades(self):
        from core.analysis.performance import PerformanceAnalyzer
        pa = PerformanceAnalyzer(initial_balance=100)
        trades = [
            {'pnl': 5.0, 'mode': 'BACKTEST', 'direction': 'LONG', 'entry_price': 100, 'amount': 1, 'duration_min': 30, 'entry_time': 1000, 'exit_time': 2000, 'balance': 105},
            {'pnl': -3.0, 'mode': 'BACKTEST', 'direction': 'SHORT', 'entry_price': 100, 'amount': 1, 'duration_min': 20, 'entry_time': 2000, 'exit_time': 3000, 'balance': 102},
            {'pnl': 4.0, 'mode': 'BACKTEST', 'direction': 'LONG', 'entry_price': 100, 'amount': 1, 'duration_min': 40, 'entry_time': 3000, 'exit_time': 4000, 'balance': 106},
        ]
        for t in trades:
            pa.add_trade(t)
            pa.add_equity_snapshot(t['exit_time'], t['balance'])

        report = pa.analyze()
        self.assertEqual(report['total_trades'], 3)
        self.assertGreater(report['win_rate'], 0)
        self.assertGreater(report['profit_factor'], 0)

    def test_format_report(self):
        from core.analysis.performance import PerformanceAnalyzer
        pa = PerformanceAnalyzer()
        pa.add_trade({'pnl': 5.0, 'mode': 'BACKTEST', 'direction': 'LONG', 'entry_price': 100, 'amount': 1, 'duration_min': 30})
        text = pa.format_report()
        self.assertIn("绩效", text)


class TestMonteCarlo(unittest.TestCase):
    """测试蒙特卡洛模拟器"""

    def test_simulate(self):
        from core.analysis.monte_carlo import MonteCarloSimulator
        rng = np.random.RandomState(42)
        pnls = (rng.randn(100) * 2 + 0.5).tolist()
        mc = MonteCarloSimulator(n_simulations=100)
        result = mc.simulate(pnls, 100.0)
        self.assertEqual(result['n_simulations'], 100)
        self.assertGreater(result['final_balance_mean'], 0)
        self.assertIn('bankruptcy_rate', result)

    def test_position_sizes(self):
        from core.analysis.monte_carlo import MonteCarloSimulator
        rng = np.random.RandomState(42)
        pnls = (rng.randn(50) * 1 + 0.3).tolist()
        mc = MonteCarloSimulator(n_simulations=50)
        result = mc.simulate_position_sizes(pnls)
        self.assertIn(0.05, result)
        self.assertIn(0.20, result)


if __name__ == '__main__':
    unittest.main()
