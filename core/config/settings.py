import os
import logging

logger = logging.getLogger(__name__)

class Config:
    # 代理与网络
    PROXY_PORT = 7897
    PROXY_HOST = "127.0.0.1"
    PROXY_URL = f"http://{PROXY_HOST}:{PROXY_PORT}"

    # 交易所 API
    API_KEY = "YOUR_BINANCE_API_KEY"
    API_SECRET = "YOUR_BINANCE_API_SECRET"

    # 交易标的与参数
    SYMBOL = 'XRP/USDT'
    SYMBOL_WS = 'xrpusdt'  # WebSocket用的全小写无斜杠名称
    TIMEFRAME = '1m'

    # 资金管理
    MIN_LEVERAGE = 5.0
    MAX_LEVERAGE = 5.0
    RISK_APPETITE = 0.03
    TAKER_FEE_RATE = 0.0005

    MAX_FUNDING_RATE_THRESHOLD = 0.0005

    # 策略参数
    BAILOUT_ON_NTH_FLIP = 3
    FEE_BUFFER_PCT = 0.0012
    MIN_ATR_PCT = 0.0020
    MIN_TP_DISTANCE = 0.003

    # 微观结构
    OBI_THRESHOLD_TREND = -0.2
    OBI_THRESHOLD_BREAKOUT = 0.1
    MAX_SPREAD_PCT = 0.001
    LABEL_ATR_MULT = 0.5  # 训练与标签阈值：ATR倍数，用于决定涨跌标签门槛
    BACKTEST_MODE = True  # 回测模式开关：True 时跳过依赖订单簿的过滤（避免OBI真空抑制信号）
    FUNDING_EVENT_INTERVAL_HOURS = 8  # 资金费率结算间隔（小时），回测按此周期触发结算事件
    BACKTEST_FUNDING_RATE_PCT = 0.0000  # 回测资金费率（百分比），正数对多仓扣费、对空仓加费；负数相反

    #邮件报告开关
    ENABLE_MAIL_REPORT = False

    # 日志配置
    LOG_LEVEL = 'INFO'
    LOG_DIR = 'logs'
    LOG_FILE = 'quant_bot.log'
    LOG_TO_CONSOLE = True
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5

    @staticmethod
    def setup_proxy():
        # 如果需要设置系统级代理环境变量
        if Config.PROXY_HOST and Config.PROXY_PORT:
            os.environ["HTTP_PROXY"] = Config.PROXY_URL
            os.environ["HTTPS_PROXY"] = Config.PROXY_URL