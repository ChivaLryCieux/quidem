"""
回测器 - 基于现有 core 模块的统一回测系统

使用示例：
  python backtest/backtester.py --symbol SOL/USDT --balance 100
  python backtest/backtester.py --symbol SOL/USDT --lookback-days 30
  python backtest/backtester.py --symbol SOL/USDT --since "2025-01-01" --end "2025-02-01"

输出文件（默认保存到 backtest/outputs/YYYYMMDD_HHMMSS/）：
  - 01_price.png: 价格与交易标记
  - 02_equity_curve.png: 权益曲线
  - 03_drawdown.png: 回撤曲线
  - backtest_YYYYMMDD_HHMMSS.csv: 交易明细
"""

# ========== 回测超参数配置 ==========
KLINE_LIMIT_15M = 35000  # 15分钟K线数量
KLINE_LIMIT_5M = 100000  # 5分钟K线数量

import os
import sys
import ccxt
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
from matplotlib.lines import Line2D
from datetime import datetime, timedelta
import argparse
import time

plt.style.use('seaborn-v0_8-darkgrid')
plt.rcParams['axes.unicode_minus'] = False

_preferred_fonts = ["Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Arial Unicode MS", "DejaVu Sans"]
_available_font_names = {f.name for f in fm.fontManager.ttflist}
_chosen_font = next((n for n in _preferred_fonts if n in _available_font_names), None)
if _chosen_font:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [_chosen_font]

root = os.path.dirname(os.path.dirname(__file__))
sys.path.append(root)
sys.path.append(os.path.join(root, "core"))

from core.config import Config
from core.strategy import StrategyBrain
from core.risk import RiskManager

def _make_exchange(use_proxy=True):
    conf = {'enableRateLimit': True, 'options': {'defaultType': 'future'}}
    if use_proxy and hasattr(Config, 'PROXY_URL'):
        conf['proxies'] = {'http': Config.PROXY_URL, 'https': Config.PROXY_URL}
    try:
        return ccxt.binance(conf)
    except Exception:
        if use_proxy:
            return _make_exchange(False)
        raise

def _fetch_ohlcv(exchange, symbol, timeframe, limit, since=None):
    print(f"📡 正在获取 {symbol} {timeframe} K线数据 (目标: {limit})...")
    all_ohlcv = []
    
    fetch_limit = 1000 
    current_since = since
    if current_since is None:
        try:
            tf_sec = exchange.parse_timeframe(timeframe)
            tf_ms = int(tf_sec * 1000)
            current_since = int(exchange.milliseconds() - (int(limit) * tf_ms))
        except Exception:
            current_since = None
    
    retry_count = 0
    max_retries = 3

    while len(all_ohlcv) < limit:
        left = limit - len(all_ohlcv)
        this_limit = min(left, fetch_limit)
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=this_limit)
            if ohlcv:
                ohlcv = [c[:6] for c in ohlcv if c is not None and len(c) >= 6]
            if not ohlcv:
                break
            
            last_time = ohlcv[-1][0]
            if current_since is not None and last_time == current_since:
                break

            if all_ohlcv:
                prev_last = all_ohlcv[-1][0]
                if ohlcv[0][0] <= prev_last:
                    ohlcv = [c for c in ohlcv if c[0] > prev_last]
                    if not ohlcv:
                        break
                    last_time = ohlcv[-1][0]

            current_since = last_time + 1 
            
            all_ohlcv.extend(ohlcv)
            print(f"   已获取 {len(all_ohlcv)}/{limit} 根...")
            
            time.sleep(exchange.rateLimit / 1000.0 if exchange.rateLimit else 0.1)
            retry_count = 0
            
        except Exception as e:
            print(f"⚠️ 获取数据出错 (重试 {retry_count+1}/{max_retries}): {e}")
            retry_count += 1
            time.sleep(2)
            if retry_count >= max_retries:
                break
            
    return all_ohlcv

class StrategyBacktesterUnified:
    def __init__(self, symbol=None, balance=100.0, since_ms=None, end_ms=None, timeformat="%Y-%m-%d %H:%M", warmup_steps=100):
        setattr(Config, "BACKTEST_MODE", True)
        self.symbol = symbol or Config.SYMBOL
        self.initial_balance = balance
        self.balance = balance
        
        self.brain = StrategyBrain()
        self.risk = RiskManager()
        
        self.position = self._reset_position()
        self.trades = []
        self.data_1m_cache = []
        self.slippage = getattr(Config, "SLIPPAGE_BPS", 0.0002)
        
        self.since_ms = since_ms
        self.end_ms = end_ms
        self.timeformat = timeformat
        self.warmup_steps = warmup_steps
        self.plot_max_points = 10000
        self.plot_dpi = 160
        self.plot_mtm_equity = False
        self.plot_resample = ""
        self.plot_show_trades = True
        self.plot_show_drawdown = True
        self.plot_figsize = (14, 9)
        self.inject_amount = 1000.0
        self.title_leverage = 2.0
        self.run_dir = ""
        self.run_tag = ""
        
        self.save_path = None
        self.snapshots = []
        self.last_snapshot_time = 0.0
        self.profit_flip_count = 0
        self.was_in_profit = False
        
        # 回测统计（仅记录注资类指标；交易统计在 report 中基于 self.trades 计算）
        self.bankruptcy_count = 0
        self.total_injected = 0.0

    def _reset_position(self):
        return {
            'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 
            'entry_time': 0, 'last_funding_index': 0,
            'entry_rsi': 0.0, 'entry_atr': 0.0, 'entry_regime': 'INIT', 'cluster': 5,
            'leverage': 0.0
        }

    def _inject_capital(self, current_time_ms):
        """当余额<=0时触发注资，记录一次 INJECTION 交易。"""
        inject_amount = float(self.inject_amount)
        self.balance += float(inject_amount)
        self.total_injected += float(inject_amount)
        self.bankruptcy_count += 1
        
        t_str = pd.to_datetime(current_time_ms, unit='ms').strftime('%Y-%m-%d %H:%M')
        print(f"💀 [{t_str}] 触发爆仓保护 | 注入: ${inject_amount} | 当前余额: ${self.balance:.2f} | 总爆仓: {self.bankruptcy_count}")
        
        self.trades.append({
            'entry_time': current_time_ms,
            'exit_time': current_time_ms,
            'mode': 'INJECTION',
            'action': '注资',
            'entry_price': 0, 'exit_price': 0, 'amount': 0, 'leverage': 0,
            'pnl': 0, 'fee': 0, 'balance': self.balance,
            'regime': 'BANKRUPTCY', 'reason': 'InjectOnLoss',
            'duration_min': 0, 'direction': 'NONE',
            'entry_rsi': 0, 'exit_rsi': 0, 'entry_atr': 0, 'exit_atr': 0, 'flips': 0, 'cluster': 5
        })

    def _apply_entry_slippage(self, sig, price):
        return price * (1 + self.slippage) if sig == 1 else price * (1 - self.slippage)

    def _apply_exit_slippage(self, side, price):
        return price * (1 - self.slippage) if side == "sell" else price * (1 + self.slippage)

    def _attempt_entry(self, analysis, price, current_time_ms, funding_rate=0.0):
        if self.balance <= 0:
            self._inject_capital(current_time_ms)

        sig, lev = self.brain.get_entry_signal(analysis, price)
        if sig == 0:
            return
        lev = float(lev) if lev else float(getattr(Config, "MAX_LEVERAGE", 1.0))
        lev = max(1.0, lev)

        risky, _ = self.risk.check_funding_rate_risk(sig, funding_rate)
        if risky:
            return

        usable_balance = max(self.balance, 0)
        eprice = self._apply_entry_slippage(sig, price)
        
        atr_15m = analysis.get('atr', 0.0) if analysis else 0.0
        atr_1m = analysis.get('atr', 0.0) if analysis else 0.0
        curr_rsi = analysis.get('rsi', 50.0)
        cluster_info = analysis.get('cluster', (99, 0))

        tp_dist = eprice * Config.MIN_TP_DISTANCE  # 止盈: 0.35% (简化，不依赖ATR)
        sl_dist = eprice * Config.MAX_SL_DISTANCE   # 止损: 0.6% (盈亏比约1:1.7)

        risk_pct = float(getattr(Config, "RISK_APPETITE", 0.03))
        risk_budget = max(0.0, usable_balance * risk_pct)
        # 每次只用 20% 资金开仓 (原98%导致单次亏损过大)
        position_size_pct = 0.20
        amt_by_margin = (usable_balance * position_size_pct) / ((1 / lev) + Config.TAKER_FEE_RATE) / price
        amt = max(0.0, amt_by_margin)
        
        if amt * price < 5.0:
            return

        self.position = {
            'size': amt if sig == 1 else -amt,
            'entry_price': eprice,
            'entry_time': int(current_time_ms),
            'sl': eprice - sl_dist if sig == 1 else eprice + sl_dist,
            'tp': eprice + tp_dist if sig == 1 else eprice - tp_dist,
            'last_funding_index': int(current_time_ms // (getattr(Config, "FUNDING_EVENT_INTERVAL_HOURS", 8) * 3600 * 1000)),
            'entry_rsi': curr_rsi,
            'entry_atr': atr_15m,
            'entry_regime': self.brain.state,
            'cluster': cluster_info[0],
            'leverage': lev
        }
        self.snapshots = []
        self.last_snapshot_time = 0.0
        self.profit_flip_count = 0
        self.was_in_profit = False

    def _manage_position(self, price, analysis, current_time_ms, funding_rate=0.0):
        pos = self.position
        if pos['size'] == 0: return

        # 资金费率模拟：按事件间隔收取/支付 funding（方向决定正负）
        rate = getattr(Config, "BACKTEST_FUNDING_RATE_PCT", 0.0)
        if rate != 0.0:
            idx_now = int(current_time_ms // (getattr(Config, "FUNDING_EVENT_INTERVAL_HOURS", 8) * 3600 * 1000))
            last_idx = pos.get('last_funding_index', idx_now)
            if idx_now > last_idx:
                events = idx_now - last_idx
                pos_val = abs(pos['size']) * price
                fee = pos_val * rate * events
                payment = fee if pos['size'] > 0 else -fee
                self.balance -= payment
                self.position['last_funding_index'] = idx_now

        # 盈亏 Flip：用于风险管理统计（从未盈利 -> 盈利 的切换次数）
        raw_pnl_pct = (price - pos['entry_price']) / pos['entry_price'] * (1 if pos['size'] > 0 else -1)
        is_prof = raw_pnl_pct > Config.FEE_BUFFER_PCT
        if not self.was_in_profit and is_prof:
            self.profit_flip_count += 1
        self.was_in_profit = is_prof
        
        atr_1m = analysis.get('atr', 0.0) if analysis else 0.0
        
        # 交易期间快照：每 15 分钟记录一次，便于复盘
        now_sec = current_time_ms / 1000.0
        if now_sec - self.last_snapshot_time >= 900:
            pnl = (price - pos['entry_price']) * pos['size']
            self.snapshots.append({'time': now_sec, 'price': price, 'pnl': pnl, 'regime': self.brain.state})
            self.last_snapshot_time = now_sec

        should_exit, reason = self.risk.check_exit_conditions(
            pos, price, current_time_ms, self.profit_flip_count, atr_1m, self.balance
        )
        if should_exit:
            self._execute_exit(reason, price, current_time_ms, analysis)

    def _execute_exit(self, reason, price, current_time_ms, analysis=None, funding_rate=0.0):
        pos_size = self.position['size']
        if pos_size == 0: return
        
        entry = self.position['entry_price']
        lev = float(self.position.get('leverage') or getattr(Config, "MAX_LEVERAGE", 1.0))
        lev = max(1.0, lev)
        raw_pnl = (price - entry) * pos_size
        fee = abs(pos_size) * (entry + price) * Config.TAKER_FEE_RATE
        net_pnl = raw_pnl - fee
        self.balance += net_pnl
        
        margin_used = abs(pos_size) * entry / lev
        _ = self.risk.activate_circuit_breaker(net_pnl, margin_used, now_ms=current_time_ms)
        
        exit_rsi = analysis.get('rsi', 0.0) if analysis else 0.0
        exit_atr = analysis.get('atr', 0.0) if analysis else 0.0
        
        self.trades.append({
            'entry_time': self.position['entry_time'],
            'exit_time': int(current_time_ms),
            'mode': 'BACKTEST',
            'action': '平仓',
            'direction': 'LONG' if pos_size > 0 else 'SHORT',
            'entry_price': entry,
            'exit_price': price,
            'amount': abs(pos_size),
            'leverage': lev,
            'pnl': net_pnl,
            'fee': fee,
            'balance': self.balance,
            'regime': self.position.get('entry_regime', 'UNKNOWN'),
            'reason': reason,
            'duration_min': (int(current_time_ms) - self.position['entry_time']) / 60000.0,
            'entry_rsi': self.position.get('entry_rsi', 0.0),
            'exit_rsi': exit_rsi,
            'entry_atr': self.position.get('entry_atr', 0.0),
            'exit_atr': exit_atr,
            'flips': self.profit_flip_count,
            'cluster': self.position.get('cluster', 99)
        })
        
        self.snapshots = []
        self.last_snapshot_time = 0.0
        self.position = self._reset_position()
        
        if self.balance <= 0:
            self._inject_capital(current_time_ms)

    def _intrabar_exit(self, c1, current_time_ms, analysis=None):
        if self.position['size'] == 0: return False
        h, l = float(c1[2]), float(c1[3])
        pos = self.position
        
        triggered, reason, exit_price = False, "", 0.0
        
        if pos['size'] > 0:
            # if l <= pos['sl']:  # 止损已禁用
            #     exit_price, reason, triggered = self._apply_exit_slippage("sell", pos['sl']), "🛑 SL (Intra)", True
            if h >= pos['tp']:
                exit_price, reason, triggered = self._apply_exit_slippage("sell", pos['tp']), "💰 TP (Intra)", True
        else:
            # if h >= pos['sl']:  # 止损已禁用
            #     exit_price, reason, triggered = self._apply_exit_slippage("buy", pos['sl']), "🛑 SL (Intra)", True
            if l <= pos['tp']:
                exit_price, reason, triggered = self._apply_exit_slippage("buy", pos['tp']), "💰 TP (Intra)", True
                
        if triggered:
            self._execute_exit(reason, exit_price, current_time_ms, analysis)
            return True
        return False

    def run(self, limit_1m=500000, limit_15m=34000):
        print(f"🚀 开始回测: {self.symbol} | 初始资金: {self.balance} | 滑点: {self.slippage*10000:.1f}bps")

        base_dir = self.save_path if self.save_path and os.path.isdir(self.save_path) else os.path.join(os.path.dirname(__file__), "outputs")
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_tag = ts_str
        self.run_dir = os.path.join(base_dir, ts_str)
        os.makedirs(self.run_dir, exist_ok=True)
        print(f"📁 输出目录: {self.run_dir}")

        ex = _make_exchange(True)
        data_5m = _fetch_ohlcv(ex, self.symbol, '5m', limit_1m, since=self.since_ms)
        data_15m = _fetch_ohlcv(ex, self.symbol, '15m', limit_15m, since=self.since_ms)
        
        if self.end_ms:
            data_5m = [c for c in data_5m if c[0] <= self.end_ms]
            data_15m = [c for c in data_15m if c[0] <= self.end_ms]
            
        self.data_1m_cache = data_5m  # 兼容性保留
        print(f"数据就绪: 5m={len(data_5m)}, 15m={len(data_15m)}")
        
        idx_15 = 0
        processed_count = 0
        total_steps = len(data_5m)
        
        for i, c5 in enumerate(data_5m):
            current_time_ms = int(c5[0])
            
            if i % 5000 == 0:
                print(f"进度: {i}/{total_steps} ({(i/total_steps)*100:.1f}%) | 余额: {self.balance:.2f} | 交易: {len(self.trades)}")

            # 15m：用已完成的 15m K 线更新特征；只处理时间不晚于当前 5m 的 15m K
            while idx_15 < len(data_15m) and data_15m[idx_15][0] <= c5[0]:
                c15 = data_15m[idx_15]
                self.brain.ingest_candle(c15, '15m')
                idx_15 += 1

            # 5m：执行交易逻辑
            self.brain.ingest_candle(c5, '5m')
            analysis = self.brain.analyze()
            
            if not analysis: continue
            
            processed_count += 1
            if processed_count < self.warmup_steps: continue

            if self._intrabar_exit(c5, current_time_ms, analysis): continue
            
            price = float(c5[4])
            
            # 开仓逻辑
            if self.position['size'] == 0 and not self.risk.is_in_cooldown(now_ms=current_time_ms):
                self._attempt_entry(analysis, price, current_time_ms)
            
            # 持仓管理
            if self.position['size'] != 0:
                self._manage_position(price, analysis, current_time_ms)
        
        # 回测结束：若仍持仓则按最后一根K线收盘价平仓
        if self.position['size'] != 0 and len(data_5m) > 0:
            self._execute_exit("结束平仓", float(data_5m[-1][4]), int(data_5m[-1][0]))
            
        self._save_csv()
        self._report()

    def _save_csv(self):
        if not self.trades: return
        
        tag = self.run_tag if isinstance(self.run_tag, str) and self.run_tag else datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"backtest_{tag}.csv"
        out_dir = self.run_dir if self.run_dir and os.path.isdir(self.run_dir) else os.getcwd()
        fpath = os.path.join(out_dir, fname)
        
        df = pd.DataFrame(self.trades)
        df['Time'] = pd.to_datetime(df['exit_time'], unit='ms')
        df['Duration_Str'] = df['duration_min'].apply(lambda x: f"{int(x)}m 0s" if pd.notnull(x) else "")
        
        cols = {
            'Time': 'Time', 'action': 'Action', 'reason': 'Reason', 'direction': 'Direction',
            'Duration_Str': 'Duration', 'regime': 'Entry_Regime', 
            'flips': 'Flips', 'exit_price': 'Price', 'pnl': 'PnL', 'balance': 'Balance', 'cluster': 'Cluster'
        }
        
        out_df = pd.DataFrame()
        for k, v in cols.items():
            out_df[v] = df[k] if k in df.columns else 0
            
        out_df.to_csv(fpath, index=False, encoding='utf-8-sig')
        print(f"📄 交易记录已保存: {fpath}")

    def _report(self):
        real_trades = [t for t in self.trades if t['mode'] != 'INJECTION']
        if not real_trades:
            print("无有效交易")
            self._plot()
            return
            
        wins = [t for t in real_trades if t['pnl'] > 0]
        losses = [t for t in real_trades if t['pnl'] <= 0]
        total_pnl = sum(t['pnl'] for t in real_trades)
        
        print("\n" + "="*40)
        print(f"📊 回测统计")
        print("="*40)
        print(f"总交易: {len(real_trades)} | 爆仓注入: {self.bankruptcy_count} (${self.total_injected:.0f})")
        print(f"净盈亏: {total_pnl:.2f} | 最终权益: {self.balance:.2f}")
        print(f"胜率: {(len(wins)/len(real_trades)*100):.1f}%")
        print("="*40)
        
        self._plot()

    def _plot(self):
        if not self.data_1m_cache: return

        ohlcv_rows = [c[:6] for c in self.data_1m_cache if c is not None and len(c) >= 6]
        if not ohlcv_rows:
            return
        ohlcv_df = pd.DataFrame(
            ohlcv_rows,
            columns=["ts", "open", "high", "low", "close", "volume"]
        )
        ohlcv_df["ts"] = pd.to_datetime(ohlcv_df["ts"], unit="ms")
        ohlcv_df = ohlcv_df.set_index("ts").sort_index()

        plot_df = ohlcv_df
        if isinstance(self.plot_resample, str) and self.plot_resample.strip():
            rule = self.plot_resample.strip()
            plot_df = (
                ohlcv_df.resample(rule)
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna()
            )

        max_points = int(self.plot_max_points) if self.plot_max_points else 0
        step = 1 if max_points <= 0 else max(1, len(plot_df) // max_points)
        plot_df = plot_df.iloc[::step]

        times = plot_df.index.to_pydatetime()
        prices = plot_df["close"].astype(float).to_numpy()

        out_dir = self.run_dir if self.run_dir and os.path.isdir(self.run_dir) else os.getcwd()

        span_days = (times[-1] - times[0]).total_seconds() / 86400.0 if len(times) >= 2 else 0.0
        locator = mdates.AutoDateLocator(minticks=4, maxticks=12)
        if span_days <= 2:
            formatter = mdates.DateFormatter('%m-%d %H:%M')
        elif span_days <= 90:
            formatter = mdates.DateFormatter('%Y-%m-%d')
        else:
            formatter = mdates.DateFormatter('%Y-%m')

        # 交易标记：入场/出场点、时间竖线、成交价与 close 的偏差细线
        longs_xy = []
        shorts_xy = []
        exits_xy = []
        entry_vlines = []
        exit_vlines = []
        slippage_segments = []
        if bool(self.plot_show_trades):
            valid_trades = [t for t in self.trades if t.get('mode') != 'INJECTION']
            if len(valid_trades) > 2000:
                k = max(1, len(valid_trades) // 2000)
                valid_trades = valid_trades[::k]

            if len(times) > 0:
                left_bound = plot_df.index[0]
                right_bound = plot_df.index[-1]
                plot_index = plot_df.index
                offset_dt = timedelta(0)
                if len(plot_index) >= 2:
                    avg_td = (plot_index[-1] - plot_index[0]) / max(1, len(plot_index) - 1)
                    try:
                        offset_dt = (avg_td * 0.08).to_pytimedelta()
                    except Exception:
                        offset_dt = timedelta(0)
                for t in valid_trades:
                    entry_time = t.get("entry_time")
                    entry_price = t.get("entry_price")
                    if entry_time is None or entry_price is None:
                        continue
                    entry_dt = pd.to_datetime(int(entry_time), unit="ms")
                    if entry_dt < left_bound or entry_dt > right_bound:
                        entry_dt = None

                    if entry_dt is not None:
                        x = entry_dt.to_pydatetime()
                        y = float(entry_price)
                        idx = int(plot_index.get_indexer([entry_dt], method="nearest")[0])
                        if 0 <= idx < len(plot_df):
                            y_close = float(plot_df["close"].iloc[idx])
                            x_line = x + offset_dt
                            if t.get("direction") == "LONG":
                                slippage_segments.append((x, x_line, y, y_close, "g"))
                            elif t.get("direction") == "SHORT":
                                slippage_segments.append((x, x_line, y, y_close, "r"))

                        if t.get("direction") == "LONG":
                            longs_xy.append((x, y))
                        elif t.get("direction") == "SHORT":
                            shorts_xy.append((x, y))
                        entry_vlines.append(x)

                    exit_time = t.get("exit_time")
                    exit_price = t.get("exit_price")
                    if exit_time is not None and exit_price is not None:
                        exit_dt = pd.to_datetime(int(exit_time), unit="ms")
                        if left_bound <= exit_dt <= right_bound:
                            x_exit = exit_dt.to_pydatetime()
                            exits_xy.append((x_exit, float(exit_price)))
                            exit_vlines.append(x_exit)

        # 输出 01_price.png：价格(close)与交易标记
        fig_price, ax_price = plt.subplots(1, 1, figsize=tuple(self.plot_figsize))
        ax_price.plot(times, prices, color='gray', alpha=0.6, lw=1)
        if bool(self.plot_show_trades):
            if entry_vlines:
                for x in entry_vlines:
                    ax_price.axvline(x, color="green", alpha=0.15, linewidth=0.8, zorder=1)
            if exit_vlines:
                for x in exit_vlines:
                    ax_price.axvline(x, color="red", alpha=0.15, linewidth=0.8, zorder=1)
            if slippage_segments:
                for x0, x1, y_trade, y_close, c in slippage_segments:
                    ax_price.plot([x0, x1], [y_trade, y_trade], color=c, lw=0.6, alpha=0.55, zorder=2)
                    ax_price.plot([x1, x1], [y_trade, y_close], color=c, lw=0.6, alpha=0.55, zorder=2)
            if longs_xy:
                xs, ys = zip(*longs_xy)
                ax_price.scatter(
                    xs,
                    ys,
                    c='g', marker='^', s=14, alpha=0.85, label='Long', zorder=3
                )
            if shorts_xy:
                xs, ys = zip(*shorts_xy)
                ax_price.scatter(
                    xs,
                    ys,
                    c='r', marker='v', s=14, alpha=0.85, label='Short', zorder=3
                )
            if exits_xy:
                xs, ys = zip(*exits_xy)
                ax_price.scatter(xs, ys, c="red", marker="x", s=18, alpha=0.85, zorder=3)

            legend_handles = [
                Line2D([0], [0], color='gray', label='价格(close)', lw=1, alpha=0.6),
                Line2D([0], [0], marker='^', color='g', linestyle='None', label='做多开仓', markersize=7),
                Line2D([0], [0], marker='v', color='r', linestyle='None', label='做空开仓', markersize=7),
                Line2D([0], [0], marker='x', color='red', linestyle='None', label='平仓', markersize=7),
                Line2D([0], [0], color='green', linestyle='-', alpha=0.15, label='入场时间'),
                Line2D([0], [0], color='red', linestyle='-', alpha=0.15, label='出场时间'),
            ]
            ax_price.legend(handles=legend_handles, loc='upper left')
        ax_price.set_title(f"{self.symbol} Price")
        ax_price.grid(True)
        ax_price.xaxis.set_major_locator(locator)
        ax_price.xaxis.set_major_formatter(formatter)
        plt.xticks(rotation=30)
        fig_price.tight_layout()
        plt.savefig(os.path.join(out_dir, "01_price.png"), dpi=int(self.plot_dpi), bbox_inches="tight")
        plt.close(fig_price)

        # 输出 02_equity_curve.png：权益曲线（含注资标记）
        eq_points = [{"ts": int(self.data_1m_cache[0][0]), "equity": float(self.initial_balance)}]
        for t in sorted(self.trades, key=lambda x: int(x.get("exit_time", 0))):
            eq_points.append({"ts": int(t["exit_time"]), "equity": float(t.get("balance", 0.0))})

        eq_df = pd.DataFrame(eq_points)
        eq_df["ts"] = pd.to_datetime(eq_df["ts"], unit="ms")
        eq_df = eq_df.set_index("ts").sort_index()
        if isinstance(self.plot_resample, str) and self.plot_resample.strip():
            eq_df = eq_df.resample(self.plot_resample.strip()).last().dropna()
        max_eq_points = max_points if max_points > 0 else 0
        if max_eq_points > 0:
            eq_step = max(1, len(eq_df) // max_eq_points)
            eq_df = eq_df.iloc[::eq_step]

        eq_t = eq_df.index.to_pydatetime().tolist()
        eq_v = eq_df["equity"].astype(float).to_numpy()

        real_trades = [t for t in self.trades if t.get("mode") != "INJECTION"]
        levs = [float(t.get("leverage", 0.0)) for t in real_trades if t.get("leverage") is not None]
        levs = [v for v in levs if v > 0]
        lev_avg = float(np.mean(levs)) if levs else 0.0
        lev_max = float(np.max(levs)) if levs else 0.0
        inj_total = float(getattr(self, "total_injected", 0.0) or 0.0)
        inj_count = int(getattr(self, "bankruptcy_count", 0) or 0)

        fig_eq, ax_eq = plt.subplots(1, 1, figsize=tuple(self.plot_figsize))
        ax_eq.step(eq_t, eq_v, where='post', color='#1f77b4', lw=1.6)
        if bool(self.plot_show_trades):
            injections = [t for t in self.trades if t['mode'] == 'INJECTION']
            if injections:
                inj_t = [datetime.fromtimestamp(t['exit_time']/1000) for t in injections]
                inj_v = [t['balance'] for t in injections]
                ax_eq.scatter(inj_t, inj_v, c='purple', marker='*', s=80, label='注资', zorder=5)
                ax_eq.legend()
        title = f"权益曲线 (杠杆均值={lev_avg:.2f}x, 最大={lev_max:.2f}x, 注资={inj_count}次/${inj_total:.0f})"
        ax_eq.set_title(title)
        ax_eq.grid(True)
        ax_eq.xaxis.set_major_locator(locator)
        ax_eq.xaxis.set_major_formatter(formatter)
        plt.xticks(rotation=30)
        fig_eq.tight_layout()
        plt.savefig(os.path.join(out_dir, "02_equity_curve.png"), dpi=int(self.plot_dpi), bbox_inches="tight")
        plt.close(fig_eq)

        # 输出 03_drawdown.png：回撤曲线
        eq_arr = np.array(eq_v, dtype=float)
        peak = np.maximum.accumulate(eq_arr) if len(eq_arr) else eq_arr
        dd = (eq_arr / (peak + 1e-12)) - 1.0 if len(eq_arr) else eq_arr
        fig_dd, ax_dd = plt.subplots(1, 1, figsize=tuple(self.plot_figsize))
        ax_dd.plot(eq_t, dd * 100.0, color="#d62728", lw=1.2)
        ax_dd.fill_between(eq_t, dd * 100.0, 0.0, color="#d62728", alpha=0.15, linewidth=0)
        ax_dd.set_title("Drawdown (%)")
        ax_dd.grid(True)
        ax_dd.xaxis.set_major_locator(locator)
        ax_dd.xaxis.set_major_formatter(formatter)
        plt.xticks(rotation=30)
        fig_dd.tight_layout()
        plt.savefig(os.path.join(out_dir, "03_drawdown.png"), dpi=int(self.plot_dpi), bbox_inches="tight")
        plt.close(fig_dd)

        print(f"📈 图片与CSV已输出到: {out_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default=Config.SYMBOL)
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--limit-5m", type=int, default=KLINE_LIMIT_5M)
    parser.add_argument("--limit-15m", type=int, default=KLINE_LIMIT_15M)
    parser.add_argument("--save", type=str, default="")
    parser.add_argument("--since-ms", type=int, default=None)
    parser.add_argument("--end-ms", type=int, default=None)
    parser.add_argument("--since", type=str, default="")
    parser.add_argument("--end", type=str, default="")
    parser.add_argument("--lookback-days", type=float, default=0.0)
    parser.add_argument("--warmup-steps", type=int, default=100)
    parser.add_argument("--plot-max-points", type=int, default=10000)
    parser.add_argument("--plot-dpi", type=int, default=160)
    parser.add_argument("--plot-mtm-equity", action="store_true")
    parser.add_argument("--plot-resample", type=str, default="")
    parser.add_argument("--plot-no-trades", action="store_true")
    parser.add_argument("--plot-no-drawdown", action="store_true")
    parser.add_argument("--plot-figsize", type=str, default="14,9")
    parser.add_argument("--inject-amount", type=float, default=1000.0)
    parser.add_argument("--title-lev", type=float, default=2.0)
    args = parser.parse_args()

    since_ms = args.since_ms
    end_ms = args.end_ms
    if args.since:
        since_ms = int(pd.to_datetime(args.since).timestamp() * 1000)
    if args.end:
        end_ms = int(pd.to_datetime(args.end).timestamp() * 1000)
    if args.lookback_days and args.lookback_days > 0:
        end_ms = end_ms or int(time.time() * 1000)
        since_ms = int(end_ms - float(args.lookback_days) * 86400 * 1000)
    
    bt = StrategyBacktesterUnified(
        symbol=args.symbol, balance=args.balance, 
        since_ms=since_ms, end_ms=end_ms, 
        warmup_steps=args.warmup_steps
    )
    bt.slippage = args.slippage
    if args.save: bt.save_path = args.save
    bt.plot_max_points = args.plot_max_points
    bt.plot_dpi = args.plot_dpi
    bt.plot_mtm_equity = bool(args.plot_mtm_equity)
    bt.plot_resample = args.plot_resample or ""
    bt.plot_show_trades = not bool(args.plot_no_trades)
    bt.plot_show_drawdown = not bool(args.plot_no_drawdown)
    bt.inject_amount = float(args.inject_amount)
    bt.title_leverage = float(args.title_lev)
    try:
        w_str, h_str = (args.plot_figsize or "14,9").split(",", 1)
        bt.plot_figsize = (float(w_str.strip()), float(h_str.strip()))
    except Exception:
        bt.plot_figsize = (14, 9)
    
    bt.run(limit_1m=args.limit_5m, limit_15m=args.limit_15m)
