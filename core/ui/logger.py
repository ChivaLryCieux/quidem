import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler


class UILogger:
    def __init__(self, name="trading_ui", log_level=logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(log_level)

        # 防止重复添加 Handler (关键：避免日志重复打印)
        if self.logger.hasHandlers():
            return

        # 创建日志目录
        log_dir = "logs"
        # [优化] exist_ok=True 避免竞态条件报错
        os.makedirs(log_dir, exist_ok=True)

        # 使用固定的日志前缀，方便归档
        # 注意：这里保留了时间戳文件名，但在生产环境中通常建议用 logs/trading.log 并自动轮转
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_filename = os.path.join(log_dir, f"trading_{timestamp}.log")

        # 格式化器：对齐列宽，提升可读性
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 使用 RotatingFileHandler 防止磁盘写满
        # maxBytes=10MB, backupCount=5 (最多保留50MB日志)
        file_handler = RotatingFileHandler(
            log_filename,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # 控制台处理器 (StreamHandler)
        # 如果你的 display.py 已经接管了屏幕显示，这里再输出到控制台会破坏 UI。
        # 建议：仅当没有 UI 系统接管时才启用控制台日志。
        # 为了保持接口兼容，这里保留它，但建议在 main.py 的 logging 配置中统一管理。
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    def get_logger(self):
        return self.logger

    def log_trade(self, action, symbol, price, size, pnl=0, balance=0):
        """记录交易信息"""
        # [优化] 增加 :< 对齐格式，使日志文件更整洁
        msg = f"{action:<4} {symbol} @ {price:.4f} x {size} | PnL: {pnl:+.2f} | Balance: {balance:.2f}"
        self.logger.info(msg)

    def log_signal(self, signal_type, confidence, price, indicators):
        """记录信号信息"""
        msg = f"Signal: {signal_type:<4} (conf: {confidence:.2f}) @ {price:.4f} | Indicators: {indicators}"
        self.logger.info(msg)

    def log_error(self, error_msg, context=""):
        """记录错误信息"""
        if context:
            msg = f"[{context}] {error_msg}"
        else:
            msg = error_msg
        self.logger.error(msg)

    def log_warning(self, warning_msg, context=""):
        """记录警告信息"""
        if context:
            msg = f"[{context}] {warning_msg}"
        else:
            msg = warning_msg
        self.logger.warning(msg)