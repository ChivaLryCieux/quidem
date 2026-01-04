import numpy as np
import pandas as pd
from typing import Union, List, Dict, Any

class DataValidator:
    """数据验证工具类"""
    
    @staticmethod
    def validate_price_data(prices: Union[List, np.ndarray, pd.Series]) -> bool:
        """
        验证价格数据的有效性
        
        Args:
            prices: 价格数据
            
        Returns:
            是否有效
        """
        if prices is None or len(prices) == 0:
            return False
            
        # 转换为numpy数组
        if isinstance(prices, (list, pd.Series)):
            prices = np.array(prices)
            
        # 检查是否有NaN或无穷值
        if np.isnan(prices).any() or np.isinf(prices).any():
            return False
            
        # 检查是否所有价格都为正数
        if (prices <= 0).any():
            return False
            
        return True
        
    @staticmethod
    def validate_ohlc_data(ohlc_data: Dict[str, Any]) -> bool:
        """
        验证OHLC数据的有效性
        
        Args:
            ohlc_data: OHLC数据字典，包含'open', 'high', 'low', 'close'键
            
        Returns:
            是否有效
        """
        required_keys = ['open', 'high', 'low', 'close']
        
        # 检查必需键
        for key in required_keys:
            if key not in ohlc_data:
                return False
                
        # 检查数据长度一致性
        lengths = [len(ohlc_data[key]) for key in required_keys if key in ohlc_data]
        if len(set(lengths)) != 1:
            return False
            
        # 验证每个价格序列
        for key in required_keys:
            if not DataValidator.validate_price_data(ohlc_data[key]):
                return False
                
        # 检查价格逻辑关系
        for i in range(lengths[0]):
            open_price = ohlc_data['open'][i]
            high_price = ohlc_data['high'][i]
            low_price = ohlc_data['low'][i]
            close_price = ohlc_data['close'][i]
            
            if not (low_price <= open_price <= high_price):
                return False
            if not (low_price <= close_price <= high_price):
                return False
                
        return True
        
    @staticmethod
    def validate_trade_data(trade_data: Dict[str, Any]) -> bool:
        """
        验证交易数据的有效性
        
        Args:
            trade_data: 交易数据字典
            
        Returns:
            是否有效
        """
        required_keys = ['symbol', 'action', 'price', 'size']
        
        # 检查必需键
        for key in required_keys:
            if key not in trade_data or trade_data[key] is None:
                return False
                
        # 验证价格
        if trade_data['price'] <= 0:
            return False
            
        # 验证数量
        if trade_data['size'] == 0:
            return False
            
        # 验证动作类型
        valid_actions = ['buy', 'sell', 'long', 'short', 'close_long', 'close_short']
        if trade_data['action'] not in valid_actions:
            return False
            
        return True
        
    @staticmethod
    def validate_indicator_params(indicator_name: str, params: Dict[str, Any]) -> bool:
        """
        验证技术指标参数
        
        Args:
            indicator_name: 指标名称
            params: 参数字典
            
        Returns:
            是否有效
        """
        # 常见指标参数验证
        validation_rules = {
            'sma': {'period': lambda x: isinstance(x, int) and x > 0},
            'ema': {'period': lambda x: isinstance(x, int) and x > 0},
            'rsi': {'period': lambda x: isinstance(x, int) and x > 0},
            'macd': {'fast_period': lambda x: isinstance(x, int) and x > 0,
                    'slow_period': lambda x: isinstance(x, int) and x > 0,
                    'signal_period': lambda x: isinstance(x, int) and x > 0},
            'bollinger': {'period': lambda x: isinstance(x, int) and x > 0,
                         'std_dev': lambda x: isinstance(x, (int, float)) and x > 0},
            'atr': {'period': lambda x: isinstance(x, int) and x > 0}
        }
        
        if indicator_name not in validation_rules:
            return False
            
        rules = validation_rules[indicator_name]
        
        for param, validator in rules.items():
            if param not in params:
                return False
            if not validator(params[param]):
                return False
                
        return True
        
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        清理文件名，移除不安全字符
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的文件名
        """
        import re
        
        # 移除不安全的字符
        unsafe_chars = r'[<>:"/\\|?*]'
        sanitized = re.sub(unsafe_chars, '_', filename)
        
        # 移除多余的空格和下划线
        sanitized = re.sub(r'[_]+', '_', sanitized)
        sanitized = sanitized.strip('_')
        
        # 确保不为空
        if not sanitized:
            sanitized = 'unnamed_file'
            
        return sanitized
        
    @staticmethod
    def validate_config_value(key: str, value: Any, expected_type: type, 
                            min_value=None, max_value=None, choices=None) -> bool:
        """
        验证配置值的有效性
        
        Args:
            key: 配置键名
            value: 配置值
            expected_type: 期望的数据类型
            min_value: 最小值（可选）
            max_value: 最大值（可选）
            choices: 可选值列表（可选）
            
        Returns:
            是否有效
        """
        # 验证类型
        if not isinstance(value, expected_type):
            return False
            
        # 验证数值范围
        if min_value is not None and value < min_value:
            return False
            
        if max_value is not None and value > max_value:
            return False
            
        # 验证可选值
        if choices is not None and value not in choices:
            return False
            
        return True