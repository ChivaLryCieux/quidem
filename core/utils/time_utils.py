import time
import datetime
from typing import Optional, Union

class TimeUtils:
    """时间处理工具类"""
    
    @staticmethod
    def current_timestamp_ms() -> int:
        """
        获取当前时间戳（毫秒）
        
        Returns:
            当前时间戳（毫秒）
        """
        return int(time.time() * 1000)
        
    @staticmethod
    def current_timestamp_s() -> int:
        """
        获取当前时间戳（秒）
        
        Returns:
            当前时间戳（秒）
        """
        return int(time.time())
        
    @staticmethod
    def ms_to_datetime(timestamp_ms: int) -> datetime.datetime:
        """
        将毫秒时间戳转换为datetime对象
        
        Args:
            timestamp_ms: 毫秒时间戳
            
        Returns:
            datetime对象
        """
        return datetime.datetime.fromtimestamp(timestamp_ms / 1000.0)
        
    @staticmethod
    def s_to_datetime(timestamp_s: int) -> datetime.datetime:
        """
        将秒时间戳转换为datetime对象
        
        Args:
            timestamp_s: 秒时间戳
            
        Returns:
            datetime对象
        """
        return datetime.datetime.fromtimestamp(timestamp_s)
        
    @staticmethod
    def datetime_to_ms(dt: datetime.datetime) -> int:
        """
        将datetime对象转换为毫秒时间戳
        
        Args:
            dt: datetime对象
            
        Returns:
            毫秒时间戳
        """
        return int(dt.timestamp() * 1000)
        
    @staticmethod
    def datetime_to_s(dt: datetime.datetime) -> int:
        """
        将datetime对象转换为秒时间戳
        
        Args:
            dt: datetime对象
            
        Returns:
            秒时间戳
        """
        return int(dt.timestamp())
        
    @staticmethod
    def format_timestamp_ms(timestamp_ms: int, format_str: str = '%Y-%m-%d %H:%M:%S') -> str:
        """
        格式化毫秒时间戳
        
        Args:
            timestamp_ms: 毫秒时间戳
            format_str: 格式字符串
            
        Returns:
            格式化后的时间字符串
        """
        dt = TimeUtils.ms_to_datetime(timestamp_ms)
        return dt.strftime(format_str)
        
    @staticmethod
    def format_timestamp_s(timestamp_s: int, format_str: str = '%Y-%m-%d %H:%M:%S') -> str:
        """
        格式化秒时间戳
        
        Args:
            timestamp_s: 秒时间戳
            format_str: 格式字符串
            
        Returns:
            格式化后的时间字符串
        """
        dt = TimeUtils.s_to_datetime(timestamp_s)
        return dt.strftime(format_str)
        
    @staticmethod
    def get_time_diff_ms(start_ms: int, end_ms: Optional[int] = None) -> int:
        """
        计算时间差（毫秒）
        
        Args:
            start_ms: 开始时间戳（毫秒）
            end_ms: 结束时间戳（毫秒），如果为None则使用当前时间
            
        Returns:
            时间差（毫秒）
        """
        if end_ms is None:
            end_ms = TimeUtils.current_timestamp_ms()
        return end_ms - start_ms
        
    @staticmethod
    def get_time_diff_s(start_s: int, end_s: Optional[int] = None) -> int:
        """
        计算时间差（秒）
        
        Args:
            start_s: 开始时间戳（秒）
            end_s: 结束时间戳（秒），如果为None则使用当前时间
            
        Returns:
            时间差（秒）
        """
        if end_s is None:
            end_s = TimeUtils.current_timestamp_s()
        return end_s - start_s
        
    @staticmethod
    def is_market_hours(dt: Optional[datetime.datetime] = None) -> bool:
        """
        检查是否为交易时间（简化版本，假设24小时交易）
        
        Args:
            dt: datetime对象，如果为None则使用当前时间
            
        Returns:
            是否为交易时间
        """
        if dt is None:
            dt = datetime.datetime.now()
            
        # 这里可以根据具体的交易时间规则进行修改
        # 目前假设24小时都可以交易
        return True
        
    @staticmethod
    def get_trading_day_start(dt: Optional[datetime.datetime] = None) -> datetime.datetime:
        """
        获取交易日开始时间（假设为UTC 00:00）
        
        Args:
            dt: datetime对象，如果为None则使用当前时间
            
        Returns:
            交易日开始时间
        """
        if dt is None:
            dt = datetime.datetime.now()
            
        # 返回当天的开始时间
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        
    @staticmethod
    def sleep_ms(milliseconds: int) -> None:
        """
        睡眠指定的毫秒数
        
        Args:
            milliseconds: 毫秒数
        """
        time.sleep(milliseconds / 1000.0)
        
    @staticmethod
    def sleep_seconds(seconds: Union[int, float]) -> None:
        """
        睡眠指定的秒数
        
        Args:
            seconds: 秒数
        """
        time.sleep(seconds)