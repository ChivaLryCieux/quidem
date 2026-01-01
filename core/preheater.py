import os
import sys
import asyncio
import ccxt
import aiohttp
import joblib
import pandas as pd
import logging
from colorama import Fore, Style

logger = logging.getLogger(__name__)

root = os.path.dirname(os.path.dirname(__file__))
sys.path.append(root)
sys.path.append(os.path.join(root, "core"))

from core.config import Config
from core.strategy import StrategyBrain
from core.math_tools import MathUtils

def _make_exchange(use_proxy=True):
    conf = {'enableRateLimit': True, 'options': {'defaultType': 'future'}}
    if use_proxy and getattr(Config, "PROXY_URL", None):
        conf['proxies'] = {'http': Config.PROXY_URL, 'https': Config.PROXY_URL}
    try:
        return ccxt.binance(conf)
    except Exception:
        if use_proxy:
            return _make_exchange(False)
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
    print(f"{Fore.CYAN}开始统一预热器...{Style.RESET_ALL}")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ohlcv_1m, ohlcv_15m = loop.run_until_complete(_fetch_dual_async(Config.SYMBOL, warmup_1m, warmup_15m))

    brain = StrategyBrain()
    model_dir = os.path.join(root, "backtest", "models")
    model_path = os.path.join(model_dir, "rf_model.joblib")

    if os.path.exists(model_path):
        print(f"{Fore.YELLOW}加载已有模型进行增量训练...{Style.RESET_ALL}")
        try:
            brain.rf_classifier.rf_model = joblib.load(model_path)
        except Exception:
            pass

    for c in ohlcv_1m:
        brain.ingest_candle(c, '1m')

    df15_all = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    atr_series_all = MathUtils.calc_atr(df15_all) if len(df15_all) >= 15 else pd.Series([0.0] * len(df15_all))

    label_stats = {1: 0, -1: 0, 0: 0}
    correct = 0
    total_val = 0
    start_val_idx = int(len(ohlcv_15m) * 0.85)

    print(f"开始训练 {len(ohlcv_15m)} 根 15m K线...")
    for i, c in enumerate(ohlcv_15m):
        brain.ingest_candle(c, '15m')
        res = brain.analyze()
        if not res:
            continue
        atr_val = float(atr_series_all.iloc[i]) if i >= 14 else 0.0
        diff = float(c[4]) - float(c[1])
        threshold_mult = float(getattr(Config, "LABEL_ATR_MULT", 0.5))
        threshold = atr_val * threshold_mult if atr_val > 0 else 0.0
        if diff > threshold:
            label = 1
        elif diff < -threshold:
            label = -1
        else:
            label = 0
        label_stats[label] += 1
        if i >= start_val_idx:
            pred, conf = brain.rf_classifier.predict(res['features'])
            if pred == label:
                correct += 1
            total_val += 1
        brain.train_ai(res['features'], label)

    if not os.path.exists(model_dir):
        os.makedirs(model_dir, exist_ok=True)
    try:
        joblib.dump(brain.rf_classifier.rf_model, model_path)
    except Exception:
        pass

    acc = (correct / total_val) * 100 if total_val > 0 else 0.0
    signal_ratio = ((label_stats[1] + label_stats[-1]) / len(ohlcv_15m)) * 100 if len(ohlcv_15m) > 0 else 0.0

    logger.info("=" * 40)
    logger.info(f"预热报告")
    logger.info(f"样本数: {len(ohlcv_15m)}")
    logger.info(f"标签分布: 多({label_stats[1]}) | 空({label_stats[-1]}) | 观({label_stats[0]})")
    logger.info(f"有效信号占比: {signal_ratio:.1f}%")
    logger.info(f"预测准确率(Prequential): {acc:.2f}%")
    logger.info("=" * 40)

    if signal_ratio < 10:
        logger.warning("信号稀疏，考虑降低 Config.LABEL_ATR_MULT")
    if acc < 40:
        logger.warning("准确率较低，可能需要更多预热数据")
    if label_stats[1] == 0 or label_stats[-1] == 0:
        logger.error("单边标签未出现，增加 warmup_15m")

if __name__ == "__main__":
    run()
