import numpy as np
import pandas as pd
import os
import sys
from river import compose, preprocessing
from river.forest import ARFClassifier as AdaptiveRandomForestClassifier
from colorama import Fore

from config import Config
from math_tools import MathUtils, HInfinityFilter1D, OnlineEGARCH, WaveletAnalyzer, MomentumCalculator, \
    RealizedVolatilityCalculator, FractalAnalysis, OnlineBOCPD


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
        w_bid_vol = sum(o[1] * (TARGET_DEPTH - i) / TARGET_DEPTH for i, o in enumerate(bids))
        w_ask_vol = sum(o[1] * (TARGET_DEPTH - i) / TARGET_DEPTH for i, o in enumerate(asks))
        total_vol = w_bid_vol + w_ask_vol + 1e-9
        obi = (w_bid_vol - w_ask_vol) / total_vol
        mid_price = (bids[0][0] + asks[0][0]) / 2
        spread_pct = (asks[0][0] - bids[0][0]) / mid_price
        return obi, spread_pct


# ==========================================
# 2. 随机森林分类器 (已修复动量计算逻辑)
# ==========================================
class RandomForestClassifier:
    def __init__(self):
        self.hf = HInfinityFilter1D(gamma=0.13)
        self.hf_predictor_1m = HInfinityFilter1D(gamma=0.13)
        self.hf_predictor_15m = HInfinityFilter1D(gamma=0.13)

        self.egarch, self.wavelet = OnlineEGARCH(), WaveletAnalyzer()
        self.momentum_calc = MomentumCalculator()
        self.volatility_calc = RealizedVolatilityCalculator()
        self.fractal_analysis = FractalAnalysis(window_size=30)
        self.bocpd = OnlineBOCPD(hazard=1 / 100, max_lags=200)

        self.atr_15m_last = 0.0
        self.rf_model = compose.Pipeline(
            preprocessing.StandardScaler(),
            AdaptiveRandomForestClassifier(n_models=10, seed=42)
        )
        self.prev_features = None
        self.history = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        self.history_15m = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        self.last_price = 0.0
        self.price_prediction_diff = 0.0
        self.price_history_1m = []
        self.price_history_15m = []

        # 缓存数据
        self.cached_analysis_data = None

    def ingest_candle(self, item, timeframe='1m'):
        # item: [timestamp, open, high, low, close, volume]
        row = pd.DataFrame([{'timestamp': item[0], 'open': float(item[1]), 'high': float(item[2]),
                             'low': float(item[3]), 'close': float(item[4]), 'volume': float(item[5])}])
        curr_price = float(item[4])

        if timeframe == '1m':
            # 维护 1m K线历史
            if self.history.empty:
                self.history = row
            else:
                if self.history.iloc[-1]['timestamp'] == item[0]:
                    self.history.iloc[-1] = row.iloc[0]  # 更新当前K线
                elif item[0] > self.history.iloc[-1]['timestamp']:
                    self.history = pd.concat([self.history, row], ignore_index=True)  # 新K线

            self.history = self.history.iloc[-100:]  # 保持窗口

            # 更新无状态的实时滤波器 (Tick级更新)
            self.hf_predictor_1m.update(curr_price)
            self.volatility_calc.update(curr_price)
            self.fractal_analysis.update(curr_price)
            self.bocpd.update(curr_price)

            # 更新价格历史队列
            self.price_history_1m.append(curr_price)
            if len(self.price_history_1m) > 100: self.price_history_1m.pop(0)

            # === 触发特征重算并缓存 ===
            self._recalculate_and_cache_features(curr_price)

        elif timeframe == '15m':
            if self.history_15m.empty:
                self.history_15m = row
            else:
                if self.history_15m.iloc[-1]['timestamp'] == item[0]:
                    self.history_15m.iloc[-1] = row.iloc[0]
                elif item[0] > self.history_15m.iloc[-1]['timestamp']:
                    self.history_15m = pd.concat([self.history_15m, row], ignore_index=True)

            self.history_15m = self.history_15m.iloc[-100:]

            self.hf_predictor_15m.update(curr_price)
            self.price_history_15m.append(curr_price)
            if len(self.price_history_15m) > 100: self.price_history_15m.pop(0)

            self._update_price_prediction_diff()

            try:
                if len(self.history_15m) >= 15:
                    self.atr_15m_last = float(MathUtils.calc_atr(self.history_15m.iloc[-30:]).iloc[-1])
            except Exception:
                self.atr_15m_last = 0.0

    def _recalculate_and_cache_features(self, curr_price):
        if len(self.history) < 30:
            self.cached_analysis_data = None
            return

        # 1. 基础指标
        log_ret = np.log(curr_price / self.last_price) if self.last_price > 0 else 0.0
        self.last_price = curr_price

        eg_vol = self.egarch.update(log_ret)
        hf_val = self.hf.update(curr_price)
        wav_res, wav_eng = self.wavelet.process(self.history['close'].values)
        rsi = MathUtils.calc_rsi(self.history['close']).iloc[-1]
        atr = MathUtils.calc_atr(self.history).iloc[-1]

        curr_tr = max(self.history['high'].iloc[-1] - self.history['low'].iloc[-1],
                      abs(self.history['high'].iloc[-1] - self.history['close'].iloc[-2]))
        prev_atr = MathUtils.calc_atr(self.history.iloc[:-1]).iloc[-1]
        vol_expl = curr_tr / (prev_atr + 1e-9)
        range_pct = (self.history['high'].iloc[-1] - self.history['low'].iloc[-1]) / self.history['open'].iloc[-1]
        hf_diff = (curr_price - hf_val) / hf_val

        # 2. 动量计算 (基于历史列表)
        prices_list = self.history['close'].tolist()
        momentums = self.momentum_calc.calculate_all_momentums(prices_list)

        # 3. 波动率计算 (基于 DataFrame，修复点)
        # 直接传入当前的 history DataFrame
        volatilities = self.volatility_calc.calculate_from_history(self.history)

        # 4. 其他特征
        hurst = self.fractal_analysis.update(curr_price)
        cp_prob = self.bocpd.update(curr_price)

        # 辅助函数：安全获取字典值
        def get_val(d, k): return d.get(k, 0.0) if d.get(k) is not None else 0.0

        # 注意：这里我们提取用于 feature 向量的值，虽然下面存了完整字典
        # 但为了避免 RF 模型报错，这里还是按顺序解包
        mom_5 = get_val(momentums, 'T_5')
        mom_10 = get_val(momentums, 'T_10')
        mom_25 = get_val(momentums, 'T_25')
        mom_50 = get_val(momentums, 'T_50')

        vol_5 = get_val(volatilities, 'T_5')
        vol_10 = get_val(volatilities, 'T_10')
        vol_25 = get_val(volatilities, 'T_25')
        vol_50 = get_val(volatilities, 'T_50')

        features = np.array([
            hf_diff, eg_vol * 1000, rsi / 100.0, vol_expl, range_pct,
                     (curr_price - wav_res) / curr_price * 100, np.log1p(wav_eng),
            mom_5, mom_10, mom_25, mom_50,
            vol_5, vol_10, vol_25, vol_50,
            self.price_prediction_diff, hurst, cp_prob
        ]).reshape(1, -1)

        self.cached_analysis_data = {
            'features': features, 'price': curr_price, 'atr': atr, 'rsi': rsi,
            'vol_explosion': vol_expl, 'hf_diff': hf_diff, 'wavelet_energy': wav_eng,
            'mom_5': mom_5, 'mom_10': mom_10, 'mom_25': mom_25, 'mom_50': mom_50,
            'vol_5': vol_5, 'vol_10': vol_10, 'vol_25': vol_25, 'vol_50': vol_50,
            'range_pct': range_pct, 'price_prediction_diff': self.price_prediction_diff,
            'momentum_values': momentums,
            'volatility_values': volatilities,  # 存入完整的波动率字典
            'hurst_exponent': hurst,
            'change_point_prob': cp_prob
        }

    def extract_features(self):
        # 直接返回缓存，不再重复计算
        return self.cached_analysis_data

    def _update_price_prediction_diff(self):
        try:
            pred_15m_base = self.hf_predictor_15m.x
            pred_1m_base = self.hf_predictor_1m.x
            if len(self.price_history_1m) < 2 or len(self.price_history_15m) < 2:
                self.price_prediction_diff = pred_15m_base - pred_1m_base
                return
            trend_1m = (self.price_history_1m[-1] - self.price_history_1m[-2]) / (self.price_history_1m[-2] + 1e-9)
            trend_15m = (self.price_history_15m[-1] - self.price_history_15m[-2]) / (self.price_history_15m[-2] + 1e-9)
            pred_15m = pred_15m_base * (1 + trend_15m * 15)
            pred_1m = pred_1m_base * (1 + trend_1m * 1)
            self.price_prediction_diff = pred_15m - pred_1m
        except Exception:
            self.price_prediction_diff = 0.0

    def train(self, features, label):
        curr_x = {f"f{i}": v for i, v in enumerate(features.flatten())}
        if self.prev_features:
            self.rf_model.learn_one(self.prev_features, label)
        self.prev_features = curr_x

    def predict(self, features):
        x = {f"f{i}": v for i, v in enumerate(features.flatten())}
        probs = self.rf_model.predict_proba_one(x)
        if not probs: return 0, 0.0
        prob_1 = probs.get(1, 0.0)
        prob_minus1 = probs.get(-1, 0.0)
        prob_0 = probs.get(0, 0.0)
        if prob_1 >= prob_minus1 and prob_1 >= prob_0:
            return 1, prob_1
        elif prob_minus1 >= prob_1 and prob_minus1 >= prob_0:
            return -1, prob_minus1
        else:
            return 0, prob_0


# ==========================================
# 3. K均值聚类分析器
# ==========================================
class KMeansClusterAnalyzer:
    def __init__(self, n_clusters=5):
        self.n_clusters = n_clusters
        # 注意：这里不需要改，feature_names 只是内部用来对应特征向量顺序的
        self.feature_names = ['mom_5', 'mom_10', 'mom_25', 'mom_50', 'vol_5', 'vol_10', 'vol_25', 'vol_50']

        # ... (加载 CSV 的代码保持不变) ...
        # 请保留原有的 __init__ 中加载 CSV 的代码

        self.is_initialized = False
        self.last_valid_cluster = 5

        # 加载CSV部分省略，请保留原样...
        centroids_path = os.path.join(os.path.dirname(__file__), 'centroids.csv')
        if not os.path.exists(centroids_path):
            print(f"{Fore.RED}错误: 未找到 centroids.csv 文件{Fore.RESET}")
            sys.exit(1)
        try:
            centroids_df = pd.read_csv(centroids_path, index_col=0)
            self.centroids = {}
            for cluster_id in range(len(centroids_df)):
                row = centroids_df.iloc[cluster_id]
                self.centroids[cluster_id] = [
                    row.get('log_mom_5', 0), row.get('log_mom_10', 0),
                    row.get('log_mom_25', 0), row.get('log_mom_50', 0),
                    row.get('vol_5', 0), row.get('vol_10', 0),
                    row.get('vol_25', 0), row.get('vol_50', 0)
                ]
        except Exception:
            sys.exit(1)

    def predict_cluster(self, momentum_values, volatility_values):
        """
        momentum_values: 字典，包含键 {'T_5', 'T_10', ...}
        volatility_values: 字典，包含键 {'T_5', 'T_10', ...}
        """
        if not momentum_values or not volatility_values:
            return (self.last_valid_cluster, 0.0) if self.is_initialized else (5, 999.0)

        features = []

        # === 修复点：正确映射键名 ===
        # 我们知道 MomentumCalculator 和 VolatilityCalculator 现在的输出键名是 'T_5' 这种格式
        periods = [5, 10, 25, 50]

        # 1. 提取动量 (已是 Log 值)
        for T in periods:
            key = f"T_{T}"
            val = momentum_values.get(key)
            if val is None: val = 0.0
            features.append(val)

        # 2. 提取波动率
        for T in periods:
            key = f"T_{T}"
            val = volatility_values.get(key)
            if val is None: val = 0.0
            features.append(val)

        feature_vector = np.array(features)

        # 简单过滤：如果特征全为0，说明数据还没准备好，保持 Cluster 5
        if np.all(feature_vector == 0):
            return (self.last_valid_cluster, 0.0) if self.is_initialized else (5, 999.0)

        min_distance = float('inf')
        best_cluster = 5

        for cluster_id, centroid in self.centroids.items():
            dist = np.linalg.norm(feature_vector - np.array(centroid))
            if dist < min_distance:
                min_distance = dist
                best_cluster = cluster_id

        # 只要找到了有效簇，就更新状态
        if best_cluster != 5:
            self.is_initialized = True
            self.last_valid_cluster = best_cluster

        return best_cluster, min_distance


# ==========================================
# 4. 状态机
# ==========================================
class StateMachine:
    def __init__(self):
        self.state, self.color = "INIT", Fore.WHITE
        self.ob_analyzer = OrderBookAnalyzer()
        self.last_cluster = 5

    def determine_regime(self, range_pct, vol_expl):
        # 逻辑保持不变...
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
        # 逻辑保持不变...
        if not analysis_data: return 0, Config.MIN_LEVERAGE

        if 'obi' in analysis_data and 'spread_pct' in analysis_data:
            obi = analysis_data['obi']
            spread_pct = analysis_data['spread_pct']
        else:
            obi, spread_pct = self.ob_analyzer.analyze(analysis_data.get('orderbook', {}))

        features = analysis_data['features']
        ai_dir, ai_conf = analysis_data['ai_prediction']
        cluster_data = analysis_data.get('cluster', (5, 0.0))
        cluster_id = cluster_data[0]

        sig, lev = 0, Config.MIN_LEVERAGE

        # 回测/实盘 过滤
        if (not getattr(Config, "BACKTEST_MODE", False)) and spread_pct > Config.MAX_SPREAD_PCT:
            print(f"⛔ Spread过大: {spread_pct:.5f}")
            return 0, lev

        if cluster_id == 5:
            return 0, lev

        if cluster_id != self.last_cluster:
            print(f" 🔄 簇变更: {self.last_cluster} -> {cluster_id}")
            self.last_cluster = cluster_id

        target_conf = 0.4
        is_signal = False
        match_reason = ""

        # 信号映射逻辑 (保持您原有的逻辑)
        if cluster_id == 0:
            if ai_dir != 0 and ai_conf > target_conf:
                sig, lev, is_signal = ai_dir, 5, True
                match_reason = f"簇0波动+AI信心{ai_conf:.2f}"
        elif cluster_id == 1:
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
            print(f"✅ 信号生成: {match_reason}")

        return sig, lev


# ==========================================
# 5. 策略大脑
# ==========================================
class StrategyBrain:
    def __init__(self):
        self.rf_classifier = RandomForestClassifier()
        self.state_machine = StateMachine()
        self.cluster_analyzer = KMeansClusterAnalyzer()
        self.state = self.state_machine.state
        self.color = self.state_machine.color

    def ingest_candle(self, item, timeframe='1m'):
        self.rf_classifier.ingest_candle(item, timeframe)

    def analyze(self, orderbook=None):
        # 直接获取缓存的特征
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

        # 聚类预测
        cluster_id, cluster_dist = self.cluster_analyzer.predict_cluster(
            feature_data.get('momentum_values'),
            feature_data.get('volatility_values')
        )
        feature_data['cluster'] = (cluster_id, cluster_dist)

        return feature_data

    def train_ai(self, features, label):
        self.rf_classifier.train(features, label)

    def get_entry_signal(self, analysis_data, current_price):
        return self.state_machine.get_entry_signal(analysis_data, current_price)