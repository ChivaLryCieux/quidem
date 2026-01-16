import numpy as np
import pandas as pd
import logging
from colorama import Fore, Style

from core.models.ml_models import SRP_PAR_EWA_Ensemble
from core.models.cluster import KMeansClusterAnalyzer
from core.strategy.analyzers import OrderBookAnalyzer, StateMachine
from core.strategy.signals import SignalGenerator

logger = logging.getLogger(__name__)


# ==========================================
# 策略大脑
# ==========================================
class StrategyBrain:
    def __init__(self):
        self.rf_classifier = SRP_PAR_EWA_Ensemble()
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
        sanitized_features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
        feature_values = []
        for i, v in enumerate(sanitized_features.flatten()):
            feature_values.append(v)
        x = {f"f{i}": v for i, v in enumerate(feature_values)}
        
        # SRP + PAR + EWA 训练
        self.rf_classifier.classifier_srp.learn_one(x, label)
        if label != 0:
            self.rf_classifier.classifier_par.learn_one(x, label)
            
        # EWA 回归训练
        # 简单使用平均值作为特征，这与 models.py 中的逻辑保持一致
        avg_feat = sum(feature_values) / len(feature_values)
        if np.isnan(avg_feat) or np.isinf(avg_feat):
            avg_feat = 0.0
            
        reg_features = {'input': avg_feat}
        # 将分类标签转换为回归目标 (-1.0, 0.0, 1.0)
        self.rf_classifier.ewa_ensemble.learn_one(reg_features, float(label))

    def get_entry_signal(self, analysis_data, current_price):
        return self.state_machine.get_entry_signal(analysis_data, current_price)

    def on_candle_close(self, final_analysis_of_closed_candle, close_price):
        if final_analysis_of_closed_candle and 'features' in final_analysis_of_closed_candle:
            self.rf_classifier.on_candle_close(
                final_analysis_of_closed_candle,
                close_price
            )