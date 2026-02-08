"""
GMM-HMM 推理引擎

负责加载训练好的 HMM 模型并进行实时状态预测。
5个状态定义：
  State 0: 大跌 (Huge Drop) - 极负动量，高波动，高量
  State 1: 小跌 (Small Drop) - 弱负动量，低波动
  State 2: 震荡 (Volatility) - 动量接近0，均值回归特性强
  State 3: 小涨 (Small Rise) - 弱正动量，低波动
  State 4: 大涨 (Huge Rise) - 极正动量，高波动，高量
"""

import numpy as np
import os
import sys
import logging
import joblib

logger = logging.getLogger(__name__)


class HMMStateEngine:
    """
    GMM-HMM 推理引擎
    负责加载训练好的 HMM 模型并进行实时状态预测
    """
    
    def __init__(self, model_path=None):
        """
        初始化 HMM 引擎，加载训练好的模型
        
        Args:
            model_path: 模型文件路径，默认为 core/sol_hmm_latest.pkl
        """
        # 默认模型路径
        if model_path is None:
            model_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 
                'sol_hmm_latest.pkl'
            )
        
        # 检查文件是否存在
        if not os.path.exists(model_path):
            # 尝试旧的 xrp 模型路径作为后备
            old_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 
                'xrp_hmm_latest.pkl'
            )
            if os.path.exists(old_path):
                logger.warning(f"⚠️ 未找到 SOL 模型，使用旧模型: {old_path}")
                model_path = old_path
            else:
                logger.error(f"❌ HMM 模型文件未找到: {model_path}")
                self._init_fallback()
                return
        
        try:
            # 加载模型包
            logger.info(f"正在加载 HMM 模型: {model_path}")
            model_bundle = joblib.load(model_path)
            
            # 提取模型组件
            self.model = model_bundle['model']
            self.scaler = model_bundle['scaler']
            self.state_map = model_bundle['state_map']
            self.feature_cols = model_bundle['feature_cols']
            self.n_clusters = model_bundle.get('n_clusters', 5)
            
            logger.info(f"✅ HMM 模型加载成功")
            logger.info(f"   - 状态数量: {self.n_clusters}")
            logger.info(f"   - 特征维度: {len(self.feature_cols)}")
            logger.info(f"   - 状态映射: {self.state_map}")
            
            self.model_loaded = True
            
        except Exception as e:
            logger.error(f"❌ HMM 模型加载失败: {e}")
            self._init_fallback()
        
        # 状态追踪
        self.is_initialized = False
        self.last_valid_state = 99
    
    def _init_fallback(self):
        """初始化后备模式（无模型）"""
        self.model = None
        self.scaler = None
        self.state_map = {}
        self.feature_cols = []
        self.n_clusters = 5
        self.model_loaded = False
        logger.warning("⚠️ HMM 引擎运行在后备模式，将返回默认状态")
    
    def predict_state(self, momentum_values=None, volatility_values=None, context=None):
        """
        预测当前市场状态
        
        Args:
            momentum_values: 字典，格式 {'T_1': val, 'T_10': val, ...} (旧接口兼容)
            volatility_values: 字典，格式 {'T_5': val, 'T_50': val, ...} (旧接口兼容)
            context: 完整的特征上下文字典 (新接口)
        
        Returns:
            (state_id, confidence): 状态ID (0-4) 和置信度
        """
        # 模型未加载，返回默认状态
        if not self.model_loaded:
            return (self.last_valid_state, 0.0) if self.is_initialized else (99, 0.0)
        
        # 使用新接口 (context)
        if context is not None and 'hmm_features' in context:
            return self._predict_from_features(context['hmm_features'])
        
        # 使用旧接口 (momentum_values, volatility_values)
        if momentum_values is not None and volatility_values is not None:
            return self._predict_from_legacy(momentum_values, volatility_values, context)
        
        return (self.last_valid_state, 0.0) if self.is_initialized else (99, 0.0)
    
    def _predict_from_features(self, hmm_features):
        """从预计算的HMM特征向量预测状态"""
        if hmm_features is None:
            return (self.last_valid_state, 0.0) if self.is_initialized else (99, 0.0)
        
        feature_vector = np.array(hmm_features).reshape(1, -1)
        
        # 检查是否全为零
        if np.all(feature_vector == 0):
            return (self.last_valid_state, 0.0) if self.is_initialized else (99, 0.0)
        
        # 数据清洗
        feature_vector = np.nan_to_num(feature_vector, nan=0.0, posinf=0.0, neginf=0.0)
        
        try:
            # 特征缩放
            X_scaled = self.scaler.transform(feature_vector)
            
            # HMM 状态预测
            raw_state = self.model.predict(X_scaled)[0]
            
            # 映射到排序后的状态ID
            sorted_state = self.state_map.get(raw_state, 99)
            
            # 计算置信度
            log_likelihood = self.model.score(X_scaled)
            confidence = min(1.0, max(0.0, np.exp(log_likelihood / 100)))
            
            # 更新状态追踪
            if sorted_state != 99:
                self.is_initialized = True
                self.last_valid_state = sorted_state
            
            return sorted_state, confidence
            
        except Exception as e:
            logger.error(f"HMM 预测失败: {e}")
            return (self.last_valid_state, 0.0) if self.is_initialized else (99, 0.0)
    
    def _predict_from_legacy(self, momentum_values, volatility_values, context=None):
        """从旧格式的动量和波动率值预测状态（兼容性）"""
        # 尝试从 context 获取额外特征
        if context is None:
            context = {}
        
        # 构建特征向量 (12维)
        features = []
        
        # 1. 相对成交量
        features.append(context.get('relative_volume', 1.0))
        
        # 2. 对数动量 (1,10,50,96)
        for T in [1, 10, 50, 96]:
            key = f"T_{T}"
            val = momentum_values.get(key, 0.0)
            features.append(val if val is not None else 0.0)
        
        # 3. 滚动标准差 (5,50,96)
        for T in [5, 50, 96]:
            key = f"T_{T}"
            val = volatility_values.get(key, 0.0)
            features.append(val if val is not None else 0.0)
        
        # 4. 归一化MACD
        features.append(context.get('macd_normalized', 0.0))
        
        # 5. 布林带距离
        features.append(context.get('bb_distance', 0.0))
        
        # 6. SuperTrend方向
        features.append(float(context.get('supertrend_direction', 0)))
        
        # 7. K-D差值
        features.append(context.get('k_minus_d', 0.0))
        
        feature_vector = np.array(features).reshape(1, -1)
        return self._predict_from_features(feature_vector)
    
    def get_state_name(self, state_id):
        """
        获取状态的中文名称
        
        Args:
            state_id: 状态ID (0-4 或 99)
        
        Returns:
            状态名称字符串
        """
        state_names = {
            0: "大跌",
            1: "小跌",
            2: "震荡",
            3: "小涨",
            4: "大涨",
            99: "初始化"
        }
        return state_names.get(state_id, f"未知状态({state_id})")
