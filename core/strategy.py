import numpy as np
import pandas as pd
import os
import sys
from colorama import Fore, Style

# ==========================================
# River 0.23.0 适配专用导入块
# ==========================================
try:
    import river
    from river import compose
    from river import preprocessing, linear_model, optim

    # River 0.23.0 使用 AdaptiveRandomForestClassifier
    try:
        from river.forest import AdaptiveRandomForestClassifier

        print(f"{Fore.GREEN}[System] River {river.__version__} 环境检测正常{Style.RESET_ALL}")
    except ImportError:
        from river.forest import ARFClassifier as AdaptiveRandomForestClassifier

except ImportError as e:
    print(f"{Fore.RED}错误: River 库加载失败。虽然检测到已安装，但导入出错。{Style.RESET_ALL}")
    print(e)
    sys.exit(1)
# ==========================================

from config import Config
from math_tools import MathUtils, HInfinityFilter1D, OnlineEGARCH, WaveletAnalyzer, MomentumCalculator, \
    RollingVolatilityCalculator, FractalAnalysis, OnlineBOCPD


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
# 2. 自适应双核模型 (Random Forest + Linear)
# ==========================================
class RandomForestClassifier:
    def __init__(self):
        # --- 大脑 1: 随机森林 (稳健派，擅长复杂结构) ---
        self.rf_model = compose.Pipeline(
            preprocessing.StandardScaler(),
            AdaptiveRandomForestClassifier(
                n_models =30,
                max_depth =12,
                split_criterion ="hellinger",
                grace_period = 50,
                lambda_value = 6,
                seed =42
            )
        )

        # --- 大脑 2: 在线线性模型 (激进派，擅长线性趋势) ---
        # 使用逻辑回归 (Logistic Regression) + 随机梯度下降 (SGD)
        self.linear_model = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.LogisticRegression(optimizer=optim.SGD(lr=0.01))
        )

        # 状态变量
        self.last_close_price = None
        self.training_features_buffer = None
        self.history = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume','taker_buy'])

        # 训练计数器
        self.train_count = 0

        # 价格预测偏差记录
        self.price_prediction_diff = 0.0
        self.last_hf_prediction = 0.0  # [修复] 新增变量供 UI 显示

        # 高频价格预测器 (简单线性回归)
        self.hf_predictor_1m = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.LinearRegression()
        )

        # 初始化各个数学工具
        self.wavelet = WaveletAnalyzer()
        self.hf = HInfinityFilter1D()
        self.egarch = OnlineEGARCH()
        self.momentum_calc = MomentumCalculator()
        self.volatility_calc = RollingVolatilityCalculator()
        self.fractal_analysis = FractalAnalysis()
        self.bocpd = OnlineBOCPD()
        self.cached_analysis_data = None

    def ingest_candle(self, candle, timeframe='1m', btc_change_pct=0.0, obi_value=0.0):
        """
        处理新K线数据，维护历史列表
        """
        if timeframe == '1m':
            if len(candle) == 6:
                candle.append(candle[5] * 0.5)
            timestamp, open_, high, low, close, vol, taker_buy_vol = candle
            new_row = pd.DataFrame([[timestamp, open_, high, low, close, vol, taker_buy_vol]],
                                   columns=['timestamp', 'open', 'high', 'low', 'close', 'volume','taker_buy'])

            # 维护历史数据窗口 (500根)
            if self.history.empty:
                self.history = new_row
            else:
                self.history = pd.concat([self.history, new_row]).iloc[-500:]

            # --- 训练高频价格预测器 (HF Predictor) ---
            if len(self.history) > 1:
                X_hf = {'close_lag1': self.history['close'].iloc[-2]}
                y_true = close
                pred_price = self.hf_predictor_1m.predict_one(X_hf)

                # 更新状态供 UI 和特征使用
                self.last_hf_prediction = pred_price
                self.price_prediction_diff = (pred_price - close) / close

                self.hf_predictor_1m.learn_one(X_hf, y_true)

            # 计算所有复杂特征并缓存
            self._recalculate_and_cache_features(close, btc_change_pct, obi_value)

    def _recalculate_and_cache_features(self, curr_price, btc_change_pct=0.0, obi_value=0.0):
        """
        计算复杂的数学特征
        """
        if len(self.history) < 30:
            self.cached_analysis_data = None
            return

        # 1. 基础指标更新
        last_p = self.last_close_price if self.last_close_price else curr_price
        log_ret = np.log(curr_price / last_p) if last_p > 0 else 0.0

        eg_vol = self.egarch.update(log_ret)
        hf_val = self.hf.update(curr_price)
        wav_res, wav_eng = self.wavelet.process(self.history['close'].values)
        rsi = MathUtils.calc_rsi(self.history['close']).iloc[-1]
        atr = MathUtils.calc_atr(self.history).iloc[-1]

        # 2. 动量与波动率 (基于列表)
        prices_list = self.history['close'].tolist()
        momentums = self.momentum_calc.calculate_all_momentums(prices_list)
        # [修复] 确保调用 correct method (calculate_all_volatilities)
        volatilities = self.volatility_calc.calculate_all_volatilities(prices_list)

        # 3. 其他特征
        hurst = self.fractal_analysis.update(curr_price)
        cp_prob = self.bocpd.update(curr_price)
        range_pct = (self.history['high'].iloc[-1] - self.history['low'].iloc[-1]) / self.history['open'].iloc[-1]
        hf_diff = (curr_price - hf_val) / hf_val
        prev_atr = MathUtils.calc_atr(self.history.iloc[:-1]).iloc[-1]
        vol_expl = (self.history['high'].iloc[-1] - self.history['low'].iloc[-1]) / (prev_atr + 1e-9)
        # [新增] 计算主动买卖压力特征
        # 获取当前K线的总成交量和主动买入量
        curr_vol = self.history['volume'].iloc[-1]
        curr_taker_buy = self.history['taker_buy'].iloc[-1]

        # 计算买入比例 (0.0 ~ 1.0)
        # 如果是 0.5 代表买卖平衡，>0.5 代表买方强，<0.5 代表卖方强
        buy_ratio = curr_taker_buy / (curr_vol + 1e-9)

        # 将其转换为 -1 到 1 的压力值，方便 AI 理解
        # 结果 > 0 说明有人主动买， < 0 说明有人主动卖
        buy_pressure = (buy_ratio - 0.5) * 2.0

        # [新增] 也可以计算量的变化率（量比），辅助判断是否放量
        # 简单计算：当前量 / 过去5根均量
        vol_ma5 = self.history['volume'].rolling(5).mean().iloc[-1]
        vol_ratio = curr_vol / (vol_ma5 + 1e-9)

        # 1. BTC 动量 (放大 1000 倍让数值不至于太小)
        btc_mom = btc_change_pct * 1000

        # 2. Alpha (超额收益): XRP 涨幅 - BTC 涨幅
        # 如果 > 0，说明 XRP 比 BTC 强 (独立行情)
        # 如果 < 0，说明 XRP 比 BTC 弱 (跟跌不跟涨)
        xrp_change = (curr_price - self.last_close_price) / self.last_close_price if self.last_close_price else 0.0
        alpha = (xrp_change - btc_change_pct) * 1000

        # 4. 组装特征向量 (numpy array)
        def get_val(d, k): return d.get(k, 0.0) if d.get(k) is not None else 0.0

        features = np.array([
            hf_diff,
            eg_vol * 1000,
            rsi / 100.0,
            vol_expl,
            range_pct,
            (curr_price - wav_res) / curr_price * 100,
            np.log1p(wav_eng),
            get_val(momentums, 'T_5'), get_val(momentums, 'T_10'),
            get_val(momentums, 'T_25'), get_val(momentums, 'T_50'),
            get_val(volatilities, 'T_5'), get_val(volatilities, 'T_10'),
            get_val(volatilities, 'T_25'), get_val(volatilities, 'T_50'),
            self.price_prediction_diff, hurst, cp_prob,

            buy_pressure,  # 主动买卖意愿 (-1 ~ 1)
            np.log1p(vol_ratio),  # 量比 (放量程度)
            btc_mom,
            alpha,
            obi_value
        ]).reshape(1, -1)

        # 5. 存入缓存
        self.cached_analysis_data = {
            'features': features, 'price': curr_price, 'atr': atr, 'rsi': rsi,
            'vol_explosion': vol_expl, 'hf_diff': hf_diff, 'wavelet_energy': wav_eng,
            'momentum_values': momentums, 'volatility_values': volatilities,
            'range_pct': range_pct, 'obi': 0.0,
            'hurst_exponent': hurst, 'change_point_prob': cp_prob
        }

    def predict(self, features):
        """
        【双核预测核心】
        综合 随机森林(RF) 和 线性模型(Linear) 的结果
        """
        # 将 numpy 数组转为 dict 喂给 River
        x = {f"f{i}": v for i, v in enumerate(features.flatten())}

        # 1. 获取随机森林的意见 (保守派)
        rf_probs = self.rf_model.predict_proba_one(x)
        rf_conf_1 = rf_probs.get(1, 0.0)
        rf_conf_minus_1 = rf_probs.get(-1, 0.0)

        # 2. 获取线性模型的意见 (激进派)
        linear_probs = self.linear_model.predict_proba_one(x)
        ln_conf_1 = linear_probs.get(1, 0.0)
        ln_conf_minus_1 = linear_probs.get(-1, 0.0)

        # 3. 混合投票 (Soft Voting)
        # 权重 50/50，兼顾稳健与速度
        final_prob_1 = (rf_conf_1 * 0.5) + (ln_conf_1 * 0.5)
        final_prob_minus_1 = (rf_conf_minus_1 * 0.5) + (ln_conf_minus_1 * 0.5)

        # 4. 最终决策
        if final_prob_1 > final_prob_minus_1 and final_prob_1 > 0.5:
            return 1, final_prob_1
        elif final_prob_minus_1 > final_prob_1 and final_prob_minus_1 > 0.5:
            return -1, final_prob_minus_1
        else:
            return 0, 0.0

    def on_candle_close(self, closed_candle_analysis, current_close_price):
        """
        【双核训练核心】
        同时训练两个模型，让它们一起进化
        """
        if self.last_close_price is None:
            self.last_close_price = current_close_price
            self.training_features_buffer = closed_candle_analysis['features']
            print(f"{Fore.CYAN}[AI Train] 系统初始化：记录首个基准价格 {current_close_price}{Style.RESET_ALL}")
            return

        if self.training_features_buffer is not None:
            # --- A. 计算真实涨跌 ---
            price_diff_pct = (current_close_price - self.last_close_price) / self.last_close_price

            # 硬性门槛：至少覆盖成本 (0.0015 = 0.15%)
            COST_THRESHOLD = 0.0015

            atr_val = closed_candle_analysis.get('atr', 0.0)

            # 动态门槛：ATR 的 0.5 倍
            if atr_val > 0:
                dynamic_threshold = max((atr_val / self.last_close_price) * 0.5, COST_THRESHOLD)
            else:
                dynamic_threshold = COST_THRESHOLD

            label = 0
            if price_diff_pct > dynamic_threshold:
                label = 1
            elif price_diff_pct < -dynamic_threshold:
                label = -1



            x = {f"f{i}": v for i, v in enumerate(self.training_features_buffer.flatten())}

            self.rf_model.learn_one(x, label)

            if label != 0:
                self.linear_model.learn_one(x, label)

            self.train_count += 1

            # 日志：确认双核都在工作
            if label != 0:
                print(f"[AI Learn] 波动:{atr_val:.4f} | 涨跌:{price_diff_pct:.2%} | Label:{label} (双核更新)")

        # 滚动更新
        self.last_close_price = current_close_price
        self.training_features_buffer = closed_candle_analysis['features']

    def extract_features(self):
        return self.cached_analysis_data


# ==========================================
# 3. K均值聚类分析器
# ==========================================
class KMeansClusterAnalyzer:
    def __init__(self, n_clusters=5):
        self.n_clusters = n_clusters
        self.feature_names = ['mom_5', 'mom_10', 'mom_25', 'mom_50', 'vol_5', 'vol_10', 'vol_25', 'vol_50']
        self.is_initialized = False
        self.last_valid_cluster = 5

        # 加载CSV
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
        if not momentum_values or not volatility_values:
            return (self.last_valid_cluster, 0.0) if self.is_initialized else (5, 999.0)

        features = []
        periods = [5, 10, 25, 50]

        # 1. 提取动量
        for T in periods:
            val = momentum_values.get(f"T_{T}")
            # 如果 val 是 None，则使用 0.0，否则使用 val
            features.append(val if val is not None else 0.0)

        # 2. 提取波动率
        for T in periods:
            val = volatility_values.get(f"T_{T}")
            features.append(val if val is not None else 0.0)

        feature_vector = np.array(features)

        if np.all(feature_vector == 0):
            return (self.last_valid_cluster, 0.0) if self.is_initialized else (5, 999.0)

        min_distance = float('inf')
        best_cluster = 5

        for cluster_id, centroid in self.centroids.items():
            dist = np.linalg.norm(feature_vector - np.array(centroid))
            if dist < min_distance:
                min_distance = dist
                best_cluster = cluster_id

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