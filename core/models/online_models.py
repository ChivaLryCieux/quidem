import numpy as np
import pandas as pd
import logging
from river import compose, preprocessing, linear_model, optim, tree, ensemble

from core.analysis.feature_engineering import FeatureEngineer


class SRP_PAR_Ensemble:
    """
    双核架构：Tree Ensemble + PAR (Logistic)
    采用 Soft Voting 机制
    
    修复:
    - 使用集成树模型替代单棵树
    - 修复Scaler泄漏问题
    - 只训练有明确方向的样本(label != 0)
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
        self.scaler_fitted = False  # 标记scaler是否已初始化

    def _init_models(self):
        # 1. Tree Ensemble - Adaptive Random Forest (集成树模型,更稳定)
        self.model_tree = ensemble.AdaptiveRandomForestClassifier(
            n_models=5,  # 5棵树的集成
            max_depth=10,
            grace_period=100,
            delta=1e-5,
            leaf_prediction='nba',  # Naive Bayes Adaptive
            split_criterion='info_gain'
        )

        # 2. PAR - Logistic Regression (线性模型,捕捉线性关系)
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

        # 2. 特征缩放 (只transform,不learn - 修复Scaler泄漏)
        if self.scaler_fitted:
            x_scaled = self.scaler.transform_one(x)
        else:
            # 首次预测时使用原始特征(scaler尚未训练)
            x_scaled = x

        # 3. 获取概率 (Soft Voting)
        # Tree Ensemble 概率
        tree_probs = self.model_tree.predict_proba_one(x_scaled)
        # PAR 概率
        par_probs = self.model_par.predict_proba_one(x_scaled)

        # 提取上涨(1)和下跌(-1)的概率，如果键不存在则为0
        p_up = (tree_probs.get(1, 0.0) + par_probs.get(1, 0.0)) / 2
        p_down = (tree_probs.get(-1, 0.0) + par_probs.get(-1, 0.0)) / 2

        # 4. 计算最终得分 (-1 到 1)
        final_score = p_up - p_down

        # 5. 决策逻辑
        # 信心 = 得分的绝对值
        confidence = abs(final_score)

        # 信心阈值逻辑
        threshold = 0.25

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

            # 2. 只训练有明确方向的样本 (修复0 label语义污染和PAR被拖死问题)
            if label != 0:
                # 准备训练数据
                features = self.training_features_buffer
                x = {}
                if isinstance(features, dict):
                    x = {k: self._sanitize_value(v) for k, v in features.items()}
                elif isinstance(features, np.ndarray):
                    sanitized = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
                    x = {f"f{i}": v for i, v in enumerate(sanitized.flatten())}

                # 3. 在训练时更新Scaler (修复Scaler泄漏问题)
                self.scaler.learn_one(x)
                self.scaler_fitted = True
                x_scaled = self.scaler.transform_one(x)

                # 4. 训练模型
                self.model_tree.learn_one(x_scaled, label)
                self.model_par.learn_one(x_scaled, label)

                self.train_count += 1
                print(f"[AI Learn] 波动:{price_diff_pct:.2%} | Label:{label} | 样本数:{self.train_count}")

        # 更新 Buffer
        self.last_close_price = current_close_price
        self.training_features_buffer = closed_candle_analysis.get('features')

    def extract_features(self):
        return self.cached_analysis_data