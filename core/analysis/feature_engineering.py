
import numpy as np
import pandas as pd
from core.analysis.lib_indicators import MultivariateHInfinityFilter, WaveletAnalyzer, OnlineBOCPD
from core.analysis.raw_indicators import (
    MomentumCalculator, OnlineEGARCH, RollingVolatilityCalculator, 
    FractalAnalysis, MathUtils
)

class FeatureEngineer:
    """
    负责从原始K线数据中提取机器学习模型所需的特征。
    """
    def __init__(self):
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
        
        self.last_close_price = None
        self.last_hf_signal = 0.0

    def calculate_features(self, history_df, curr_price, btc_change_pct=0.0, obi_value=0.0):
        """
        计算特征
        :param history_df: 需要包含 'close', 'high', 'low', 'open', 'volume', 'taker_buy'
        :return: (features_array, context_dict)
        """
        if len(history_df) < 30:
            return None, None

        # 1. 小波去噪
        if len(history_df) >= 16:
            price_history = history_df['close'].iloc[-16:].tolist()
            clean_price = self.wavelet.process(price_history)[0]
        else:
            clean_price = curr_price
        
        # 2. 对数收益率与 EGARCH 波动率
        last_p = self.last_close_price if self.last_close_price else curr_price
        log_ret = np.log(curr_price / last_p) if last_p > 0 else 0.0
        eg_vol = self.egarch.update(log_ret)
        
        # 3. 动量计算
        prices_list = history_df['close'].tolist()
        moms = self.momentum_calc.update(clean_price)
        
        # 4. 分形与变点检测
        hurst = self.fractal_analysis.update(curr_price)
        cp_prob = self.bocpd.update(log_ret)
        
        # 5. 基础技术指标
        rsi = MathUtils.calc_rsi(history_df['close']).iloc[-1]
        atr = MathUtils.calc_atr(history_df).iloc[-1]
        range_pct = (history_df['high'].iloc[-1] - history_df['low'].iloc[-1]) / history_df['open'].iloc[-1]
        prev_atr = MathUtils.calc_atr(history_df.iloc[:-1]).iloc[-1]
        vol_expl = (history_df['high'].iloc[-1] - history_df['low'].iloc[-1]) / (prev_atr + 1e-9)
        
        # 6. 量能分析
        curr_vol = history_df['volume'].iloc[-1]
        curr_taker_buy = history_df['taker_buy'].iloc[-1]
        buy_ratio = curr_taker_buy / (curr_vol + 1e-9)
        buy_pressure = (buy_ratio - 0.5) * 2.0
        vol_ma5 = history_df['volume'].rolling(5).mean().iloc[-1]
        vol_ratio = curr_vol / (vol_ma5 + 1e-9)
        
        # 7. 外部因子
        btc_mom = btc_change_pct * 1000
        xrp_change = (curr_price - self.last_close_price) / self.last_close_price if self.last_close_price else 0.0
        alpha = (xrp_change - btc_change_pct) * 1000
        
        # 8. H-infinity Filter Check
        current_hf_features = np.concatenate([moms, [1.0]])
        if self.prev_hf_features is not None and self.prev_price is not None:
            prev_log_ret = np.log(curr_price / self.prev_price) if self.prev_price > 0 else 0.0
            self.hf_filter.update(self.prev_hf_features, prev_log_ret, cp_prob)
        
        hf_signal = -1.0 * self.hf_filter.predict(current_hf_features)
        self.last_hf_signal = hf_signal
        
        # 更新状态
        self.prev_price = curr_price
        self.prev_hf_features = current_hf_features
        self.last_close_price = curr_price # Update this at the end of calc
        
        # 9. 波动率族
        volatilities = self.volatility_calc.calculate_all_volatilities(prices_list)
        def get_val(d, k): return d.get(k, 0.0) if d.get(k) is not None else 0.0

        # === 组装特征向量 ===
        # 注意：这里的结构必须与模型训练时保持完全一致
        features = np.array([
            hf_signal,
            eg_vol * 1000,
            rsi / 100.0,
            vol_expl,
            range_pct,
            (curr_price - clean_price) / curr_price * 100,
            0.0,  # Legacy: wavelet energy
            moms[1] if len(moms) > 1 else 0.0,
            moms[1] if len(moms) > 1 else 0.0, # Approximate T_10
            moms[2] if len(moms) > 2 else 0.0, # Approximate T_25
            moms[3] if len(moms) > 3 else 0.0, # Approximate T_50
            get_val(volatilities, 'T_5'), get_val(volatilities, 'T_10'),
            get_val(volatilities, 'T_25'), get_val(volatilities, 'T_50'),
            0.0, hurst, cp_prob,
            buy_pressure,
            np.log1p(vol_ratio),
            btc_mom,
            alpha,
            obi_value
        ]).reshape(1, -1)
        
        # Sanitize
        features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
        
        context = {
            'features': features, 
            'price': curr_price, 
            'atr': atr, 
            'rsi': rsi,
            'vol_explosion': vol_expl, 
            'hf_signal': hf_signal, 
            'wavelet_energy': 0.0,
            'momentum_values': {'T_1': moms[0], 'T_5': moms[1], 'T_15': moms[2], 
                              'T_30': moms[3], 'T_50': moms[4], 'T_96': moms[5]}, 
            'volatility_values': volatilities,
            'range_pct': range_pct, 
            'obi': obi_value,
            'hurst_exponent': hurst, 
            'change_point_prob': cp_prob
        }
        
        return features, context
