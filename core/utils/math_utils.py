import numpy as np
import pandas as pd
from typing import Union, List, Optional

class MathUtils:
    """数学计算工具类"""
    
    @staticmethod
    def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
        """
        安全除法，避免除以零错误
        
        Args:
            numerator: 分子
            denominator: 分母
            default: 除零时的默认值
            
        Returns:
            除法结果
        """
        if denominator == 0 or np.isnan(denominator) or np.isinf(denominator):
            return default
        return numerator / denominator
        
    @staticmethod
    def calculate_returns(prices: Union[List, np.ndarray, pd.Series], 
                         method: str = 'simple') -> np.ndarray:
        """
        计算收益率
        
        Args:
            prices: 价格序列
            method: 计算方法 ('simple' 或 'log')
            
        Returns:
            收益率序列
        """
        if isinstance(prices, (list, pd.Series)):
            prices = np.array(prices)
            
        if len(prices) < 2:
            return np.array([])
            
        if method == 'simple':
            returns = np.diff(prices) / prices[:-1]
        elif method == 'log':
            returns = np.diff(np.log(prices))
        else:
            raise ValueError("method must be 'simple' or 'log'")
            
        return returns
        
    @staticmethod
    def calculate_volatility(returns: Union[List, np.ndarray, pd.Series], 
                            window: int = 20, annualize: bool = True) -> float:
        """
        计算波动率
        
        Args:
            returns: 收益率序列
            window: 计算窗口
            annualize: 是否年化
            
        Returns:
            波动率
        """
        if isinstance(returns, (list, pd.Series)):
            returns = np.array(returns)
            
        if len(returns) < window:
            return 0.0
            
        recent_returns = returns[-window:]
        volatility = np.std(recent_returns)
        
        if annualize:
            # 假设252个交易日
            volatility *= np.sqrt(252)
            
        return volatility
        
    @staticmethod
    def calculate_sharpe_ratio(returns: Union[List, np.ndarray, pd.Series], 
                              risk_free_rate: float = 0.0) -> float:
        """
        计算夏普比率
        
        Args:
            returns: 收益率序列
            risk_free_rate: 无风险利率
            
        Returns:
            夏普比率
        """
        if isinstance(returns, (list, pd.Series)):
            returns = np.array(returns)
            
        if len(returns) == 0:
            return 0.0
            
        excess_returns = returns - risk_free_rate
        mean_return = np.mean(excess_returns)
        std_return = np.std(excess_returns)
        
        return MathUtils.safe_divide(mean_return, std_return)
        
    @staticmethod
    def calculate_max_drawdown(prices: Union[List, np.ndarray, pd.Series]) -> float:
        """
        计算最大回撤
        
        Args:
            prices: 价格序列
            
        Returns:
            最大回撤（百分比）
        """
        if isinstance(prices, (list, pd.Series)):
            prices = np.array(prices)
            
        if len(prices) == 0:
            return 0.0
            
        # 计算累积最大值
        peak = np.maximum.accumulate(prices)
        
        # 计算回撤
        drawdown = (peak - prices) / peak
        
        # 返回最大回撤
        return np.max(drawdown)
        
    @staticmethod
    def calculate_win_rate(returns: Union[List, np.ndarray, pd.Series]) -> float:
        """
        计算胜率
        
        Args:
            returns: 收益率序列
            
        Returns:
            胜率（百分比）
        """
        if isinstance(returns, (list, pd.Series)):
            returns = np.array(returns)
            
        if len(returns) == 0:
            return 0.0
            
        wins = np.sum(returns > 0)
        return wins / len(returns)
        
    @staticmethod
    def calculate_profit_factor(returns: Union[List, np.ndarray, pd.Series]) -> float:
        """
        计算盈利因子
        
        Args:
            returns: 收益率序列
            
        Returns:
            盈利因子
        """
        if isinstance(returns, (list, pd.Series)):
            returns = np.array(returns)
            
        if len(returns) == 0:
            return 0.0
            
        profits = returns[returns > 0]
        losses = returns[returns <= 0]
        
        gross_profit = np.sum(profits)
        gross_loss = abs(np.sum(losses))
        
        return MathUtils.safe_divide(gross_profit, gross_loss)
        
    @staticmethod
    def calculate_moving_average(data: Union[List, np.ndarray, pd.Series], 
                               window: int, method: str = 'simple') -> np.ndarray:
        """
        计算移动平均
        
        Args:
            data: 数据序列
            window: 窗口大小
            method: 计算方法 ('simple' 或 'exponential')
            
        Returns:
            移动平均序列
        """
        if isinstance(data, (list, pd.Series)):
            data = np.array(data)
            
        if len(data) < window:
            return np.array([])
            
        if method == 'simple':
            # 简单移动平均
            result = np.convolve(data, np.ones(window)/window, mode='valid')
        elif method == 'exponential':
            # 指数移动平均
            alpha = 2 / (window + 1)
            result = np.zeros(len(data) - window + 1)
            result[0] = np.mean(data[:window])
            
            for i in range(1, len(result)):
                result[i] = alpha * data[window + i - 1] + (1 - alpha) * result[i - 1]
        else:
            raise ValueError("method must be 'simple' or 'exponential'")
            
        return result
        
    @staticmethod
    def calculate_percentile(data: Union[List, np.ndarray, pd.Series], 
                           percentile: float) -> float:
        """
        计算百分位数
        
        Args:
            data: 数据序列
            percentile: 百分位数 (0-1)
            
        Returns:
            百分位数值
        """
        if isinstance(data, (list, pd.Series)):
            data = np.array(data)
            
        if len(data) == 0:
            return 0.0
            
        return np.percentile(data, percentile * 100)
        
    @staticmethod
    def normalize_data(data: Union[List, np.ndarray, pd.Series], 
                      method: str = 'minmax') -> np.ndarray:
        """
        数据归一化
        
        Args:
            data: 数据序列
            method: 归一化方法 ('minmax' 或 'zscore')
            
        Returns:
            归一化后的数据
        """
        if isinstance(data, (list, pd.Series)):
            data = np.array(data)
            
        if len(data) == 0:
            return data
            
        if method == 'minmax':
            # 最小-最大归一化
            min_val = np.min(data)
            max_val = np.max(data)
            
            if min_val == max_val:
                return np.zeros_like(data)
                
            return (data - min_val) / (max_val - min_val)
            
        elif method == 'zscore':
            # Z-score标准化
            mean_val = np.mean(data)
            std_val = np.std(data)
            
            if std_val == 0:
                return np.zeros_like(data)
                
            return (data - mean_val) / std_val
        else:
            raise ValueError("method must be 'minmax' or 'zscore'")