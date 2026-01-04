import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional

class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m',    
        'INFO': '\033[32m',     
        'WARNING': '\033[33m',  
        'ERROR': '\033[31m',    
        'CRITICAL': '\033[35m', 
    }
    RESET = '\033[0m'

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)

def setup_logging(
    log_level: str = 'INFO',
    log_dir: Optional[str] = None,
    log_file: Optional[str] = None,
    console_output: bool = True,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5
) -> None:
    """
    设置日志配置
    
    Args:
        log_level: 日志级别 ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        log_dir: 日志文件目录
        log_file: 日志文件名
        console_output: 是否输出到控制台
        max_bytes: 日志文件最大大小 (字节)
        backup_count: 日志文件备份数量
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除现有的处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 控制台输出
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        
        console_formatter = ColoredFormatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # 文件输出
    if log_file:
        if log_dir is None:
            log_dir = Path(__file__).parent.parent.parent / 'logs'
        
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, log_file)
        
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        
        file_formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器
    
    Args:
        name: 日志记录器名称
        
    Returns:
        日志记录器实例
    """
    return logging.getLogger(name)