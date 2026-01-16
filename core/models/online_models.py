
import numpy as np
import pandas as pd
import logging
import sys
from colorama import Fore, Style

try:
    import river
    from river import compose
    from river import preprocessing, linear_model, optim, ensemble
    from river import tree
    from river import base
    try:
        from river.forest import AdaptiveRandomForestClassifier
        print(f"{Fore.GREEN}[System] River {river.__version__} 环境检测正常{Style.RESET_ALL}")
    except ImportError:
        from river.forest import ARFClassifier as AdaptiveRandomForestClassifier
except ImportError as e:
    print(f"{Fore.RED}错误: River 库加载失败。{Style.RESET_ALL}")
    sys.exit(1)

from core.analysis.feature_engineering import FeatureEngineer

logger = logging.getLogger(__name__)

class SRP_PAR_EWA_Ensemble:
    """
    SRP (Streaming Random Patches) + PAR (Passive-Aggressive Regressor) 
    双核架构，结合EWARegressor动态权重分配。
    
    Refactored to separate feature engineering.
    """
    def __init__(self):
        self._init_models()
        
        self.feature_engineer = FeatureEngineer()
        self.history = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])
        self.cached_analysis_data = None
        self.training_features_buffer = None
        self.last_close_price = None
        self.train_count = 0
        self._ewa_initialized = False

    def _init_models(self):
        # SRP - Tree-based
        self.classifier_srp = compose.Pipeline(
            preprocessing.StandardScaler(),
            tree.HoeffdingTreeClassifier(grace_period=50, delta=1e-5, max_depth=12, split_criterion="info_gain")
        )
        
        # PAR - Linear
        self.classifier_par = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.LogisticRegression(optimizer=optim.SGD(lr=0.01))
        )
        
        # Regression models for EWA weight learning
        self.srp_regressor = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.LinearRegression(optimizer=optim.SGD(lr=0.01))
        )
        self.par_regressor = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.PARegressor(C=1.0, eps=0.1, mode=1)
        )
        
        # EWA Ensemble
        self.ewa_ensemble = ensemble.EWARegressor(
            models=[self.srp_regressor, self.par_regressor],
            learning_rate=0.5
        )

    def _sanitize_value(self, v):
        if v is None: return 0.0
        try:
            v_float = float(v)
            if np.isnan(v_float) or np.isinf(v_float): return 0.0
            return v_float
        except Exception: return 0.0

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

            # 只有15mK线触发特征重算
            features, context = self.feature_engineer.calculate_features(
                self.history, close, btc_change_pct, obi_value
            )
            self.cached_analysis_data = context

    def predict(self, features):
        """
        SRP + PAR + EWA 双核预测
        """
        # 特征预处理
        if isinstance(features, dict):
            x = {f"f{i}": self._sanitize_value(v) for i, v in enumerate(features.values())}
        elif isinstance(features, np.ndarray):
            sanitized = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
            x = {f"f{i}": v for i, v in enumerate(sanitized.flatten())}
        else:
            x = {f"f{i}": self._sanitize_value(v) for i, v in enumerate(features)}

        # 1. Base Models Prediction
        srp_probs = self.classifier_srp.predict_proba_one(x)
        srp_score = srp_probs.get(1, 0.0) - srp_probs.get(-1, 0.0)

        par_probs = self.classifier_par.predict_proba_one(x)
        par_score = par_probs.get(1, 0.0) - par_probs.get(-1, 0.0)

        # 2. Ensemble Input (Average)
        ens_input = (srp_score + par_score) / 2
        ens_input = 0.0 if np.isnan(ens_input) or np.isinf(ens_input) else ens_input
            
        # 3. Dynamic Weighting via EWA
        final_pred_value = ens_input
        if self._ewa_initialized:
            try:
                ewa_pred = self.ewa_ensemble.predict_one({'ensemble_input': ens_input})
                if ewa_pred is not None:
                    final_pred_value = ewa_pred
            except Exception:
                pass
        else:
            self._ewa_initialized = True

        # Sanitize final
        if np.isnan(final_pred_value): final_pred_value = 0.0

        # Thresholding
        if final_pred_value > 0.08:
            return 1, abs(final_pred_value)
        elif final_pred_value < -0.08:
            return -1, abs(final_pred_value)
        else:
            return 0, abs(final_pred_value)

    def on_candle_close(self, closed_candle_analysis, current_close_price):
        """
        在线学习更新
        """
        if self.last_close_price is None:
            self.last_close_price = current_close_price
            self.training_features_buffer = closed_candle_analysis.get('features')
            print(f"{Fore.CYAN}[AI Train] 系统初始化：记录首个基准价格 {current_close_price}{Style.RESET_ALL}")
            return

        if self.training_features_buffer is not None:
            price_diff_pct = (current_close_price - self.last_close_price) / self.last_close_price
            FIXED_THRESHOLD = 0.0015

            label = 0
            reg_target = 0.0
            if price_diff_pct > FIXED_THRESHOLD:
                label = 1; reg_target = 1.0
            elif price_diff_pct < -FIXED_THRESHOLD:
                label = -1; reg_target = -1.0

            # 构建训练样本
            sanitized = np.nan_to_num(self.training_features_buffer, nan=0.0, posinf=0.0, neginf=0.0)
            x = {f"f{i}": v for i, v in enumerate(sanitized.flatten())}

            # Train Classifiers
            self.classifier_srp.learn_one(x, label)
            if label != 0:
                self.classifier_par.learn_one(x, label)

            # Train EWA Regressor
            avg_feat = np.mean(sanitized)
            avg_feat = 0.0 if np.isnan(avg_feat) else avg_feat
            self.ewa_ensemble.learn_one({'input': avg_feat}, reg_target)

            self.train_count += 1
            if label != 0:
                print(f"[AI Learn] 涨跌:{price_diff_pct:.2%} | Label:{label}")

        self.last_close_price = current_close_price
        self.training_features_buffer = closed_candle_analysis.get('features')

    def extract_features(self):
        return self.cached_analysis_data
