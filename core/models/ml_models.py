import numpy as np
import pandas as pd
import os
import sys
import logging
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
    print(f"{Fore.RED}错误: River 库加载失败。虽然检测到已安装，但导入出错。{Style.RESET_ALL}")
    print(e)
    sys.exit(1)

from core.analysis.indicators import MathUtils
from core.analysis.filters import MultivariateHInfinityFilter, OnlineEGARCH, WaveletAnalyzer
from core.analysis.transform import MomentumCalculator, RollingVolatilityCalculator, FractalAnalysis, OnlineBOCPD

logger = logging.getLogger(__name__)


class SRP_PAR_EWA_Ensemble:
    """
    SRP (Streaming Random Patches) + PAR (Passive-Aggressive Regressor) 
    双核架构，结合EWARegressor动态权重分配
    """
    def __init__(self):
        # SRP - Streaming Random Patches (Tree-based)
        self.srp_model = compose.Pipeline(
            preprocessing.StandardScaler(),
            tree.HoeffdingTreeClassifier(
                grace_period=50,
                delta=1e-5,
                max_depth=12,
                split_criterion="info_gain"
            )
        )
        
        # PAR - Passive-Aggressive Regressor (Linear)
        self.par_model = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.PARegressor(
                C=1.0,
                eps=0.1,
                mode=1  # PA-I
            )
        )
        
        # 使用更适合的回归模型进行动态权重分配
        self.srp_regressor = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.LinearRegression(
                optimizer=optim.SGD(lr=0.01)
            )
        )
        
        self.par_regressor = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.PARegressor(
                C=1.0,
                eps=0.1,
                mode=1
            )
        )
        
        # EWARegressor 动态权重分配
        self.ewa_ensemble = ensemble.EWARegressor(
            models=[
                self.srp_regressor,  # Tree-based regression
                self.par_regressor   # Linear regression
            ],
            learning_rate=0.5
        )
        
        # 用于分类任务的辅助模型
        self.classifier_srp = compose.Pipeline(
            preprocessing.StandardScaler(),
            tree.HoeffdingTreeClassifier(
                grace_period=50,
                delta=1e-5,
                max_depth=12,
                split_criterion="info_gain"
            )
        )
        
        self.classifier_par = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.LogisticRegression(
                optimizer=optim.SGD(lr=0.01)
            )
        )

        self.last_close_price = None
        self.training_features_buffer = None
        self.history = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])

        self.train_count = 0

        # Remove price prediction related variables
        # self.price_prediction_diff = 0.0
        # self.last_hf_prediction = 0.0
        
        # Add H-infinity signal tracking
        self.last_hf_signal = 0.0

        # Remove hf_predictor_1m as we no longer predict prices
        # self.hf_predictor_1m = compose.Pipeline(
        #     preprocessing.StandardScaler(),
        #     linear_model.LinearRegression()
        # )

        # New optimized H-infinity system components
        self.wavelet = WaveletAnalyzer()
        self.egarch = OnlineEGARCH()
        self.momentum_calc = MomentumCalculator(periods=[1, 5, 15, 30, 50, 96])
        self.volatility_calc = RollingVolatilityCalculator()
        self.fractal_analysis = FractalAnalysis()
        self.bocpd = OnlineBOCPD()
        
        # Multivariate H-infinity filter (7 features: 6 momentum + 1 bias)
        self.n_hf_features = 7
        self.hf_filter = MultivariateHInfinityFilter(n_features=self.n_hf_features)
        self.prev_hf_features = None
        self.prev_price = None
        
        # Initialize cached analysis data
        self.cached_analysis_data = None

    def _sanitize_value(self, v):
        """Sanitize value to ensure it's a finite float."""
        if v is None:
            return 0.0
        try:
            v_float = float(v)
            if np.isnan(v_float) or np.isinf(v_float):
                return 0.0
            return v_float
        except Exception:
            return 0.0

    def ingest_candle(self, candle, timeframe='1m', btc_change_pct=0.0, obi_value=0.0):
        if timeframe == '15m':
            # 15分钟K线用于主要特征计算和模型预测
            if len(candle) == 6:
                candle.append(candle[5] * 0.5)
            timestamp, open_, high, low, close, vol, taker_buy_vol = candle
            new_row = pd.DataFrame([[timestamp, open_, high, low, close, vol, taker_buy_vol]],
                                   columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])

            if self.history.empty:
                self.history = new_row
            else:
                self.history = pd.concat([self.history, new_row]).iloc[-500:]

            # 只在15分钟K线收盘时重新计算特征
            self._recalculate_and_cache_features(close, btc_change_pct, obi_value)
            
        elif timeframe == '1m':
            # 1分钟K线不再用于价格预测，仅记录历史数据
            pass

    def _recalculate_and_cache_features(self, curr_price, btc_change_pct=0.0, obi_value=0.0):
        if len(self.history) < 30:
            self.cached_analysis_data = None
            return

        # Process price through wavelet for noise reduction
        # Use recent price history for wavelet analysis
        if len(self.history) >= 16:
            price_history = self.history['close'].iloc[-16:].tolist()
            clean_price = self.wavelet.process(price_history)[0]
        else:
            clean_price = curr_price
        
        # Calculate log return
        last_p = self.last_close_price if self.last_close_price else curr_price
        log_ret = np.log(curr_price / last_p) if last_p > 0 else 0.0
        
        # Update EGARCH volatility
        eg_vol = self.egarch.update(log_ret)
        
        # Calculate momentums (this now returns numpy array)
        prices_list = self.history['close'].tolist()
        moms = self.momentum_calc.update(clean_price)
        
        # Update fractal analysis and change point detection
        hurst = self.fractal_analysis.update(curr_price)
        cp_prob = self.bocpd.update(log_ret)
        
        # Calculate other features
        rsi = MathUtils.calc_rsi(self.history['close']).iloc[-1]
        atr = MathUtils.calc_atr(self.history).iloc[-1]
        range_pct = (self.history['high'].iloc[-1] - self.history['low'].iloc[-1]) / self.history['open'].iloc[-1]
        prev_atr = MathUtils.calc_atr(self.history.iloc[:-1]).iloc[-1]
        vol_expl = (self.history['high'].iloc[-1] - self.history['low'].iloc[-1]) / (prev_atr + 1e-9)
        
        curr_vol = self.history['volume'].iloc[-1]
        curr_taker_buy = self.history['taker_buy'].iloc[-1]
        buy_ratio = curr_taker_buy / (curr_vol + 1e-9)
        buy_pressure = (buy_ratio - 0.5) * 2.0
        vol_ma5 = self.history['volume'].rolling(5).mean().iloc[-1]
        vol_ratio = curr_vol / (vol_ma5 + 1e-9)
        
        btc_mom = btc_change_pct * 1000
        xrp_change = (curr_price - self.last_close_price) / self.last_close_price if self.last_close_price else 0.0
        alpha = (xrp_change - btc_change_pct) * 1000
        
        # Create H-infinity features: 6 momentum features + 1 bias
        current_hf_features = np.concatenate([moms, [1.0]])
        
        # Update H-infinity filter if we have previous features
        if self.prev_hf_features is not None and self.prev_price is not None:
            prev_log_ret = np.log(curr_price / self.prev_price) if self.prev_price > 0 else 0.0
            self.hf_filter.update(self.prev_hf_features, prev_log_ret, cp_prob)
        
        # Generate H-infinity signal (momentum reversion strategy)
        hf_signal = -1.0 * self.hf_filter.predict(current_hf_features)
        
        # Store H-infinity signal for UI display
        self.last_hf_signal = hf_signal
        
        # Store current state for next iteration
        self.prev_price = curr_price
        self.prev_hf_features = current_hf_features
        
        def get_val(d, k): return d.get(k, 0.0) if d.get(k) is not None else 0.0
        volatilities = self.volatility_calc.calculate_all_volatilities(prices_list)
        
        # Build feature array - replace hf_diff with hf_signal
        # Note: moms is array with indices [0,1,2,3,4,5] corresponding to periods [1,5,15,30,50,96]
        features = np.array([
            hf_signal,  # Replaced hf_diff with hf_signal
            eg_vol * 1000,
            rsi / 100.0,
            vol_expl,
            range_pct,
            (curr_price - clean_price) / curr_price * 100,  # Use clean_price instead of wav_res
            0.0,  # Placeholder for wavelet energy (not available in new implementation)
            moms[1] if len(moms) > 1 else 0.0,  # T_5 (index 1)
            moms[1] if len(moms) > 1 else 0.0,  # T_10 - using T_5 as approximation
            moms[2] if len(moms) > 2 else 0.0,  # T_15 - using as T_25 approximation
            moms[3] if len(moms) > 3 else 0.0,  # T_30 - using as T_50 approximation
            get_val(volatilities, 'T_5'), get_val(volatilities, 'T_10'),
            get_val(volatilities, 'T_25'), get_val(volatilities, 'T_50'),
            0.0, hurst, cp_prob,  # Replaced self.price_prediction_diff with 0.0
            
            buy_pressure,
            np.log1p(vol_ratio),
            btc_mom,
            alpha,
            obi_value
        ]).reshape(1, -1)
        
        # Sanitize features to remove NaNs and Infs before caching
        features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
        
        self.cached_analysis_data = {
            'features': features, 'price': curr_price, 'atr': atr, 'rsi': rsi,
            'vol_explosion': vol_expl, 'hf_signal': hf_signal, 'wavelet_energy': 0.0,
            'momentum_values': {'T_1': moms[0], 'T_5': moms[1], 'T_15': moms[2], 
                              'T_30': moms[3], 'T_50': moms[4], 'T_96': moms[5]}, 
            'volatility_values': volatilities,
            'range_pct': range_pct, 'obi': 0.0,
            'hurst_exponent': hurst, 'change_point_prob': cp_prob
        }

    def predict(self, features):
        """
        SRP + PAR + EWA 双核预测
        """
        # 处理不同类型的特征输入
        if isinstance(features, dict):
            # 如果传入的是字典，直接使用
            x = {f"f{i}": self._sanitize_value(v) for i, v in enumerate(features.values())}
        elif isinstance(features, np.ndarray):
            # 如果传入的是numpy数组，按原逻辑处理
            # Ensure numpy array is sanitized first
            sanitized_features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
            feature_values = []
            for i, v in enumerate(sanitized_features.flatten()):
                feature_values.append(v)
            x = {f"f{i}": v for i, v in enumerate(feature_values)}
        else:
            # 其他类型，转换为字典
            x = {f"f{i}": self._sanitize_value(v) for i, v in enumerate(features)}

        # SRP (Tree-based) 预测
        srp_probs = self.classifier_srp.predict_proba_one(x)
        srp_conf_1 = srp_probs.get(1, 0.0)
        srp_conf_minus_1 = srp_probs.get(-1, 0.0)

        # PAR (Linear) 预测  
        par_probs = self.classifier_par.predict_proba_one(x)
        par_conf_1 = par_probs.get(1, 0.0)
        par_conf_minus_1 = par_probs.get(-1, 0.0)

        # 使用EWARegressor进行动态权重分配
        # 将分类问题转换为回归问题：1 -> 1.0, -1 -> -1.0, 0 -> 0.0
        srp_pred_value = srp_conf_1 - srp_conf_minus_1
        par_pred_value = par_conf_1 - par_conf_minus_1
        
        # 创建特征用于EWA回归 - 使用单一特征简化
        # Sanitize ensemble inputs
        ens_input = (srp_pred_value + par_pred_value) / 2
        if np.isnan(ens_input) or np.isinf(ens_input):
            ens_input = 0.0
            
        reg_features = {'ensemble_input': ens_input}
        
        # 获取EWA动态权重 - 使用简单加权平均作为回退
        try:
            # 首先尝试用SRP和PAR的预测值作为训练数据
            if hasattr(self, '_ewa_initialized') and self._ewa_initialized:
                ewa_pred = self.ewa_ensemble.predict_one(reg_features)
                if ewa_pred is not None:
                    final_pred_value = ewa_pred
                else:
                    final_pred_value = ens_input
            else:
                # 初始阶段使用简单平均
                final_pred_value = ens_input
                self._ewa_initialized = True
        except Exception as e:
            logger.warning(f"EWA预测失败: {e}，使用简单平均")
            final_pred_value = ens_input
        
        # Sanitize final prediction value
        if np.isnan(final_pred_value) or np.isinf(final_pred_value):
            final_pred_value = 0.0
            
        # 转换回分类结果
        if final_pred_value > 0.08:  # 看涨阈值 (Lowered from 0.2)
            return 1, abs(final_pred_value)
        elif final_pred_value < -0.08:  # 看跌阈值 (Lowered from 0.2)
            return -1, abs(final_pred_value)
        else:
            return 0, abs(final_pred_value)

    def on_candle_close(self, closed_candle_analysis, current_close_price):
        """
        SRP + PAR + EWA 在线学习更新
        """
        if self.last_close_price is None:
            self.last_close_price = current_close_price
            self.training_features_buffer = closed_candle_analysis['features']
            print(f"{Fore.CYAN}[AI Train] 系统初始化：记录首个基准价格 {current_close_price}{Style.RESET_ALL}")
            return

        if self.training_features_buffer is not None:
            price_diff_pct = (current_close_price - self.last_close_price) / self.last_close_price

            COST_THRESHOLD = 0.0015

            atr_val = closed_candle_analysis.get('atr', 0.0)

            if atr_val > 0:
                dynamic_threshold = max((atr_val / self.last_close_price) * 0.5, COST_THRESHOLD)
            else:
                dynamic_threshold = COST_THRESHOLD

            label = 0
            regression_target = 0.0
            if price_diff_pct > dynamic_threshold:
                label = 1
                regression_target = 1.0
            elif price_diff_pct < -dynamic_threshold:
                label = -1
                regression_target = -1.0
            else:
                regression_target = 0.0

            # 确保训练特征中没有 None 值 (Sanitize)
            sanitized_buffer = np.nan_to_num(self.training_features_buffer, nan=0.0, posinf=0.0, neginf=0.0)
            feature_values = []
            for i, v in enumerate(sanitized_buffer.flatten()):
                feature_values.append(v)
            x = {f"f{i}": v for i, v in enumerate(feature_values)}

            # SRP (Tree-based) 分类训练
            self.classifier_srp.learn_one(x, label)
            
            # PAR (Linear) 分类训练
            if label != 0:
                self.classifier_par.learn_one(x, label)
            
            # EWA 回归训练 - 使用回归目标
            # Sanitize regression inputs
            avg_feat = sum(feature_values) / len(feature_values)
            if np.isnan(avg_feat) or np.isinf(avg_feat):
                 avg_feat = 0.0
            
            reg_features = {'input': avg_feat} 
            
            if not np.isnan(regression_target) and not np.isinf(regression_target):
                self.ewa_ensemble.learn_one(reg_features, regression_target)

            self.train_count += 1

            if label != 0:
                print(f"[AI Learn] 波动:{atr_val:.4f} | 涨跌:{price_diff_pct:.2%} | Label:{label} | Target:{regression_target} (SRP+PAR+EWA三核更新)")

        self.last_close_price = current_close_price
        self.training_features_buffer = closed_candle_analysis['features']

    def extract_features(self):
        return self.cached_analysis_data