import numpy as np
import pandas as pd
import logging
from colorama import Fore, Style

from core.models.hmm_engine import HMMStateEngine
from core.strategy.analyzers import OrderBookAnalyzer, StateMachine
from core.strategy.signals import SignalGenerator
from core.analysis.feature_engineering import FeatureEngineer

logger = logging.getLogger(__name__)


# ==========================================
# 策略大脑
# ==========================================
class StrategyBrain:
    def __init__(self):
        self.feature_engineer = FeatureEngineer()
        self.state_machine = StateMachine()
        self.hmm_engine = HMMStateEngine()
        self.signal_generator = SignalGenerator()
        self.state = self.state_machine.state
        self.color = self.state_machine.color
        
        # K线历史数据
        self.history = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])
        self.cached_analysis_data = None

    def ingest_candle(self, item, timeframe='1m', btc_change_pct=0.0, obi_value=0.0):
        """接收K线数据并计算特征"""
        if timeframe == '15m':
            if len(item) == 6:
                item.append(item[5] * 0.5)
            timestamp, open_, high, low, close, vol, taker_buy_vol = item
            new_row = pd.DataFrame([[timestamp, open_, high, low, close, vol, taker_buy_vol]],
                                   columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])

            if self.history.empty:
                self.history = new_row
            else:
                self.history = pd.concat([self.history, new_row]).iloc[-500:]

            # 计算特征
            features, context = self.feature_engineer.calculate_features(
                self.history, close, btc_change_pct, obi_value
            )
            self.cached_analysis_data = context

    def analyze(self, orderbook=None):
        """分析市场状态"""
        feature_data = self.cached_analysis_data
        if not feature_data:
            return None

        feature_data['orderbook'] = orderbook
        obi, spread_pct = self.state_machine.ob_analyzer.analyze(orderbook)
        feature_data['obi'] = obi
        feature_data['spread_pct'] = spread_pct

        # 使用HMM状态预测
        state_id, state_confidence = self.hmm_engine.predict_state(
            feature_data.get('momentum_values'),
            feature_data.get('volatility_values')
        )
        feature_data['cluster'] = (state_id, state_confidence)

        # 根据HMM状态设置显示状态和颜色
        state_map = {
            0: ("📉 大跌", Fore.RED),
            1: ("📉 弱跌", Fore.LIGHTRED_EX),
            2: ("🦀 震荡", Fore.YELLOW),
            3: ("📈 弱涨", Fore.LIGHTGREEN_EX),
            4: ("📈 大涨", Fore.GREEN),
            99: ("⏳ 初始", Fore.WHITE)
        }
        self.state, self.color = state_map.get(state_id, ("❓ 未知", Fore.WHITE))

        return feature_data

    def get_entry_signal(self, analysis_data, current_price):
        return self.state_machine.get_entry_signal(analysis_data, current_price)