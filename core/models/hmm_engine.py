import numpy as np
import pandas as pd
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
            model_path: 模型文件路径，默认为 core/xrp_hmm_latest.pkl
        """
        # 默认模型路径
        if model_path is None:
            model_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 
                'xrp_hmm_latest.pkl'
            )
        
        # 检查文件是否存在
        if not os.path.exists(model_path):
            logger.error(f"❌ HMM 模型文件未找到: {model_path}")
            sys.exit(1)
        
        try:
            # 加载模型包（只加载一次）
            logger.info(f"正在加载 HMM 模型: {model_path}")
            model_bundle = joblib.load(model_path)
            
            # 提取模型组件
            self.model = model_bundle['model']  # GMMHMM 对象
            self.scaler = model_bundle['scaler']  # StandardScaler 对象
            self.state_map = model_bundle['state_map']  # 状态映射字典
            self.feature_cols = model_bundle['feature_cols']  # 特征列名列表
            self.n_clusters = model_bundle.get('n_clusters', 5)
            
            logger.info(f"✅ HMM 模型加载成功")
            logger.info(f"   - 状态数量: {self.n_clusters}")
            logger.info(f"   - 特征维度: {len(self.feature_cols)}")
            logger.info(f"   - 状态映射: {self.state_map}")
            
        except Exception as e:
            logger.error(f"❌ HMM 模型加载失败: {e}")
            sys.exit(1)
        
        # 训练时使用的窗口（必须与训练代码一致）
        self.windows = [1, 5, 15, 30, 50, 96]
        
        # 状态追踪
        self.is_initialized = False
        self.last_valid_state = 99  # 初始状态为 99
        
        # 最小数据长度（需要足够的历史数据来计算 rolling(96)）
        self.min_data_length = max(self.windows) + 10  # 96 + 10 = 106
    
    def predict_state(self, momentum_values, volatility_values):
        """
        预测当前市场状态
        
        Args:
            momentum_values: 字典，格式 {'T_1': val, 'T_5': val, ...}
            volatility_values: 字典，格式 {'T_1': val, 'T_5': val, ...}
        
        Returns:
            (state_id, confidence): 状态ID (0-4) 和置信度
        """
        # 1. 数据验证
        if not momentum_values or not volatility_values:
            return (self.last_valid_state, 0.0) if self.is_initialized else (99, 0.0)
        
        # 2. 构建特征向量（必须与训练时的顺序完全一致）
        features = []
        
        # 2.1 添加对数动量特征（按窗口顺序）
        for T in self.windows:
            key = f"T_{T}"
            val = momentum_values.get(key)
            features.append(val if val is not None else 0.0)
        
        # 2.2 添加波动率特征（只在大于1的窗口）
        for T in self.windows:
            if T > 1:
                key = f"T_{T}"
                val = volatility_values.get(key)
                features.append(val if val is not None else 0.0)
        
        # 3. 转换为 numpy 数组
        feature_vector = np.array(features).reshape(1, -1)
        
        # 4. 检查是否全为零（无效数据）
        if np.all(feature_vector == 0):
            return (self.last_valid_state, 0.0) if self.is_initialized else (99, 0.0)
        
        # 5. 数据清洗（防止 NaN 和 Inf）
        feature_vector = np.nan_to_num(feature_vector, nan=0.0, posinf=0.0, neginf=0.0)
        
        try:
            # 6. 特征缩放（只使用 transform，不使用 fit_transform）
            # 这是关键：防止未来函数！
            X_scaled = self.scaler.transform(feature_vector)
            
            # 7. HMM 状态预测
            # predict() 返回的是训练时的随机状态ID，需要通过 state_map 映射
            raw_state = self.model.predict(X_scaled)[0]
            
            # 8. 映射到排序后的状态ID (0=大跌, 1=弱跌, 2=震荡, 3=弱涨, 4=大涨)
            sorted_state = self.state_map.get(raw_state, 99)
            
            # 9. 计算置信度（使用状态概率）
            # score() 返回对数似然，我们将其转换为置信度
            log_likelihood = self.model.score(X_scaled)
            # 简单映射：将对数似然归一化到 [0, 1]
            # 注意：这是一个简化的置信度估计
            confidence = min(1.0, max(0.0, np.exp(log_likelihood / 100)))
            
            # 10. 更新状态追踪
            if sorted_state != 99:
                self.is_initialized = True
                self.last_valid_state = sorted_state
            
            return sorted_state, confidence
            
        except Exception as e:
            logger.error(f"HMM 预测失败: {e}")
            return (self.last_valid_state, 0.0) if self.is_initialized else (99, 0.0)
    
    def get_state_name(self, state_id):
        """
        获取状态的中文名称
        
        Args:
            state_id: 状态ID (0-4 或 99)
        
        Returns:
            状态名称字符串
        """
        state_names = {
            0: "极度恐慌/大跌",
            1: "阴跌/弱势",
            2: "震荡/噪音",
            3: "反弹/弱势上涨",
            4: "主升浪/大涨",
            99: "初始化"
        }
        return state_names.get(state_id, f"未知状态({state_id})")
