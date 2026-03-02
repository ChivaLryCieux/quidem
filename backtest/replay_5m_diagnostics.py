"""5m K线信号诊断回放脚本。

用途：
1) 从指定开始时间（默认“昨天 23:00”）抓取 SOL/USDT 5m 与 15m K线；
2) 重放策略，记录每次信号出现时的技术面快照；
3) 评估信号后续 N 根K线走势（MFE/MAE）和 TP/SL 命中情况；
4) 输出 CSV 便于对照“当时信号 vs 后续走向”。

示例：
  python backtest/replay_5m_diagnostics.py
  python backtest/replay_5m_diagnostics.py --since "2026-03-01 23:00" --hours 18 --symbol SOL/USDT
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

import ccxt
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.append(ROOT)

from core.config.settings import Config
from core.strategy.brain import StrategyBrain


def make_exchange() -> ccxt.Exchange:
    conf = {"enableRateLimit": True, "options": {"defaultType": "future"}}
    if getattr(Config, "PROXY_URL", ""):
        conf["proxies"] = {"http": Config.PROXY_URL, "https": Config.PROXY_URL}
    try:
        return ccxt.binance(conf)
    except Exception:
        conf.pop("proxies", None)
        return ccxt.binance(conf)


def fetch_ohlcv(exchange: ccxt.Exchange, symbol: str, timeframe: str, since_ms: int, end_ms: int) -> list[list[float]]:
    all_rows: list[list[float]] = []
    cursor = since_ms
    while cursor < end_ms:
        rows = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
        if not rows:
            break
        for row in rows:
            if row[0] > end_ms:
                break
            if not all_rows or row[0] > all_rows[-1][0]:
                all_rows.append(row[:6])
        cursor = rows[-1][0] + 1
        time.sleep((exchange.rateLimit or 100) / 1000)
        if rows[-1][0] >= end_ms:
            break
    return [r for r in all_rows if since_ms <= r[0] <= end_ms]


def forward_outcome(df_5m: pd.DataFrame, idx: int, sig: int, horizon: int, tp_pct: float, sl_pct: float) -> dict:
    entry = float(df_5m.iloc[idx]["close"])
    future = df_5m.iloc[idx + 1: idx + 1 + horizon]
    if future.empty:
        return {"bars_checked": 0, "mfe_pct": 0.0, "mae_pct": 0.0, "path": "N/A", "exit_price": entry}

    highs = future["high"].astype(float)
    lows = future["low"].astype(float)
    if sig == 1:
        mfe = (highs.max() - entry) / entry
        mae = (lows.min() - entry) / entry
        tp = entry * (1 + tp_pct)
        sl = entry * (1 - sl_pct)
        path = "TIMEOUT"
        exit_price = float(future.iloc[-1]["close"])
        for _, row in future.iterrows():
            if float(row["low"]) <= sl:
                path, exit_price = "SL", sl
                break
            if float(row["high"]) >= tp:
                path, exit_price = "TP", tp
                break
    else:
        mfe = (entry - lows.min()) / entry
        mae = (entry - highs.max()) / entry
        tp = entry * (1 - tp_pct)
        sl = entry * (1 + sl_pct)
        path = "TIMEOUT"
        exit_price = float(future.iloc[-1]["close"])
        for _, row in future.iterrows():
            if float(row["high"]) >= sl:
                path, exit_price = "SL", sl
                break
            if float(row["low"]) <= tp:
                path, exit_price = "TP", tp
                break

    pnl_pct = (exit_price - entry) / entry if sig == 1 else (entry - exit_price) / entry
    return {
        "bars_checked": len(future),
        "mfe_pct": round(float(mfe) * 100, 4),
        "mae_pct": round(float(mae) * 100, 4),
        "path": path,
        "exit_price": round(float(exit_price), 6),
        "pnl_pct": round(float(pnl_pct) * 100, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SOL/USDT")
    parser.add_argument("--since", default="")
    parser.add_argument("--hours", type=float, default=16.0, help="分析窗口小时数")
    parser.add_argument("--horizon", type=int, default=12, help="每个信号向后评估的K线数量")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    now = datetime.utcnow()
    default_since = (now - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
    since_dt = pd.to_datetime(args.since) if args.since else default_since
    end_dt = since_dt + timedelta(hours=args.hours)

    since_ms = int(pd.Timestamp(since_dt).timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_dt).timestamp() * 1000)

    ex = make_exchange()
    data_5m = fetch_ohlcv(ex, args.symbol, "5m", since_ms - 400 * 5 * 60 * 1000, end_ms)
    data_15m = fetch_ohlcv(ex, args.symbol, "15m", since_ms - 200 * 15 * 60 * 1000, end_ms)

    df_5m = pd.DataFrame(data_5m, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_15m = pd.DataFrame(data_15m, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_5m["taker_buy"] = df_5m["volume"] * 0.5
    df_15m["taker_buy"] = df_15m["volume"] * 0.5

    brain = StrategyBrain()
    records = []
    i15 = 0

    for i, row in df_5m.iterrows():
        ts = int(row["timestamp"])
        while i15 < len(df_15m) and int(df_15m.iloc[i15]["timestamp"]) <= ts:
            brain.ingest_candle(df_15m.iloc[i15].tolist(), timeframe="15m")
            i15 += 1

        brain.ingest_candle(row.tolist(), timeframe="5m")
        if ts < since_ms:
            continue

        analysis = brain.analyze(orderbook=None)
        if not analysis:
            continue

        sig, lev = brain.get_entry_signal(analysis, float(row["close"]))
        if sig == 0:
            continue

        out = forward_outcome(df_5m, int(i), sig, args.horizon, Config.MIN_TP_DISTANCE, Config.MAX_SL_DISTANCE)
        records.append({
            "timestamp": pd.to_datetime(ts, unit="ms"),
            "signal": "LONG" if sig == 1 else "SHORT",
            "price": round(float(row["close"]), 6),
            "lev": lev,
            "adx": round(float(analysis.get("adx", 0)), 3),
            "vwap_distance": round(float(analysis.get("vwap_distance", 0)), 4),
            "kdj_k": round(float(analysis.get("kdj_k", 50)), 3),
            "supertrend_5m": int(analysis.get("supertrend_direction", 0)),
            **out,
        })

    result = pd.DataFrame(records)
    out_path = args.out or f"backtest/outputs/signal_replay_{pd.Timestamp.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")

    if len(result) == 0:
        print("⚠️ 在指定窗口内未捕获到开仓信号。")
        return

    wins = int((result["pnl_pct"] > 0).sum())
    print(f"✅ 输出: {out_path}")
    print(f"信号数={len(result)} | 胜率={wins / len(result) * 100:.2f}% | 平均pnl={result['pnl_pct'].mean():.3f}%")
    print(result[["timestamp", "signal", "price", "path", "pnl_pct", "mfe_pct", "mae_pct"]].tail(12).to_string(index=False))


if __name__ == "__main__":
    main()
