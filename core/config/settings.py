import logging
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer env %s=%r, using %r", name, value, default)
        return default


def _env_float(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid float env %s=%r, using %r", name, value, default)
        return default


def _env_list(name, default):
    value = os.getenv(name)
    if value is None:
        value = default
    return [item.strip() for item in value.split(",") if item.strip()]


class Config:
    """Runtime configuration for the personal trading framework.

    Defaults keep the current SOL/USDT workflow intact, while environment
    variables make the bot easier to reuse across symbols and machines.
    """

    # 代理与网络
    PROXY_ENABLED = _env_bool("PROXY_ENABLED", True)
    PROXY_PORT = _env_int("PROXY_PORT", 7890)
    PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
    PROXY_URL = os.getenv("PROXY_URL", f"http://{PROXY_HOST}:{PROXY_PORT}") if PROXY_ENABLED else ""
    HTTP_TIMEOUT_MS = _env_int("HTTP_TIMEOUT_MS", 10000)
    WS_READY_TIMEOUT_SEC = _env_int("WS_READY_TIMEOUT_SEC", 30)
    WS_RECONNECT_DELAY_SEC = _env_float("WS_RECONNECT_DELAY_SEC", 3.0)

    # 交易所 API
    API_KEY = os.getenv("BINANCE_API_KEY")
    API_SECRET = os.getenv("BINANCE_SECRET")

    # 交易标的与参数
    SYMBOL = os.getenv("SYMBOL", "SOL/USDT")
    SYMBOL_WS = os.getenv("SYMBOL_WS", SYMBOL.replace("/", "").lower())  # WebSocket用的全小写无斜杠名称
    TIMEFRAME_SIGNAL = os.getenv("TIMEFRAME_SIGNAL", "5m")   # 信号生成和交易执行周期
    TIMEFRAME_TREND = os.getenv("TIMEFRAME_TREND", "15m")    # 中趋势过滤周期
    TIMEFRAME_MACRO = os.getenv("TIMEFRAME_MACRO", "1h")     # 宏观趋势过滤周期（刻时模型）
    TIMEFRAME = TIMEFRAME_SIGNAL                             # 主周期，兼容旧代码

    # 资金管理
    PAPER_BALANCE = _env_float("PAPER_BALANCE", 100.0)
    MIN_LEVERAGE = _env_float("MIN_LEVERAGE", 5.0)
    MAX_LEVERAGE = _env_float("MAX_LEVERAGE", 10.0)       # 降低杠杆，减少手续费影响
    DEFAULT_LEVERAGE = _env_float("DEFAULT_LEVERAGE", 10.0)
    RISK_APPETITE = _env_float("RISK_APPETITE", 0.05)      # 目标单笔净利 5%
    POSITION_ALLOC_RATIO = _env_float("POSITION_ALLOC_RATIO", 0.20)
    TAKER_FEE_RATE = _env_float("TAKER_FEE_RATE", 0.0005)

    MAX_FUNDING_RATE_THRESHOLD = _env_float("MAX_FUNDING_RATE_THRESHOLD", 0.0005)

    # 策略参数
    BAILOUT_ON_NTH_FLIP = _env_int("BAILOUT_ON_NTH_FLIP", 99)  # 基本禁用flip平仓，只靠TP/SL
    FEE_BUFFER_PCT = _env_float("FEE_BUFFER_PCT", 0.0012)
    MIN_ATR_PCT = _env_float("MIN_ATR_PCT", 0.0020)
    MIN_TP_DISTANCE = _env_float("MIN_TP_DISTANCE", 0.012)   # 止盈目标：1.2%价格波动 (10x杠杆=12%本金)
    MAX_SL_DISTANCE = _env_float("MAX_SL_DISTANCE", 0.004)   # 硬止损：0.4%价格反向 (10x杠杆=4%本金)
    # 盈亏比 3:1，30%胜率即可打平，60%胜率大幅盈利

    # 微观结构
    OBI_THRESHOLD_TREND = _env_float("OBI_THRESHOLD_TREND", -0.2)
    OBI_THRESHOLD_BREAKOUT = _env_float("OBI_THRESHOLD_BREAKOUT", 0.1)
    MAX_SPREAD_PCT = _env_float("MAX_SPREAD_PCT", 0.001)
    LABEL_ATR_MULT = _env_float("LABEL_ATR_MULT", 0.5)
    BACKTEST_MODE = _env_bool("BACKTEST_MODE", True)
    FUNDING_EVENT_INTERVAL_HOURS = _env_int("FUNDING_EVENT_INTERVAL_HOURS", 8)
    BACKTEST_FUNDING_RATE_PCT = _env_float("BACKTEST_FUNDING_RATE_PCT", 0.0000)

    #邮件报告开关
    ENABLE_MAIL_REPORT = _env_bool("ENABLE_MAIL_REPORT", False)
    MAIL_FROM = os.getenv("MAIL_FROM", "")              # 发件人，必须在 .env 中显式配置（例如 "CTA q-bot <foo@your-domain.com>"）
    MAIL_TO = _env_list("MAIL_TO", "")                  # 收件人，多个以英文逗号分隔
    RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = _env_int("REDIS_PORT", 6379)
    REDIS_DB = _env_int("REDIS_DB", 0)
    REDIS_SOCKET_TIMEOUT_SEC = _env_float("REDIS_SOCKET_TIMEOUT_SEC", 1.0)
    REPORT_ARCHIVE_DIR = os.getenv("REPORT_ARCHIVE_DIR", "~/quant_archive")


    # 爆仓预警开关与参数
    ENABLE_LIQUIDATION_ALERT = _env_bool("ENABLE_LIQUIDATION_ALERT", False)
    LIQUIDATION_ALERT_SYMBOL = os.getenv("LIQUIDATION_ALERT_SYMBOL", "SOLUSDT")
    LIQUIDATION_ALERT_WINDOW_SEC = _env_int("LIQUIDATION_ALERT_WINDOW_SEC", 300)
    LIQUIDATION_ALERT_THRESHOLD_USD = _env_float("LIQUIDATION_ALERT_THRESHOLD_USD", 1000000)
    LIQUIDATION_ALERT_POLL_INTERVAL_SEC = _env_int("LIQUIDATION_ALERT_POLL_INTERVAL_SEC", 30)
    LIQUIDATION_ALERT_COOLDOWN_SEC = _env_int("LIQUIDATION_ALERT_COOLDOWN_SEC", 900)

    # 日志配置
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR = os.getenv("LOG_DIR", "logs")
    LOG_FILE = os.getenv("LOG_FILE", "quant_bot.log")
    LOG_TO_CONSOLE = _env_bool("LOG_TO_CONSOLE", True)
    LOG_MAX_BYTES = _env_int("LOG_MAX_BYTES", 10 * 1024 * 1024)  # 10MB
    LOG_BACKUP_COUNT = _env_int("LOG_BACKUP_COUNT", 5)

    # Web GUI 配置
    WEB_ENABLED = _env_bool("WEB_ENABLED", True)
    WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT = _env_int("WEB_PORT", 8000)
    WEB_AUTO_OPEN = _env_bool("WEB_AUTO_OPEN", True)

    @staticmethod
    def exchange_proxies():
        if not Config.PROXY_ENABLED or not Config.PROXY_URL:
            return {}
        return {'http': Config.PROXY_URL, 'https': Config.PROXY_URL}

    @staticmethod
    def redis_kwargs(timeout=None):
        socket_timeout = Config.REDIS_SOCKET_TIMEOUT_SEC if timeout is None else timeout
        return {
            "host": Config.REDIS_HOST,
            "port": Config.REDIS_PORT,
            "db": Config.REDIS_DB,
            "socket_timeout": socket_timeout,
        }

    @staticmethod
    def validate_for_mode(is_live=False):
        issues = []
        if Config.DEFAULT_LEVERAGE <= 0:
            issues.append("DEFAULT_LEVERAGE must be > 0")
        if Config.MAX_LEVERAGE < Config.MIN_LEVERAGE:
            issues.append("MAX_LEVERAGE must be >= MIN_LEVERAGE")
        if Config.DEFAULT_LEVERAGE > Config.MAX_LEVERAGE:
            issues.append("DEFAULT_LEVERAGE must be <= MAX_LEVERAGE")
        if not (0 < Config.POSITION_ALLOC_RATIO <= 1):
            issues.append("POSITION_ALLOC_RATIO must be in (0, 1]")
        if Config.MIN_TP_DISTANCE <= 0:
            issues.append("MIN_TP_DISTANCE must be > 0")
        if Config.MAX_SL_DISTANCE <= 0:
            issues.append("MAX_SL_DISTANCE must be > 0")
        if is_live and (not Config.API_KEY or not Config.API_SECRET):
            issues.append("BINANCE_API_KEY and BINANCE_SECRET are required for live mode")
        if Config.ENABLE_MAIL_REPORT:
            if not Config.RESEND_API_KEY:
                issues.append("RESEND_API_KEY is required when ENABLE_MAIL_REPORT=true")
            if not Config.MAIL_TO:
                issues.append("MAIL_TO is required when ENABLE_MAIL_REPORT=true")
        return issues

    @staticmethod
    def setup_proxy():
        # 如果需要设置系统级代理环境变量
        if Config.PROXY_ENABLED and Config.PROXY_URL:
            os.environ["HTTP_PROXY"] = Config.PROXY_URL
            os.environ["HTTPS_PROXY"] = Config.PROXY_URL
