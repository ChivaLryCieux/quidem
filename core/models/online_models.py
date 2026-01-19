import numpy as np
import pandas as pd
import logging
from river import compose, preprocessing, linear_model, optim, tree

from core.analysis.feature_engineering import FeatureEngineer


class SRP_PAR_Ensemble:
    """
    双核架构：SRP (Tree) + PAR (Logistic)
    采用 Soft Voting 机制
    """

    def __init__(self):
        self._init_models()
        self.feature_engineer = FeatureEngineer()
        self.history = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])

        self.last_close_price = None
        self.train_count = 0
        
        # 缓存分析数据，用于 extract_features 调用
        self.cached_analysis_data = None

        # 用于特征缩放的全局 Scaler，确保两个模型输入一致
        self.scaler = preprocessing.StandardScaler()

    def _init_models(self):
        # 1. SRP - Hoeffding Tree (适合非线性关系)
        # 注意：移除了 Pipeline 中的 StandardScaler，因为我们在外部统一做
        self.model_srp = tree.HoeffdingTreeClassifier(
            grace_period=100,  # 增加宽限期，让树更成熟再分裂
            delta=1e-5,
            max_depth=10,
            split_criterion="info_gain"
        )

        # 2. PAR - Logistic Regression (适合线性关系，模拟PAR的分类行为)
        # 使用 SGD 优化器的逻辑回归，这也是一种在线学习模型
        self.model_par = linear_model.LogisticRegression(
            optimizer=optim.SGD(lr=0.01)
        )

    def _sanitize_value(self, v):
        if v is None: return 0.0
        try:
            v_float = float(v)
            if np.isnan(v_float) or np.isinf(v_float): return 0.0
            return v_float
        except Exception:
            return 0.0

    def ingest_candle(self, candle, timeframe='1m', btc_change_pct=0.0, obi_value=0.0):
        if timeframe == '15m':
            if len(candle) == 6:
                candle.append(candle[5] * 0.5)
            timestamp, open_, high, low, close, vol, taker_buy_vol = candle
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
            # 存储返回的 context 用于后续的 extract_features 调用
            self.cached_analysis_data = context

    def predict(self, features):
        """
        输出: (方向 1/-1/0, 信心绝对值 0.0~1.0)
        """
        # 1. 特征清洗与构建字典
        if features is None: return 0, 0.0

        x = {}
        if isinstance(features, dict):
            x = {k: self._sanitize_value(v) for k, v in features.items()}
        elif isinstance(features, np.ndarray):
            sanitized = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
            x = {f"f{i}": v for i, v in enumerate(sanitized.flatten())}
        else:
            return 0, 0.0

        # 2. 在线缩放 (Learn scale but don't learn model)
        self.scaler.learn_one(x)
        x_scaled = self.scaler.transform_one(x)

        # 3. 获取概率 (Soft Voting)
        # SRP 概率
        srp_probs = self.model_srp.predict_proba_one(x_scaled)
        # PAR 概率
        par_probs = self.model_par.predict_proba_one(x_scaled)

        # 提取上涨(1)和下跌(-1)的概率，如果键不存在则为0
        p_up = (srp_probs.get(1, 0.0) + par_probs.get(1, 0.0)) / 2
        p_down = (srp_probs.get(-1, 0.0) + par_probs.get(-1, 0.0)) / 2

        # 4. 计算最终得分 (-1 到 1)
        final_score = p_up - p_down

        # 5. 决策逻辑
        # 信心 = 得分的绝对值
        confidence = abs(final_score)

        # 你的阈值逻辑：0.08
        threshold = 0.08

        if final_score > threshold:
            return 1, confidence
        elif final_score < -threshold:
            return -1, confidence
        else:
            return 0, confidence

    def on_candle_close(self, closed_candle_analysis, current_close_price):
        """
        在线训练
        """
        if self.last_close_price is None:
            self.last_close_price = current_close_price
            self.training_features_buffer = closed_candle_analysis.get('features')
            return

        if self.training_features_buffer is not None:
            # 1. 计算 Label
            price_diff_pct = (current_close_price - self.last_close_price) / self.last_close_price
            FIXED_THRESHOLD = 0.0015  # 0.15% 的波动才算有效涨跌

            label = 0
            if price_diff_pct > FIXED_THRESHOLD:
                label = 1
            elif price_diff_pct < -FIXED_THRESHOLD:
                label = -1

            # 2. 准备训练数据
            # 必须使用上一个时间步的特征来预测当前的价格变化
            features = self.training_features_buffer
            x = {}
            if isinstance(features, dict):
                x = {k: self._sanitize_value(v) for k, v in features.items()}
            elif isinstance(features, np.ndarray):
                sanitized = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
                x = {f"f{i}": v for i, v in enumerate(sanitized.flatten())}

            # 3. 缩放 (Scaler 已经在 predict 时 update 过了，这里直接 transform)
            x_scaled = self.scaler.transform_one(x)

            # 4. 训练模型
            # 无论 label 是什么，SRP 都要学 (因为树需要学习什么是不动)
            self.model_srp.learn_one(x_scaled, label)

            # PAR (线性模型) 对 0 label 学习可能会导致权重衰减过快趋向于0
            # 策略：如果为了捕捉大行情，可以只在有显著涨跌时训练 PAR，或者赋予 0 样本较小的权重
            # 这里简单处理：全量学习
            self.model_par.learn_one(x_scaled, label)

            self.train_count += 1
            if label != 0:
                print(f"[AI Learn] 波动:{price_diff_pct:.2%} | Label:{label} | 样本数:{self.train_count}")

        # 更新 Buffer
        self.last_close_price = current_close_price
        self.training_features_buffer = closed_candle_analysis.get('features')

    def extract_features(self):
        return self.cached_analysis_data