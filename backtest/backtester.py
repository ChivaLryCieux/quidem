import os
import sys
import ccxt
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from datetime import datetime
import argparse

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

root = os.path.dirname(os.path.dirname(__file__))
sys.path.append(root)
sys.path.append(os.path.join(root, "core"))

from core.config import Config
from core.strategy import StrategyBrain
from core.risk_manager import RiskManager
from core.math_tools import MathUtils

def _make_exchange(use_proxy=True):
    conf = {'enableRateLimit': True, 'options': {'defaultType': 'future'}}
    if use_proxy:
        conf['proxies'] = {'http': Config.PROXY_URL, 'https': Config.PROXY_URL}
    try:
        return ccxt.binance(conf)
    except Exception:
        if use_proxy:
            return _make_exchange(False)
        raise

def _fetch_ohlcv(exchange, symbol, timeframe, limit, since=None):
    try:
        return exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    except Exception:
        ex2 = _make_exchange(False)
        return ex2.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

class StrategyBacktesterUnified:
    def __init__(self, symbol=None, balance=100.0, since_ms=None, end_ms=None, timeformat="%H:%M", warmup_steps=30):
        setattr(Config, "BACKTEST_MODE", True)
        self.symbol = symbol or Config.SYMBOL
        self.balance = balance
        self.initial_balance = balance
        self.brain = StrategyBrain()
        self.risk = RiskManager()
        self.position = {'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 'entry_time': 0, 'last_funding_index': 0}
        self.trades = []
        self.data_1m_cache = []
        self.slippage = getattr(Config, "SLIPPAGE_BPS", 0.0002)
        self.since_ms = since_ms
        self.end_ms = end_ms
        self.timeformat = timeformat
        self.save_path = None
        self.snapshots = []
        self.last_snapshot_time = 0.0
        self.profit_flip_count = 0
        self.was_in_profit = False
        self.warmup_steps = warmup_steps

    def _apply_entry_slippage(self, sig, price):
        return price * (1 + self.slippage) if sig == 1 else price * (1 - self.slippage)

    def _apply_exit_slippage(self, side, price):
        return price * (1 - self.slippage) if side == "sell" else price * (1 + self.slippage)

    def _attempt_entry(self, analysis, price, current_time_ms, funding_rate=0.0):
        sig, lev = self.brain.get_entry_signal(analysis, price)
        if sig == 0:
            return
        risky, _ = self.risk.check_funding_rate_risk(sig, funding_rate)
        if risky:
            return
        amt = (self.balance * 0.98) / ((1 / lev) + Config.TAKER_FEE_RATE) / price
        if amt <= 0:
            return
        eprice = self._apply_entry_slippage(sig, price)
        atr_15m = getattr(self.brain.rf_classifier, "atr_15m_last", 0.0)
        tp_dist = max(atr_15m * 2, eprice * Config.MIN_TP_DISTANCE)
        sl_dist = eprice * (1 / lev) * 0.8
        self.position = {
            'size': amt if sig == 1 else -amt,
            'entry_price': eprice,
            'entry_time': int(current_time_ms),
            'sl': eprice - sl_dist if sig == 1 else eprice + sl_dist,
            'tp': eprice + tp_dist if sig == 1 else eprice - tp_dist,
            'last_funding_index': int(current_time_ms // (getattr(Config, "FUNDING_EVENT_INTERVAL_HOURS", 8) * 3600 * 1000))
        }
        self.snapshots = []
        self.last_snapshot_time = 0.0
        self.profit_flip_count = 0
        self.was_in_profit = False

    def _manage_position(self, price, analysis, current_time_ms, funding_rate=0.0):
        pos = self.position
        if pos['size'] == 0:
            return
        rate = getattr(Config, "BACKTEST_FUNDING_RATE_PCT", 0.0)
        if rate != 0.0:
            idx_now = int(current_time_ms // (getattr(Config, "FUNDING_EVENT_INTERVAL_HOURS", 8) * 3600 * 1000))
            last_idx = pos.get('last_funding_index', idx_now)
            if idx_now > last_idx:
                events = idx_now - last_idx
                pos_val = abs(pos['size']) * price
                fee = pos_val * rate * events
                self.balance += (-fee if pos['size'] > 0 else fee)
                self.position['last_funding_index'] = idx_now
        raw_pnl_pct = (price - pos['entry_price']) / pos['entry_price'] * (1 if pos['size'] > 0 else -1)
        is_prof = raw_pnl_pct > Config.FEE_BUFFER_PCT
        if not self.was_in_profit and is_prof:
            self.profit_flip_count += 1
        self.was_in_profit = is_prof
        atr_1m = analysis.get('atr', 0.0) if analysis else 0.0
        now = current_time_ms / 1000.0
        if now - self.last_snapshot_time >= 15:
            pnl = (price - pos['entry_price']) * pos['size']
            self.snapshots.append({'time': now, 'price': price, 'pnl': pnl, 'regime': self.brain.state})
            self.last_snapshot_time = now
        should_exit, reason = self.risk.check_exit_conditions(pos, price, current_time_ms, self.profit_flip_count, atr_1m, self.balance)
        if should_exit:
            self._execute_exit(reason, price, current_time_ms, funding_rate)

    def _execute_exit(self, reason, price, current_time_ms, funding_rate=0.0):
        pos_size = self.position['size']
        if pos_size == 0:
            return
        entry = self.position['entry_price']
        raw_pnl = (price - entry) * pos_size
        fee = abs(pos_size) * (entry + price) * Config.TAKER_FEE_RATE
        net_pnl = raw_pnl - fee
        self.balance += net_pnl
        margin_used = abs(pos_size) * entry / Config.MAX_LEVERAGE
        _ = self.risk.activate_circuit_breaker(net_pnl, margin_used)
        self.trades.append({
            'entry_time': self.position['entry_time'],
            'exit_time': int(current_time_ms),
            'mode': 'BACKTEST',
            'action': '做多' if pos_size > 0 else '做空',
            'entry_price': entry,
            'exit_price': price,
            'amount': abs(pos_size),
            'leverage': Config.MAX_LEVERAGE,
            'pnl': net_pnl,
            'fee': fee,
            'balance': self.balance,
            'regime': self.brain.state,
            'reason': reason,
            'snapshots': self.snapshots
        })
        self.snapshots = []
        self.last_snapshot_time = 0.0
        self.position = {'size': 0.0, 'entry_price': 0.0, 'sl': 0.0, 'tp': 0.0, 'entry_time': 0, 'last_funding_index': 0}

    def _intrabar_exit(self, c1, current_time_ms):
        if self.position['size'] == 0:
            return False
        h = float(c1[2])
        l = float(c1[3])
        pos = self.position
        if pos['size'] > 0:
            if l <= pos['sl']:
                price = self._apply_exit_slippage("sell", pos['sl'])
                self._execute_exit("🛑 SL (Intra)", price, current_time_ms, 0.0)
                return True
            if h >= pos['tp']:
                price = self._apply_exit_slippage("sell", pos['tp'])
                self._execute_exit("💰 TP (Intra)", price, current_time_ms, 0.0)
                return True
        else:
            if h >= pos['sl']:
                price = self._apply_exit_slippage("buy", pos['sl'])
                self._execute_exit("🛑 SL (Intra)", price, current_time_ms, 0.0)
                return True
            if l <= pos['tp']:
                price = self._apply_exit_slippage("buy", pos['tp'])
                self._execute_exit("💰 TP (Intra)", price, current_time_ms, 0.0)
                return True
        return False

    def run(self, limit_1m=500, limit_15m=150):
        print(f"开始回测: {self.symbol} 滑点: {self.slippage*10000:.1f}bps")
        ex = _make_exchange(True)
        data_1m = _fetch_ohlcv(ex, self.symbol, '1m', limit_1m, since=self.since_ms)
        data_15m = _fetch_ohlcv(ex, self.symbol, '15m', limit_15m, since=self.since_ms)
        if self.end_ms:
            data_1m = [c for c in data_1m if c[0] <= self.end_ms]
            data_15m = [c for c in data_15m if c[0] <= self.end_ms]
        self.data_1m_cache = data_1m
        idx_15 = 0
        processed_count = 0
        for c1 in data_1m:
            current_time_ms = int(c1[0])
            while idx_15 < len(data_15m) and data_15m[idx_15][0] <= c1[0]:
                c15 = data_15m[idx_15]
                self.brain.ingest_candle(c15, '15m')
                res15 = self.brain.analyze()
                if res15:
                    atr_val = getattr(self.brain.rf_classifier, "atr_15m_last", 0.0)
                    diff = float(c15[4]) - float(c15[1])
                    th = atr_val * getattr(Config, "LABEL_ATR_MULT", 0.5) if atr_val > 0 else float(Config.MIN_TP_DISTANCE)
                    label = 1 if diff > th else (-1 if diff < -th else 0)
                    self.brain.train_ai(res15['features'], label)
                idx_15 += 1
            self.brain.ingest_candle(c1, '1m')
            analysis = self.brain.analyze()
            if not analysis:
                continue
            processed_count += 1
            if processed_count < self.warmup_steps:
                continue
            if self._intrabar_exit(c1, current_time_ms):
                continue
            price = float(c1[4])
            if self.position['size'] != 0:
                self._manage_position(price, analysis, current_time_ms, 0.0)
            elif not self.risk.is_in_cooldown():
                self._attempt_entry(analysis, price, current_time_ms, 0.0)
        if self.position['size'] != 0 and len(data_1m) > 0:
            self._execute_exit("结束平仓", float(data_1m[-1][4]), int(data_1m[-1][0]), 0.0)
        self._report()

    def _report(self):
        if len(self.trades) == 0:
            print("回测期内无交易产生")
            return
        wins = [t for t in self.trades if t['pnl'] > 0]
        losses = [t for t in self.trades if t['pnl'] <= 0]
        total_pnl = sum(t['pnl'] for t in self.trades)
        gross_profit = sum(t['pnl'] for t in wins)
        gross_loss = abs(sum(t['pnl'] for t in losses))
        pf = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
        win_rate = (len(wins) / len(self.trades) * 100.0) if len(self.trades) > 0 else 0.0
        balances = [self.initial_balance] + [t['balance'] for t in self.trades]
        peak = np.maximum.accumulate(np.array(balances))
        dd = ((peak - balances) / peak).max() if len(balances) > 0 else 0.0
        mdd = float(dd) * 100.0
        rets_series = np.diff(balances) / np.array(balances[:-1]) if len(balances) > 1 else np.array([])
        sharpe_series = (float(np.mean(rets_series)) / float(np.std(rets_series))) * np.sqrt(365*24*60) if len(rets_series) > 1 and np.std(rets_series) > 0 else 0.0
        rets = []
        holds = []
        seq_loss = 0
        max_seq_loss = 0
        for t in self.trades:
            margin = (t['amount'] * t['entry_price']) / Config.MAX_LEVERAGE
            r = t['pnl'] / (margin + 1e-9)
            rets.append(r)
            ht = (t['exit_time'] - t['entry_time']) / 60000.0
            holds.append(ht)
            if t['pnl'] <= 0:
                seq_loss += 1
                if seq_loss > max_seq_loss:
                    max_seq_loss = seq_loss
            else:
                seq_loss = 0
        mean_ret = float(np.mean(rets)) if len(rets) > 0 else 0.0
        std_ret = float(np.std(rets)) if len(rets) > 0 else 0.0
        sharpe = (mean_ret / std_ret) if std_ret > 0 else 0.0
        down_rets = [r for r in rets if r < 0]
        down_std = float(np.std(down_rets)) if len(down_rets) > 0 else 0.0
        sortino = (mean_ret / down_std) if down_std > 0 else 0.0
        avg_hold = float(np.mean(holds)) if len(holds) > 0 else 0.0
        print(f"交易总数: {len(self.trades)} 胜率: {win_rate:.1f}% 初始资金: {self.initial_balance:.2f} 最终权益: {self.balance:.2f}")
        print(f"累计盈亏: {total_pnl:+.2f} 最大回撤: {mdd:.2f}% PF: {pf:.2f} 夏普(分钟): {sharpe_series:.2f} Sharpe: {sharpe:.2f} Sortino: {sortino:.2f} 平均持仓(分): {avg_hold:.2f} 最大连亏: {max_seq_loss}")
        self._plot(balances)

    def _plot(self, balances):
        ts = [datetime.fromtimestamp(c[0] / 1000.0) for c in self.data_1m_cache]
        px = [float(c[4]) for c in self.data_1m_cache]
        fig = plt.figure(figsize=(12, 6))
        ax1 = plt.subplot(2, 1, 1)
        ax1.plot(ts, px, color="gray", linewidth=1)
        for t in self.trades:
            et = datetime.fromtimestamp(t['entry_time'] / 1000.0)
            xt = datetime.fromtimestamp(t['exit_time'] / 1000.0)
            epx = t['entry_price']
            xpx = t['exit_price']
            if t['action'] == '做多':
                ax1.scatter([et], [epx], c="green", marker="^", s=30)
                ax1.scatter([xt], [xpx], c="red", marker="x", s=30)
            else:
                ax1.scatter([et], [epx], c="orange", marker="v", s=30)
                ax1.scatter([xt], [xpx], c="red", marker="x", s=30)
            ax1.axvline(et, color="green", alpha=0.15, linewidth=0.8)
            ax1.axvline(xt, color="red", alpha=0.15, linewidth=0.8)
        ax1.set_title("价格与交易标记")
        ax1.xaxis.set_major_formatter(mdates.DateFormatter(self.timeformat))
        if len(ts) > 0:
            ax1.set_xlim(ts[0], ts[-1])
        legend_handles = [
            Line2D([0], [0], color='gray', label='价格'),
            Line2D([0], [0], marker='^', color='green', linestyle='None', label='做多开仓', markersize=8),
            Line2D([0], [0], marker='v', color='orange', linestyle='None', label='做空开仓', markersize=8),
            Line2D([0], [0], marker='x', color='red', linestyle='None', label='平仓', markersize=8),
            Line2D([0], [0], color='green', linestyle='-', alpha=0.15, label='入场时间'),
            Line2D([0], [0], color='red', linestyle='-', alpha=0.15, label='出场时间'),
        ]
        ax1.legend(handles=legend_handles, loc='upper left')
        ax2 = plt.subplot(2, 1, 2)
        eq_times = [datetime.fromtimestamp(t['exit_time'] / 1000.0) for t in self.trades]
        eq_vals = [t['balance'] for t in self.trades]
        eq_times_line = ([ts[0]] + eq_times) if len(ts) > 0 else eq_times
        eq_vals_line = ([self.initial_balance] + eq_vals) if len(ts) > 0 else eq_vals
        ax2.plot(eq_times_line, eq_vals_line, color="#007bff")
        if len(eq_times) > 0:
            ax2.scatter(eq_times, eq_vals, color="#007bff", s=20)
        ax2.set_title("权益曲线")
        ax2.xaxis.set_major_formatter(mdates.DateFormatter(self.timeformat))
        if len(ts) > 0:
            ax2.set_xlim(ts[0], ts[-1])
        legend_handles2 = [
            Line2D([0], [0], color='#007bff', label='权益曲线'),
            Line2D([0], [0], marker='o', color='#007bff', linestyle='None', label='平仓点', markersize=6),
        ]
        ax2.legend(handles=legend_handles2, loc='upper left')
        plt.tight_layout()
        if self.save_path:
            plt.savefig(self.save_path, dpi=120, bbox_inches='tight')
        else:
            plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default=Config.SYMBOL)
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--slippage", type=float, default=getattr(Config, "SLIPPAGE_BPS", 0.0002))
    parser.add_argument("--limit-1m", type=int, default=500)
    parser.add_argument("--limit-15m", type=int, default=150)
    parser.add_argument("--save", type=str, default="")
    parser.add_argument("--since-ms", type=int, default=0)
    parser.add_argument("--end-ms", type=int, default=0)
    parser.add_argument("--timeformat", type=str, default="%H:%M")
    parser.add_argument("--warmup-steps", type=int, default=30)
    args = parser.parse_args()
    bt = StrategyBacktesterUnified(symbol=args.symbol, balance=args.balance, since_ms=(args.since_ms or None), end_ms=(args.end_ms or None), timeformat=args.timeformat, warmup_steps=args.warmup_steps)
    bt.slippage = args.slippage
    if args.save:
        bt.save_path = args.save
    bt.run(limit_1m=args.limit_1m, limit_15m=args.limit_15m)

