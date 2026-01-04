import numpy as np
import pandas as pd
import os
import sys
import logging
from colorama import Fore, Style

try:
    import river
    from river import compose
    from river import preprocessing, linear_model, optim

    try:
        from river.forest import AdaptiveRandomForestClassifier
        print(f"{Fore.GREEN}[System] River {river.__version__} 环境检测正常{Style.RESET_ALL}")
    except ImportError:
        from river.forest import ARFClassifier as AdaptiveRandomForestClassifier

except ImportError as e:
    print(f"{Fore.RED}错误: River 库加载失败。虽然检测到已安装，但导入出错。{Style.RESET_ALL}")
    print(e)
    sys.exit(1)

from analysis.indicators import MathUtils
from analysis.filters import HInfinityFilter1D, OnlineEGARCH, WaveletAnalyzer
from analysis.transform import MomentumCalculator, RollingVolatilityCalculator, FractalAnalysis, OnlineBOCPD

logger = logging.getLogger(__name__)


class RandomForestClassifier:
    def __init__(self):
        self.rf_model = compose.Pipeline(
            preprocessing.StandardScaler(),
            AdaptiveRandomForestClassifier(
                n_models=30,
                max_depth=12,
                split_criterion="hellinger",
                grace_period=50,
                lambda_value=6,
                seed=42
            )
        )

        self.linear_model = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.LogisticRegression(optimizer=optim.SGD(lr=0.01))
        )

        self.last_close_price = None
        self.training_features_buffer = None
        self.history = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])

        self.train_count = 0

        self.price_prediction_diff = 0.0
        self.last_hf_prediction = 0.0

        self.hf_predictor_1m = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.LinearRegression()
        )

        self.wavelet = WaveletAnalyzer()
        self.hf = HInfinityFilter1D()
        self.egarch = OnlineEGARCH()
        self.momentum_calc = MomentumCalculator()
        self.volatility_calc = RollingVolatilityCalculator()
        self.fractal_analysis = FractalAnalysis()
        self.bocpd = OnlineBOCPD()
        self.cached_analysis_data = None

    def ingest_candle(self, candle, timeframe='1m', btc_change_pct=0.0, obi_value=0.0):
        if timeframe == '1m':
            if len(candle) == 6:
                candle.append(candle[5] * 0.5)
            timestamp, open_, high, low, close, vol, taker_buy_vol = candle
            new_row = pd.DataFrame([[timestamp, open_, high, low, close, vol, taker_buy_vol]],
                                   columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy'])

            if self.history.empty:
                self.history = new_row
            else:
                self.history = pd.concat([self.history, new_row]).iloc[-500:]

            if len(self.history) > 1:
                X_hf = {'close_lag1': self.history['close'].iloc[-2]}
                y_true = close
                pred_price = self.hf_predictor_1m.predict_one(X_hf)

                self.last_hf_prediction = pred_price
                self.price_prediction_diff = (pred_price - close) / close

                self.hf_predictor_1m.learn_one(X_hf, y_true)

            self._recalculate_and_cache_features(close, btc_change_pct, obi_value)

    def _recalculate_and_cache_features(self, curr_price, btc_change_pct=0.0, obi_value=0.0):
        if len(self.history) < 30:
            self.cached_analysis_data = None
            return

        last_p = self.last_close_price if self.last_close_price else curr_price
        log_ret = np.log(curr_price / last_p) if last_p > 0 else 0.0

        eg_vol = self.egarch.update(log_ret)
        hf_val = self.hf.update(curr_price)
        wav_res, wav_eng = self.wavelet.process(self.history['close'].values)
        rsi = MathUtils.calc_rsi(self.history['close']).iloc[-1]
        atr = MathUtils.calc_atr(self.history).iloc[-1]

        prices_list = self.history['close'].tolist()
        momentums = self.momentum_calc.calculate_all_momentums(prices_list)
        volatilities = self.volatility_calc.calculate_all_volatilities(prices_list)

        hurst = self.fractal_analysis.update(curr_price)
        cp_prob = self.bocpd.update(curr_price)
        range_pct = (self.history['high'].iloc[-1] - self.history['low'].iloc[-1]) / self.history['open'].iloc[-1]
        hf_diff = (curr_price - hf_val) / hf_val
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

            buy_pressure,
            np.log1p(vol_ratio),
            btc_mom,
            alpha,
            obi_value
        ]).reshape(1, -1)

        self.cached_analysis_data = {
            'features': features, 'price': curr_price, 'atr': atr, 'rsi': rsi,
            'vol_explosion': vol_expl, 'hf_diff': hf_diff, 'wavelet_energy': wav_eng,
            'momentum_values': momentums, 'volatility_values': volatilities,
            'range_pct': range_pct, 'obi': 0.0,
            'hurst_exponent': hurst, 'change_point_prob': cp_prob
        }

    def predict(self, features):
        # 确保所有特征值都不是 None，将 None 替换为 0.0
        feature_values = []
        for i, v in enumerate(features.flatten()):
            if v is None:
                feature_values.append(0.0)
            else:
                feature_values.append(v)
        x = {f"f{i}": v for i, v in enumerate(feature_values)}

        rf_probs = self.rf_model.predict_proba_one(x)
        rf_conf_1 = rf_probs.get(1, 0.0)
        rf_conf_minus_1 = rf_probs.get(-1, 0.0)

        linear_probs = self.linear_model.predict_proba_one(x)
        ln_conf_1 = linear_probs.get(1, 0.0)
        ln_conf_minus_1 = linear_probs.get(-1, 0.0)

        final_prob_1 = (rf_conf_1 * 0.5) + (ln_conf_1 * 0.5)
        final_prob_minus_1 = (rf_conf_minus_1 * 0.5) + (ln_conf_minus_1 * 0.5)

        if final_prob_1 > final_prob_minus_1 and final_prob_1 > 0.5:
            return 1, final_prob_1
        elif final_prob_minus_1 > final_prob_1 and final_prob_minus_1 > 0.5:
            return -1, final_prob_minus_1
        else:
            return 0, 0.0

    def on_candle_close(self, closed_candle_analysis, current_close_price):
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
            if price_diff_pct > dynamic_threshold:
                label = 1
            elif price_diff_pct < -dynamic_threshold:
                label = -1

            # 确保训练特征中没有 None 值
            feature_values = []
            for i, v in enumerate(self.training_features_buffer.flatten()):
                if v is None:
                    feature_values.append(0.0)
                else:
                    feature_values.append(v)
            x = {f"f{i}": v for i, v in enumerate(feature_values)}

            self.rf_model.learn_one(x, label)

            if label != 0:
                self.linear_model.learn_one(x, label)

            self.train_count += 1

            if label != 0:
                print(f"[AI Learn] 波动:{atr_val:.4f} | 涨跌:{price_diff_pct:.2%} | Label:{label} (双核更新)")

        self.last_close_price = current_close_price
        self.training_features_buffer = closed_candle_analysis['features']

    def extract_features(self):
        return self.cached_analysis_data