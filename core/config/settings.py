import os
import logging
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)

class Config:
    # 代理与网络
    PROXY_PORT = 7890
    PROXY_HOST = "127.0.0.1"
    PROXY_URL = f"http://{PROXY_HOST}:{PROXY_PORT}"

    # 交易所 API
    API_KEY = os.getenv("BINANCE_API_KEY")
    API_SECRET = os.getenv("BINANCE_SECRET")

    # 交易标的与参数
    SYMBOL = 'SOL/USDT'
    SYMBOL_WS = 'solusdt'  # WebSocket用的全小写无斜杠名称
    TIMEFRAME_SIGNAL = '5m'   # 信号生成和交易执行周期
    TIMEFRAME_TREND = '15m'   # 大趋势过滤周期
    TIMEFRAME = '5m'          # 主周期，兼容旧代码

    # 资金管理
    MIN_LEVERAGE = 5.0
    MAX_LEVERAGE = 10.0       # 降低杠杆，减少手续费影响
    DEFAULT_LEVERAGE = 10.0
    RISK_APPETITE = 0.05      # 目标单笔净利 5%
    TAKER_FEE_RATE = 0.0005

    MAX_FUNDING_RATE_THRESHOLD = 0.0005

    # 策略参数
    BAILOUT_ON_NTH_FLIP = 99  # 基本禁用flip平仓，只靠TP/SL
    FEE_BUFFER_PCT = 0.0012
    MIN_ATR_PCT = 0.0020
    MIN_TP_DISTANCE = 0.012   # 止盈目标：1.2%价格波动 (10x杠杆=12%本金)
    MAX_SL_DISTANCE = 0.004   # 硬止损：0.4%价格反向 (10x杠杆=4%本金)
    # 盈亏比 3:1，30%胜率即可打平，60%胜率大幅盈利

    # 微观结构
    OBI_THRESHOLD_TREND = -0.2
    OBI_THRESHOLD_BREAKOUT = 0.1
    MAX_SPREAD_PCT = 0.001
    LABEL_ATR_MULT = 0.5
    BACKTEST_MODE = True
    FUNDING_EVENT_INTERVAL_HOURS = 8
    BACKTEST_FUNDING_RATE_PCT = 0.0000

    #邮件报告开关
    ENABLE_MAIL_REPORT = False
    MAIL_FROM = os.getenv("MAIL_FROM", "CTA q-bot <report@abyssalfish.top>")
    MAIL_TO = [addr.strip() for addr in os.getenv("MAIL_TO", "3433551710@qq.com,2874575651@qq.com").split(",") if addr.strip()]
    RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

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
