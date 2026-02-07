
import os
import sys
import asyncio
import ccxt
import aiohttp
import pandas as pd
import logging
from colorama import Fore, Style

# Fix path to include project root
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)

from core.config.settings import Config
from core.strategy.brain import StrategyBrain
from core.utils.math_utils import MathUtils

# Simple logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Pretrain")

def _make_exchange(use_proxy=True):
    conf = {'enableRateLimit': True, 'options': {'defaultType': 'future'}}
    if use_proxy and getattr(Config, "PROXY_URL", None):
        conf['proxies'] = {'http': Config.PROXY_URL, 'https': Config.PROXY_URL}
    try:
        return ccxt.binance(conf)
    except Exception:
        if use_proxy: return _make_exchange(False)
        raise

def _symbol_to_binance(s):
    return s.replace("/", "").upper()

async def _fetch_http(symbol, timeframe, limit):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": _symbol_to_binance(symbol), "interval": timeframe, "limit": limit}
    proxy = getattr(Config, "PROXY_URL", None) or None
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params, proxy=proxy) as resp:
            data = await resp.json()
            return [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])] for x in data]

async def _fetch_dual_async(symbol, warmup_1m, warmup_15m):
    try:
        res1, res15 = await asyncio.gather(
            _fetch_http(symbol, "1m", warmup_1m + 50),
            _fetch_http(symbol, "15m", warmup_15m + 50)
        )
        return res1, res15
    except Exception:
        ex = _make_exchange(True)
        return ex.fetch_ohlcv(symbol, "1m", limit=warmup_1m + 50), ex.fetch_ohlcv(symbol, "15m", limit=warmup_15m + 50)

def run(warmup_1m=1000, warmup_15m=300):
    print(f"{Fore.CYAN}预热模型...{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}注意: 在线学习模型已移除，此脚本仅用于预热HMM模型{Style.RESET_ALL}")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        ohlcv_1m, ohlcv_15m = loop.run_until_complete(_fetch_dual_async(Config.SYMBOL, warmup_1m, warmup_15m))
    except Exception as e:
        logger.error(f"Failed to fetch data: {e}")
        return

    brain = StrategyBrain()

    # Ingest data for warmup
    for c in ohlcv_1m:
        brain.ingest_candle(c, '1m')

    print(f"Processing {len(ohlcv_15m)} 15m candles...")
    for i, c in enumerate(ohlcv_15m):
        brain.ingest_candle(c, '15m')
        res = brain.analyze()
        if not res: 
            continue

    logger.info("-" * 40)
    logger.info("预热完成")
    logger.info("-" * 40)

if __name__ == "__main__":
    run()
