import numpy as np
import pandas as pd
import logging
from colorama import Fore, Style

from config import Config
from models import RandomForestClassifier, KMeansClusterAnalyzer

logger = logging.getLogger(__name__)


# ==========================================
# 1. 盘口分析器
# ==========================================
class OrderBookAnalyzer:
    def analyze(self, orderbook):
        if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
            return 0.0, 0.0
        TARGET_DEPTH = 20
        bids = orderbook['bids'][:TARGET_DEPTH]
        asks = orderbook['asks'][:TARGET_DEPTH]
        if not bids or not asks: return 0.0, 0.0
        decay = 0.9
        w_bid_vol = sum(o[1] * (TARGET_DEPTH - i) / TARGET_DEPTH for i, o in enumerate(bids))
        w_ask_vol = sum(o[1] * (TARGET_DEPTH - i) / TARGET_DEPTH for i, o in enumerate(asks))
        total_vol = w_bid_vol + w_ask_vol + 1e-9
        obi = (w_bid_vol - w_ask_vol) / total_vol
        mid_price = (bids[0][0] + asks[0][0]) / 2
        spread_pct = (asks[0][0] - bids[0][0]) / mid_price
        return obi, spread_pct


# ==========================================
# 2. 状态机
# ==========================================
class StateMachine:
    def __init__(self):
        self.state, self.color = "INIT", Fore.WHITE
        self.ob_analyzer = OrderBookAnalyzer()
        self.last_cluster = 5

    def determine_regime(self, range_pct, vol_expl):
        if range_pct < 0.0015:
            self.state, self.color = "💤 NOISE", Fore.WHITE
        elif vol_expl > 1.5:
            self.state, self.color = "💥 BREAKOUT", Fore.MAGENTA
        else:
            if vol_expl > 1.05:
                self.state, self.color = "💥 BREAKOUT", Fore.MAGENTA
            else:
                self.state, self.color = "🦀 RANGE", Fore.YELLOW
        return self.state, self.color

    def get_entry_signal(self, analysis_data, current_price):
        if not analysis_data: return 0, Config.MIN_LEVERAGE

        if 'obi' in analysis_data and 'spread_pct' in analysis_data:
            obi = analysis_data['obi']
            spread_pct = analysis_data['spread_pct']
        else:
            obi, spread_pct = self.ob_analyzer.analyze(analysis_data.get('orderbook', {}))

        features = analysis_data['features']
        # 这里 ai_conf 已经是 双核平均值
        ai_dir, ai_conf = analysis_data['ai_prediction']
        cluster_data = analysis_data.get('cluster', (5, 0.0))
        cluster_id = cluster_data[0]

        sig, lev = 0, Config.MIN_LEVERAGE

        # Spread 过滤
        if (not getattr(Config, "BACKTEST_MODE", False)) and spread_pct > Config.MAX_SPREAD_PCT:
            print(f"⛔ Spread过大: {spread_pct:.5f}")
            return 0, lev

        if cluster_id == 5:
            return 0, lev

        if cluster_id != self.last_cluster:
            print(f" 🔄 簇变更: {self.last_cluster} -> {cluster_id}")
            self.last_cluster = cluster_id

        # 恢复默认阈值 0.4 (或更高，随你设定)
        target_conf = 0.4
        is_signal = False
        match_reason = ""

        # === [回滚操作] 恢复为标准策略，不使用激进的 OBI 判定 ===
        if cluster_id == 0:
            if ai_dir != 0 and ai_conf > target_conf:
                sig, lev, is_signal = ai_dir, 5, True
                match_reason = f"簇0波动+AI信心{ai_conf:.2f}"

        elif cluster_id == 1:
            # 取消了 "if ai_dir == 0 and obi > 0.2" 的逻辑
            if ai_dir == 1 and ai_conf > target_conf:
                sig, lev, is_signal = 1, 5, True
                match_reason = f"簇1涨+AI看涨{ai_conf:.2f}"

        elif cluster_id == 2:
            if ai_dir == -1 and ai_conf > target_conf:
                sig, lev, is_signal = -1, 5, True
                match_reason = f"簇2跌+AI看跌{ai_conf:.2f}"

        elif cluster_id == 3:
            if ai_dir == 1 and ai_conf > target_conf:
                sig, lev, is_signal = 1, 5, True
                match_reason = f"簇3大涨+AI看涨{ai_conf:.2f}"

        elif cluster_id == 4:
            if ai_dir == -1 and ai_conf > target_conf:
                sig, lev, is_signal = -1, 5, True
                match_reason = f"簇4大跌+AI看跌{ai_conf:.2f}"

        if is_signal:
            logger.info(f"信号生成: {match_reason}")

        return sig, lev


# ==========================================
# 3. 策略大脑
# ==========================================
class StrategyBrain:
    def __init__(self):
        self.rf_classifier = RandomForestClassifier()
        self.state_machine = StateMachine()
        self.cluster_analyzer = KMeansClusterAnalyzer()
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
        # 将 numpy 展平转 dict
        x = {f"f{i}": v for i, v in enumerate(features.flatten())}
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