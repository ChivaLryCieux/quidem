
import numpy as np
import pandas as pd
from core.analysis.raw_indicators import (
    MomentumCalculator, RollingVolatilityCalculator, MathUtils
)

class FeatureEngineer:
    """
    负责从原始K线数据中提取HMM模型所需的特征。
    
    简化版：只计算HMM需要的11个特征（6动量+5波动率）
    以及风险管理需要的RSI和ATR。
    """
    def __init__(self):
        # HMM特征计算器
        self.momentum_calc = MomentumCalculator(periods=[1, 5, 15, 30, 50, 96])
        self.volatility_calc = RollingVolatilityCalculator()

    def calculate_features(self, history_df, curr_price, btc_change_pct=0.0, obi_value=0.0):
        """
        计算特征
        :param history_df: 需要包含 'close', 'high', 'low', 'open', 'volume', 'taker_buy'
        :param curr_price: 当前价格
        :param btc_change_pct: BTC变化百分比（保留参数以兼容，但不使用）
        :param obi_value: 订单簿失衡值（保留参数以兼容，但不使用）
        :return: (features_array, context_dict)
        """
        if len(history_df) < 30:
            return None, None

        # 1. 动量计算（HMM核心特征）
        prices_list = history_df['close'].tolist()
        moms = self.momentum_calc.update(curr_price)
        
        # 2. 波动率计算（HMM核心特征）
        volatilities = self.volatility_calc.calculate_all_volatilities(prices_list)
        def get_val(d, k): 
            return d.get(k, 0.0) if d.get(k) is not None else 0.0
        
        # 3. 技术指标（风险管理使用）
        rsi = MathUtils.calc_rsi(history_df['close']).iloc[-1]
        atr = MathUtils.calc_atr(history_df).iloc[-1]
        
        # === 组装特征向量（仅用于兼容性，实际HMM不使用这个向量） ===
        # HMM直接使用 context 中的 momentum_values 和 volatility_values
        features = np.array([0.0]).reshape(1, -1)  # 占位符
        
        # 构建context（HMM和风险管理使用）
        context = {
            'features': features,  # 占位符，保持兼容性
            'price': curr_price,
            'atr': atr,
            'rsi': rsi,
            'momentum_values': {
                'T_1': moms[0], 
                'T_5': moms[1], 
                'T_15': moms[2],
                'T_30': moms[3], 
                'T_50': moms[4], 
                'T_96': moms[5]
            },
            'volatility_values': volatilities,
            'obi': obi_value  # 保留用于盘口过滤
        }
        
        return features, context
