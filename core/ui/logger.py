import logging
import os
from datetime import datetime

class UILogger:
    def __init__(self, name="trading_ui", log_level=logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(log_level)
        
        # 创建日志目录
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # 创建文件处理器
        log_filename = f"{log_dir}/trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_filename, encoding='utf-8')
        file_handler.setLevel(log_level)
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        
        # 创建格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # 添加处理器到日志器
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
    def get_logger(self):
        return self.logger
        
    def log_trade(self, action, symbol, price, size, pnl=0, balance=0):
        """记录交易信息"""
        msg = f"{action} {symbol} @ {price:.4f} x {size} | PnL: {pnl:+.2f} | Balance: {balance:.2f}"
        self.logger.info(msg)
        
    def log_signal(self, signal_type, confidence, price, indicators):
        """记录信号信息"""
        msg = f"Signal: {signal_type} (conf: {confidence:.2f}) @ {price:.4f} | Indicators: {indicators}"
        self.logger.info(msg)
        
    def log_error(self, error_msg, context=""):
        """记录错误信息"""
        if context:
            msg = f"{context} - {error_msg}"
        else:
            msg = error_msg
        self.logger.error(msg)
        
    def log_warning(self, warning_msg, context=""):
        """记录警告信息"""
        if context:
            msg = f"{context} - {warning_msg}"
        else:
            msg = warning_msg
        self.logger.warning(msg)