
import numpy as np
import pandas as pd
from core.analysis.indicators import (
    MomentumCalculator, RollingVolatilityCalculator, MathUtils,
    BollingerBands, SuperTrend, MACDCalculator, KDJCalculator,
    ADXCalculator, VWAPCalculator
)


class FeatureEngineer:
    """
    负责从原始K线数据中提取技术指标特征。
    
    计算指标:
    1. 相对成交量, 动量, 波动率
    2. MACD, 布林带, SuperTrend
    3. KDJ, ADX, VWAP
    """
    def __init__(self):
        # HMM特征计算器
        self.momentum_periods = [1, 10, 50, 96]
        self.volatility_periods = [5, 50, 96]
        self.momentum_calc = MomentumCalculator(periods=self.momentum_periods)
        self.volatility_calc = RollingVolatilityCalculator(periods=self.volatility_periods)
        
        # 技术指标计算器
        self.bollinger = BollingerBands(period=20, std_mult=2.0)
        self.supertrend = SuperTrend(atr_period=10, multiplier=3.0)
        self.macd = MACDCalculator(fast=12, slow=26, signal=9)
        self.kdj = KDJCalculator(k_period=9, d_period=3, j_smooth=3)
        self.adx = ADXCalculator(period=14)
        self.vwap = VWAPCalculator(period=288)
        
        # 成交量MA周期
        self.vol_ma_period = 96

    def calculate_features(self, history_df, curr_price, btc_change_pct=0.0, obi_value=0.0):
        """
        计算技术指标特征
        
        :param history_df: 需要包含 'close', 'high', 'low', 'open', 'volume', 'taker_buy'
        :param curr_price: 当前价格
        :return: (features_array, context_dict)
        """
        if len(history_df) < 100:  # 需要足够历史数据
            return None, None

        # ================================================================
        # 1. 相对成交量 Vol/MA(Vol,96)
        # ================================================================
        vol_ma = history_df['volume'].rolling(window=self.vol_ma_period).mean()
        relative_volume = history_df['volume'].iloc[-1] / (vol_ma.iloc[-1] + 1e-9)
        
        # ================================================================
        # 2. 对数动量 (1,10,50,96)
        # ================================================================
        momentum_values = {}
        for T in self.momentum_periods:
            if len(history_df) > T:
                mom = np.log(history_df['close'].iloc[-1] / history_df['close'].iloc[-(T+1)])
                momentum_values[f'T_{T}'] = mom
            else:
                momentum_values[f'T_{T}'] = 0.0
        
        # ================================================================
        # 3. 滚动标准差 (5,50,96)
        # ================================================================
        log_returns = np.log(history_df['close'] / history_df['close'].shift(1)).fillna(0)
        volatility_values = {}
        for T in self.volatility_periods:
            if len(log_returns) >= T:
                vol = log_returns.tail(T).std()
                volatility_values[f'T_{T}'] = vol if not np.isnan(vol) else 0.0
            else:
                volatility_values[f'T_{T}'] = 0.0
        
        # ================================================================
        # 4. 归一化MACD/Close
        # ================================================================
        macd_result = self.macd.calculate(history_df)
        macd_normalized = macd_result['normalized']
        
        # ================================================================
        # 5. 价格与布林带中轨距离
        # ================================================================
        bb_result = self.bollinger.calculate(history_df)
        bb_distance = bb_result['distance']
        
        # ================================================================
        # 6. 二值化SuperTrend方向
        # ================================================================
        st_result = self.supertrend.calculate(history_df)
        supertrend_direction = st_result['direction']  # 1=绿(多), -1=红(空)
        
        # ================================================================
        # 7. K与D差值 (KDJ)
        # ================================================================
        kdj_result = self.kdj.calculate(history_df)
        
        # ================================================================
        # 8. ADX 趋势强度
        # ================================================================
        adx_result = self.adx.calculate(history_df)
        
        # ================================================================
        # 9. VWAP 成交量加权均价
        # ================================================================
        vwap_result = self.vwap.calculate(history_df)
        k_minus_d = kdj_result['k_minus_d']
        
        # ================================================================
        # 构建HMM特征向量 (用于训练和推理)
        # ================================================================
        # 特征顺序:
        # [relative_vol, mom_1, mom_10, mom_50, mom_96, vol_5, vol_50, vol_96, 
        #  macd_norm, bb_dist, st_dir, k_minus_d]
        hmm_features = np.array([
            relative_volume,
            momentum_values.get('T_1', 0.0),
            momentum_values.get('T_10', 0.0),
            momentum_values.get('T_50', 0.0),
            momentum_values.get('T_96', 0.0),
            volatility_values.get('T_5', 0.0),
            volatility_values.get('T_50', 0.0),
            volatility_values.get('T_96', 0.0),
            macd_normalized,
            bb_distance,
            float(supertrend_direction),
            k_minus_d
        ]).reshape(1, -1)
        
        # ================================================================
        # 技术指标（风险管理和信号生成使用）
        # ================================================================
        rsi = MathUtils.calc_rsi(history_df['close']).iloc[-1]
        atr = MathUtils.calc_atr(history_df).iloc[-1]
        
        # 构建context（策略信号和风险管理使用）
        context = {
            # 价格信息
            'price': curr_price,
            
            # 技术指标 - 风险管理
            'atr': atr,
            'rsi': rsi,
            
            # 布林带
            'bb_middle': bb_result['middle'],
            'bb_upper': bb_result['upper'],
            'bb_lower': bb_result['lower'],
            'bb_distance': bb_distance,
            
            # SuperTrend
            'supertrend_value': st_result['value'],
            'supertrend_direction': supertrend_direction,
            
            # MACD
            'macd': macd_result['macd'],
            'macd_signal': macd_result['signal'],
            'macd_histogram': macd_result['histogram'],
            'macd_normalized': macd_normalized,
            
            # KDJ
            'kdj_k': kdj_result['k'],
            'kdj_d': kdj_result['d'],
            'kdj_j': kdj_result['j'],
            'k_minus_d': k_minus_d,
            'kdj_golden_cross': kdj_result['golden_cross'],
            'kdj_death_cross': kdj_result['death_cross'],
            
            # ADX
            'adx': adx_result['adx'],
            'plus_di': adx_result['plus_di'],
            'minus_di': adx_result['minus_di'],
            'adx_rising': adx_result['adx_rising'],
            
            # VWAP
            'vwap': vwap_result['vwap'],
            'vwap_distance': vwap_result['distance'],
            'vwap_upper': vwap_result['upper_band'],
            'vwap_lower': vwap_result['lower_band'],
            
            # 成交量
            'relative_volume': relative_volume,
            
            # 动量和波动率 (兼容旧代码)
            'momentum_values': momentum_values,
            'volatility_values': volatility_values,
            
            # 盘口信息
            'obi': obi_value
        }
        
        return hmm_features, context

    def get_feature_names(self):
        """获取特征名称列表"""
        return [
            'relative_volume',
            'log_mom_1', 'log_mom_10', 'log_mom_50', 'log_mom_96',
            'vol_5', 'vol_50', 'vol_96',
            'macd_normalized',
            'bb_distance',
            'supertrend_direction',
            'k_minus_d'
        ]
