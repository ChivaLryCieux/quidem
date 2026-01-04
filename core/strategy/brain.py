import numpy as np
import pandas as pd
import logging
from colorama import Fore, Style

from models.ml_models import RandomForestClassifier
from models.cluster import KMeansClusterAnalyzer
from strategy.analyzers import OrderBookAnalyzer, StateMachine
from strategy.signals import SignalGenerator

logger = logging.getLogger(__name__)


# ==========================================
# 3. 策略大脑
# ==========================================
class StrategyBrain:
    def __init__(self):
        self.rf_classifier = RandomForestClassifier()
        self.state_machine = StateMachine()
        self.cluster_analyzer = KMeansClusterAnalyzer()
        self.signal_generator = SignalGenerator()
        self.state = self.state_machine.state
        self.color = self.state_machine.color

    def ingest_candle(self, item, timeframe='1m', btc_change_pct=0.0, obi_value=0.0):
        self.rf_classifier.ingest_candle(item, timeframe, btc_change_pct, obi_value)

    def analyze(self, orderbook=None):
        feature_data = self.rf_classifier.extract_features()
        if not feature_data:
            return None

        feature_data['orderbook'] = orderbook
        obi, spread_pct = self.state_machine.ob_analyzer.analyze(orderbook)
        feature_data['obi'] = obi
        feature_data['spread_pct'] = spread_pct

        self.state, self.color = self.state_machine.determine_regime(
            feature_data['range_pct'],
            feature_data['vol_explosion']
        )

        ai_dir, ai_conf = self.rf_classifier.predict(feature_data['features'])
        feature_data['ai_prediction'] = (ai_dir, ai_conf)

        cluster_id, cluster_dist = self.cluster_analyzer.predict_cluster(
            feature_data.get('momentum_values'),
            feature_data.get('volatility_values')
        )
        feature_data['cluster'] = (cluster_id, cluster_dist)

        return feature_data

    def train_ai(self, features, label):
        # 兼容旧接口，虽然 on_candle_close 更好
        # 将 numpy 展平转 dict，确保没有 None 值
        feature_values = []
        for i, v in enumerate(features.flatten()):
            if v is None:
                feature_values.append(0.0)
            else:
                feature_values.append(v)
        x = {f"f{i}": v for i, v in enumerate(feature_values)}
        self.rf_classifier.rf_model.learn_one(x, label)
        self.rf_classifier.linear_model.learn_one(x, label)

    def get_entry_signal(self, analysis_data, current_price):
        return self.state_machine.get_entry_signal(analysis_data, current_price)

    def on_candle_close(self, final_analysis_of_closed_candle, close_price):
        if final_analysis_of_closed_candle and 'features' in final_analysis_of_closed_candle:
            self.rf_classifier.on_candle_close(
                final_analysis_of_closed_candle,
                close_price
            )