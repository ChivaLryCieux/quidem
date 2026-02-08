"""
策略大脑 - 核心策略控制器

负责:
1. 接收和处理K线数据 (5m + 15m 双周期)
2. 计算HMM特征和技术指标
3. 调用HMM引擎预测市场状态
4. 协调信号生成
"""

import numpy as np
import pandas as pd
import logging
from colorama import Fore, Style

from core.models.hmm_engine import HMMStateEngine
from core.strategy.analyzers import OrderBookAnalyzer, StateMachine
from core.analysis.feature_engineering import FeatureEngineer
from core.analysis.indicators import SuperTrend, BollingerBands

logger = logging.getLogger(__name__)


# ==========================================
# 策略大脑
# ==========================================
class StrategyBrain:
    def __init__(self):
        self.feature_engineer = FeatureEngineer()
        self.state_machine = StateMachine()
        self.hmm_engine = HMMStateEngine()
        self.state = self.state_machine.state
        self.color = self.state_machine.color
        
        # 5m K线历史数据 (用于信号生成和HMM)
        self.history_5m = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])
        
        # 15m K线历史数据 (用于趋势过滤)
        self.history_15m = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])
        
        # 缓存的分析数据
        self.cached_analysis_data = None
        
        # 15m SuperTrend计算器
        self.supertrend_15m = SuperTrend(atr_period=10, multiplier=3.0)

    def ingest_candle(self, item, timeframe='5m', btc_change_pct=0.0, obi_value=0.0):
        """
        接收K线数据并计算特征
        
        Args:
            item: K线数据 [timestamp, open, high, low, close, volume, taker_buy?]
            timeframe: '5m' 或 '15m' 或 '1m'
            btc_change_pct: BTC变化百分比 (保留兼容)
            obi_value: 订单簿失衡值 (保留兼容)
        """
        # 标准化 item 长度
        if len(item) == 6:
            item = list(item) + [item[5] * 0.5]  # 添加 taker_buy
        
        timestamp, open_, high, low, close, vol, taker_buy_vol = item
        new_row = pd.DataFrame([[timestamp, open_, high, low, close, vol, taker_buy_vol]],
                               columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])
        
        if timeframe in ['5m', '1m']:
            # 5m 数据用于信号生成和HMM
            if self.history_5m.empty:
                self.history_5m = new_row
            else:
                self.history_5m = pd.concat([self.history_5m, new_row]).iloc[-500:]
            
            # 计算5m特征
            if len(self.history_5m) >= 100:
                features, context = self.feature_engineer.calculate_features(
                    self.history_5m, close, btc_change_pct, obi_value
                )
                self.cached_analysis_data = context
        
        elif timeframe == '15m':
            # 15m 数据用于趋势过滤
            if self.history_15m.empty:
                self.history_15m = new_row
            else:
                self.history_15m = pd.concat([self.history_15m, new_row]).iloc[-200:]
            
            # 计算15m SuperTrend
            if len(self.history_15m) >= 30:
                st_result = self.supertrend_15m.calculate(self.history_15m)
                self.state_machine.update_15m_supertrend(st_result['direction'])

    def analyze(self, orderbook=None):
        """
        分析市场状态
        
        Returns:
            feature_data: 包含HMM状态、技术指标等的字典
        """
        feature_data = self.cached_analysis_data
        if not feature_data:
            return None

        feature_data['orderbook'] = orderbook
        obi, spread_pct = self.state_machine.ob_analyzer.analyze(orderbook)
        feature_data['obi'] = obi
        feature_data['spread_pct'] = spread_pct

        # 使用HMM状态预测 (新接口)
        state_id, state_confidence = self.hmm_engine.predict_state(
            context=feature_data
        )
        feature_data['cluster'] = (state_id, state_confidence)

        # 根据HMM状态设置显示状态和颜色
        state_map = {
            0: ("📉 大跌", Fore.RED),
            1: ("📉 小跌", Fore.LIGHTRED_EX),
            2: ("🦀 震荡", Fore.YELLOW),
            3: ("📈 小涨", Fore.LIGHTGREEN_EX),
            4: ("📈 大涨", Fore.GREEN),
            99: ("⏳ 初始", Fore.WHITE)
        }
        self.state, self.color = state_map.get(state_id, ("❓ 未知", Fore.WHITE))

        return feature_data

    def get_entry_signal(self, analysis_data, current_price):
        """获取入场信号"""
        return self.state_machine.get_entry_signal(analysis_data, current_price)