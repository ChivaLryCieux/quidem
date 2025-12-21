import numpy as np
import pandas as pd
from river import compose, preprocessing
from river.forest import ARFClassifier as AdaptiveRandomForestClassifier
from colorama import Fore

from config import Config
from math_tools import MathUtils, HInfinityFilter1D, OnlineEGARCH, WaveletAnalyzer, MomentumCalculator, RealizedVolatilityCalculator


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
# 2. 随机森林分类器 - 负责机器学习功能
# ==========================================
class RandomForestClassifier:
    def __init__(self):
        self.hf = HInfinityFilter1D(gamma=0.13)
        # 添加两个额外的H无穷滤波器，分别用于1m和15m预测
        self.hf_predictor_1m = HInfinityFilter1D(gamma=0.13)
        self.hf_predictor_15m = HInfinityFilter1D(gamma=0.13)
        
        self.egarch, self.wavelet = OnlineEGARCH(), WaveletAnalyzer()
        self.momentum_calc = MomentumCalculator()
        self.volatility_calc = RealizedVolatilityCalculator()
        self.rf_model = compose.Pipeline(
            preprocessing.StandardScaler(),
            AdaptiveRandomForestClassifier(n_models=10, seed=42)
        )
        self.prev_features = None
        self.history = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        self.history_15m = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        self.last_price = 0.0
        self.price_prediction_diff = 0.0  # 存储15m预测与1m预测的差值
        self.price_history_1m = []  # 存储1分钟价格历史，用于预测
        self.price_history_15m = []  # 存储15分钟价格历史，用于预测

    def ingest_candle(self, item, timeframe='1m'):
        # item 格式: [timestamp, open, high, low, close, volume]
        row = pd.DataFrame([{'timestamp': item[0], 'open': float(item[1]), 'high': float(item[2]),
                             'low': float(item[3]), 'close': float(item[4]), 'volume': float(item[5])}])
        curr_price = float(item[4])
        
        if timeframe == '1m':
            if self.history.empty:
                self.history = row
            else:
                # 如果时间戳相同，更新最后一行（WS推送实时变动）
                if self.history.iloc[-1]['timestamp'] == item[0]:
                    self.history.iloc[-1] = row.iloc[0]
                # 如果是新时间戳，追加
                elif item[0] > self.history.iloc[-1]['timestamp']:
                    self.history = pd.concat([self.history, row], ignore_index=True)

            self.history = self.history.iloc[-100:]  # 保持滑动窗口
            
            # 更新1分钟H无穷滤波器和价格历史
            self.hf_predictor_1m.update(curr_price)
            self.price_history_1m.append(curr_price)
            if len(self.price_history_1m) > 100:  # 保持最近100个价格点
                self.price_history_1m.pop(0)
            
            # 更新波动率计算器
            self.volatility_calc.update(curr_price)
            
        elif timeframe == '15m':
            if self.history_15m.empty:
                self.history_15m = row
            else:
                # 如果时间戳相同，更新最后一行（WS推送实时变动）
                if self.history_15m.iloc[-1]['timestamp'] == item[0]:
                    self.history_15m.iloc[-1] = row.iloc[0]
                # 如果是新时间戳，追加
                elif item[0] > self.history_15m.iloc[-1]['timestamp']:
                    self.history_15m = pd.concat([self.history_15m, row], ignore_index=True)

            self.history_15m = self.history_15m.iloc[-100:]  # 保持滑动窗口
            
            # 更新15分钟H无穷滤波器和价格历史
            self.hf_predictor_15m.update(curr_price)
            self.price_history_15m.append(curr_price)
            if len(self.price_history_15m) > 100:  # 保持最近100个价格点
                self.price_history_15m.pop(0)
            
            # 更新价格预测差值
            self._update_price_prediction_diff()

    def extract_features(self):
        df = self.history
        if len(df) < 30: return None
        curr_price = df['close'].iloc[-1]
        log_ret = np.log(curr_price / self.last_price) if self.last_price else 0.0
        self.last_price = curr_price

        # 仅当价格变化时更新复杂滤波器，避免重复计算
        eg_vol = self.egarch.update(log_ret)

        hf_val = self.hf.update(curr_price)
        wav_res, wav_eng = self.wavelet.process(df['close'].values)

        rsi = MathUtils.calc_rsi(df['close']).iloc[-1]
        atr = MathUtils.calc_atr(df).iloc[-1]

        curr_tr = max(df['high'].iloc[-1] - df['low'].iloc[-1], abs(df['high'].iloc[-1] - df['close'].iloc[-2]))
        prev_atr = MathUtils.calc_atr(df.iloc[:-1]).iloc[-1]
        vol_expl = curr_tr / (prev_atr + 1e-9)
        range_pct = (df['high'].iloc[-1] - df['low'].iloc[-1]) / df['open'].iloc[-1]

        hf_diff = (curr_price - hf_val) / hf_val
        
        # 计算四个时间段的对数动量
        momentums = self.momentum_calc.update(curr_price)
        mom_5 = momentums.get('T_5', 0.0) if momentums.get('T_5') is not None else 0.0
        mom_10 = momentums.get('T_10', 0.0) if momentums.get('T_10') is not None else 0.0
        mom_25 = momentums.get('T_25', 0.0) if momentums.get('T_25') is not None else 0.0
        mom_50 = momentums.get('T_50', 0.0) if momentums.get('T_50') is not None else 0.0

        # 计算四个时间段的已实现波动率
        volatilities = self.volatility_calc.update(curr_price)
        vol_5 = volatilities.get('T_5', 0.0) if volatilities.get('T_5') is not None else 0.0
        vol_10 = volatilities.get('T_10', 0.0) if volatilities.get('T_10') is not None else 0.0
        vol_25 = volatilities.get('T_25', 0.0) if volatilities.get('T_25') is not None else 0.0
        vol_50 = volatilities.get('T_50', 0.0) if volatilities.get('T_50') is not None else 0.0

        features = np.array([
            hf_diff,
            eg_vol * 1000,
            rsi / 100.0,
            vol_expl,
            range_pct,
            (curr_price - wav_res) / curr_price * 100,
            np.log1p(wav_eng),
            mom_5,
            mom_10,
            mom_25,
            mom_50,
            vol_5,
            vol_10,
            vol_25,
            vol_50,
            self.price_prediction_diff  # 价格预测差值
        ]).reshape(1, -1)

        return {
            'features': features, 'price': curr_price, 'atr': atr, 'rsi': rsi,
            'vol_explosion': vol_expl, 'hf_diff': hf_diff, 'wavelet_energy': wav_eng,
            'mom_5': mom_5, 'mom_10': mom_10, 'mom_25': mom_25, 'mom_50': mom_50,
            'vol_5': vol_5, 'vol_10': vol_10, 'vol_25': vol_25, 'vol_50': vol_50,
            'range_pct': range_pct, 'price_prediction_diff': self.price_prediction_diff,
            'momentum_values': momentums,  # 添加完整的动量字典
            'volatility_values': volatilities  # 添加完整的波动率字典
        }

    def _update_price_prediction_diff(self):
        """更新15分钟预测与1分钟预测的差值（价格差值，非比例）"""
        try:
            # 获取当前滤波器输出作为基础预测
            pred_15m_base = self.hf_predictor_15m.x
            pred_1m_base = self.hf_predictor_1m.x
            
            # 如果价格历史不足，使用滤波器输出差值
            if len(self.price_history_1m) < 2 or len(self.price_history_15m) < 2:
                self.price_prediction_diff = pred_15m_base - pred_1m_base
                return
            
            # 计算1分钟和15分钟的趋势
            trend_1m = (self.price_history_1m[-1] - self.price_history_1m[-2]) / (self.price_history_1m[-2] + 1e-9)
            trend_15m = (self.price_history_15m[-1] - self.price_history_15m[-2]) / (self.price_history_15m[-2] + 1e-9)
            
            # 预测15分钟后的价格（使用15分钟趋势，但转换为1分钟尺度）
            pred_15m = pred_15m_base * (1 + trend_15m * 15)
            
            # 预测1分钟后的价格
            pred_1m = pred_1m_base * (1 + trend_1m * 1)
            
            # 计算价格差值（非比例）
            self.price_prediction_diff = pred_15m - pred_1m
        except Exception as e:
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
        return (1, probs.get(1, 0.0)) if probs.get(1, 0.0) > probs.get(-1, 0.0) else (-1, probs.get(-1, 0.0))


# ==========================================
# 3. K均值聚类分析器
# ==========================================
class KMeansClusterAnalyzer:
    def __init__(self, n_clusters=5):
        self.n_clusters = n_clusters
        self.feature_names = ['mom_5', 'mom_10', 'mom_25', 'mom_50', 'vol_5', 'vol_10', 'vol_25', 'vol_50']
        # 预定义的质心，每个质心包含8个特征（4个动量+4个波动率）
        self.centroids = {
            0: [-0.0077, -0.0136, -0.0246, -0.0321, 0.0048, 0.0048, 0.0048, 0.0045],  # 簇0的质心：[mom_5, mom_10, mom_25, mom_50, vol_5, vol_10, vol_25, vol_50]
            1: [-0.0005, -0.0007, -0.0007, -0.0004, 0.0022, 0.0023, 0.0026, 0.0028],  # 簇1的质心
            2: [-0.0625, -0.1557, -0.1866, -0.2102, 0.0709, 0.0770, 0.0484, 0.0342],  # 簇2的质心
            3: [0.0074, 0.0121, 0.0193, 0.0219, 0.0042, 0.0044, 0.0043, 0.0043],  # 簇3的质心
            4: [0.0628, 0.1556, 0.1866, 0.2102, 0.0708, 0.0769, 0.0484, 0.0342]   # 簇4的质心
        }
        self.is_initialized = False  # 标记是否已经进行过有效聚类
        self.last_valid_cluster = 5  # 初始状态为簇5
        self.initialized = True
        
    def predict_cluster(self, momentum_values, volatility_values):
        """根据动量和波动率值预测当前市场所属的聚类"""
        if not momentum_values or not volatility_values:
            # 如果还没有进行过有效聚类，保持簇5状态
            if not self.is_initialized:
                return 5, 999.0
            # 如果已经初始化过，返回上次有效的聚类
            else:
                return self.last_valid_cluster, 0.0
            
        # 构建特征向量
        features = []
        for name in self.feature_names[:4]:  # 动量特征
            features.append(momentum_values.get(name, 0.0))
        for name in self.feature_names[4:]:  # 波动率特征
            features.append(volatility_values.get(name, 0.0))
            
        feature_vector = np.array(features)
        
        # 计算到每个质心的距离
        min_distance = float('inf')
        best_cluster = 0
        
        for cluster_id, centroid in self.centroids.items():
            # 计算欧氏距离
            distance = np.linalg.norm(feature_vector - centroid)
            if distance < min_distance:
                min_distance = distance
                best_cluster = cluster_id
        
        # 一旦获得有效聚类，标记为已初始化，并记录有效聚类
        if best_cluster != 5:
            self.is_initialized = True
            self.last_valid_cluster = best_cluster
            
        return best_cluster, min_distance


# ==========================================
# 4. 状态机 - 负责市场状态判断和交易信号生成
# ==========================================
class StateMachine:
    def __init__(self):
        self.state, self.color = "INIT", Fore.WHITE
        self.ob_analyzer = OrderBookAnalyzer()
        self.last_cluster = 5  # 初始值记为5

    def determine_regime(self, range_pct, vol_expl):
        prev = self.state
        if range_pct < 0.0015:
            self.state, self.color = "💤 NOISE", Fore.WHITE
        elif vol_expl > 1.5:
            self.state, self.color = "💥 BREAKOUT", Fore.MAGENTA
        else:
            if vol_expl > 1.05:
                self.state, self.color = "💥 BREAKOUT", Fore.MAGENTA
            else:
                # 默认为震荡状态，除非有明确的趋势信号
                self.state, self.color = "🦀 RANGE", Fore.YELLOW
        return self.state, self.color

    def get_entry_signal(self, analysis_data, current_price):
        """
        根据新的状态机判定机制计算交易信号
        返回: (signal, leverage)
        signal: 1 (Buy), -1 (Sell), 0 (None)
        """
        # 获取订单簿分析（如果已计算则使用已有值，否则计算）
        if 'obi' in analysis_data and 'spread_pct' in analysis_data:
            obi = analysis_data['obi']
            spread_pct = analysis_data['spread_pct']
        else:
            obi, spread_pct = self.ob_analyzer.analyze(analysis_data.get('orderbook', {}))
        
        features = analysis_data['features']
        ai_dir, ai_conf = analysis_data['ai_prediction']
        
        # 获取价格预测差值
        price_pred_diff = analysis_data.get('price_prediction_diff', 0.0)

        sig = 0
        lev = Config.MIN_LEVERAGE
        regime = self.state

        # 1. 基础过滤 (Spread & ATR)
        if spread_pct > Config.MAX_SPREAD_PCT:
            return 0, lev
        if analysis_data['atr'] < current_price * Config.MIN_ATR_PCT:
            return 0, lev

        # 1. 硬阈值过滤器
        # 如果价差范围在负最小止盈距离和正最小止盈距离之间，不开仓
        if -Config.MIN_TP_DISTANCE <= price_pred_diff <= Config.MIN_TP_DISTANCE:
            return 0, lev

        # 2. 聚类分析器
        # 获取当前聚类
        current_cluster_data = analysis_data.get('cluster', (5, 0.0))
        cluster_id = current_cluster_data[0]
        cluster_distance = current_cluster_data[1]
        
        # 状态机逻辑：管理簇5到正常簇的转换
        if self.last_cluster == 5:
            if cluster_id == 5:
                print(f"初始状态: 等待首次聚类分析...")
                return 0, lev
            else:
                print(f" 🔄 聚类初始化: 簇5 → 簇{cluster_id} (距离: {cluster_distance:.4f})")
                self.last_cluster = cluster_id
        else:
            if cluster_id == 5:
                print(f" ⚠️  聚类异常返回簇5，保持上次聚类簇{self.last_cluster}")
                cluster_id = self.last_cluster
            elif cluster_id != self.last_cluster:
                print(f" 🔄 聚类变化: 簇{self.last_cluster} → 簇{cluster_id} (距离: {cluster_distance:.4f})")
                self.last_cluster = cluster_id
            else:
                print(f"聚类稳定: 保持在簇{cluster_id}")
        
        print(f"当前状态: Cluster={cluster_id}, Last={self.last_cluster}, Distance={cluster_distance:.4f}")
            
        # 聚类0 跌：如果价差为负且AI方向为做空，信心大于特定值，5倍做空
        if cluster_id == 0 and price_pred_diff < 0 and ai_dir == -1 and ai_conf > 0.51:
            sig = -1
            lev = 5
        # 聚类1 跌+平：如果价差为负且AI方向为做空，信心大于特定值，5倍做空
        elif cluster_id == 1 and price_pred_diff < 0 and ai_dir == -1 and ai_conf > 0.51:
            sig = -1
            lev = 5
        # 聚类2 暴跌：如果价差为负且AI方向为做空，信心大于特定值，5倍做空
        elif cluster_id == 2 and price_pred_diff < 0 and ai_dir == -1 and ai_conf > 0.51:
            sig = -1
            lev = 5
        # 聚类3：涨 如果价差为正且AI方向为做多，信心大于特定值，5倍做多
        elif cluster_id == 3 and price_pred_diff > 0 and ai_dir == 1 and ai_conf > 0.51:
            sig = 1
            lev = 5
        # 聚类4：由暴跌转暴涨 如果价差为正且AI方向为做多，信心大于特定值，5倍做多
        elif cluster_id == 4 and price_pred_diff > 0 and ai_dir == 1 and ai_conf > 0.51:
            sig = 1
            lev = 5
        
        # 更新上一聚类记录器
        if sig != 0:
            self.last_cluster = cluster_id

        return sig, lev


# ==========================================
# 5. 策略大脑 - 协调随机森林、状态机和聚类分析
# ==========================================
class StrategyBrain:
    def __init__(self):
        self.rf_classifier = RandomForestClassifier()
        self.state_machine = StateMachine()
        self.cluster_analyzer = KMeansClusterAnalyzer()  # 添加聚类分析器
        self.state = self.state_machine.state
        self.color = self.state_machine.color

    def ingest_candle(self, item, timeframe='1m'):
        self.rf_classifier.ingest_candle(item, timeframe)

    def analyze(self, orderbook=None):
        # 提取特征
        feature_data = self.rf_classifier.extract_features()
        if not feature_data:
            return None
            
        # 添加订单簿数据
        feature_data['orderbook'] = orderbook
        
        # 分析订单簿获取OBI和spread_pct
        obi, spread_pct = self.state_machine.ob_analyzer.analyze(orderbook)
        feature_data['obi'] = obi
        feature_data['spread_pct'] = spread_pct
        
        # 确定市场状态
        self.state, self.color = self.state_machine.determine_regime(
            feature_data['range_pct'], 
            feature_data['vol_explosion']
        )
        
        # AI预测
        ai_dir, ai_conf = self.rf_classifier.predict(feature_data['features'])
        feature_data['ai_prediction'] = (ai_dir, ai_conf)
        
        # 聚类分析
        momentum_values = feature_data.get('momentum_values', {})
        volatility_values = feature_data.get('volatility_values', {})
        cluster_id, cluster_distance = self.cluster_analyzer.predict_cluster(momentum_values, volatility_values)
        feature_data['cluster'] = (cluster_id, cluster_distance)
        
        return feature_data

    def train_ai(self, features, label):
        self.rf_classifier.train(features, label)

    def get_entry_signal(self, analysis_data, current_price):
        return self.state_machine.get_entry_signal(analysis_data, current_price)
    
    def predict_cluster(self, analysis_data):
        """
        根据分析数据预测所属的簇
        返回: (cluster_id, distance) - 簇ID和到质心的距离
        """
        momentum_values = analysis_data.get('momentum_values', {})
        volatility_values = analysis_data.get('volatility_values', {})
        
        return self.cluster_analyzer.predict_cluster(momentum_values, volatility_values)