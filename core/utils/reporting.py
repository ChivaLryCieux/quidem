
import redis
import json
import time
import ccxt
import pandas as pd
import base64
import io
import os
import numpy as np
import logging
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import matplotlib.dates as mdates

from core.config.settings import Config
from core.analysis.indicators import (
    BollingerBands, SuperTrend, MACDCalculator, KDJCalculator,
    ADXCalculator, VWAPCalculator, MathUtils
)

logger = logging.getLogger(__name__)

class ReportService:
    def __init__(self):
        try:
            self.redis_client = redis.Redis(**Config.redis_kwargs(timeout=3))
            self.redis_client.ping()
        except Exception as e:
            logger.error(f"ReportService Redis Connection Failed: {e}")
            self.redis_client = None

        self.archive_dir = os.path.expanduser(Config.REPORT_ARCHIVE_DIR)
        self._ensure_dir(self.archive_dir)

        self._daily_exchange = None
        self._bb = BollingerBands(period=20, std_mult=2.0)
        self._supertrend = SuperTrend(atr_period=10, multiplier=3.0)
        self._macd = MACDCalculator(fast=12, slow=26, signal=9)
        self._fast_macd = MACDCalculator(fast=8, slow=17, signal=9)
        self._kdj = KDJCalculator(k_period=9, d_period=3, j_smooth=3)
        self._adx = ADXCalculator(period=14)
        self._vwap = VWAPCalculator(period=20)

    def _init_daily_exchange(self):
        if self._daily_exchange is not None:
            return self._daily_exchange
        conf = {
            'enableRateLimit': True,
            'timeout': Config.HTTP_TIMEOUT_MS,
            'options': {'defaultType': 'future'}
        }
        proxies = Config.exchange_proxies()
        if proxies:
            conf['proxies'] = proxies
        self._daily_exchange = ccxt.binance(conf)
        return self._daily_exchange

    def _ensure_dir(self, path):
        if not os.path.exists(path): os.makedirs(path)
        return path

    def get_daily_dir(self):
        return self._ensure_dir(os.path.join(self.archive_dir, datetime.now().strftime('%Y-%m-%d')))

    def generate_equity_curve_b64(self, trades):
        """Generate equity curve image as base64 string"""
        if not trades: return None
        try:
            df = pd.DataFrame(trades)
            df['time'] = pd.to_datetime(df['exit_time'], unit='ms')
            df = df.sort_values('time')
            
            first = df.iloc[0]
            start_bal = first['balance'] - first['pnl']
            
            times = [df['time'].iloc[0] - pd.Timedelta(minutes=15)] + df['time'].tolist()
            balances = [start_bal] + df['balance'].tolist()

            fig = Figure(figsize=(8, 3.5), dpi=100)
            ax = fig.add_subplot(111)
            ax.plot(times, balances, color='#007bff', linewidth=2, drawstyle='steps-post')
            ax.fill_between(times, balances, min(balances)*0.995, step='post', color='#007bff', alpha=0.1)
            ax.set_title("Equity Curve (Session)", fontsize=10)
            ax.grid(True, linestyle='--', alpha=0.5)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            fig.autofmt_xdate()

            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
        except Exception as e:
            logger.error(f"Equity Curve Error: {e}")
            return None

    def generate_sparkline_b64(self, snapshots):
        """Generate sparkline image as base64 string"""
        if not snapshots or len(snapshots) < 2: return None
        try:
            df = pd.DataFrame(snapshots)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            
            fig = Figure(figsize=(2.5, 0.6), dpi=80)
            ax = fig.add_subplot(111)
            ax.axhline(0, color='#999', linestyle='--', alpha=0.5)
            ax.plot(df['time'], df['pnl'], color='#333', linewidth=1)
            
            pnl = df['pnl'].values
            ax.fill_between(df['time'], pnl, 0, where=(pnl>=0), interpolate=True, color='#28a745', alpha=0.3)
            ax.fill_between(df['time'], pnl, 0, where=(pnl<0), interpolate=True, color='#dc3545', alpha=0.3)
            
            final = pnl[-1]
            c = '#28a745' if final >= 0 else '#dc3545'
            ax.scatter(df['time'].iloc[-1], final, s=15, c=c, zorder=5)
            ax.axis('off')
            
            buf = io.BytesIO()
            fig.savefig(buf, format='png', transparent=True)
            buf.seek(0)
            return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
        except Exception:
            return None

    def create_csv_export(self, trades):
        if not trades: return None, None
        try:
            df = pd.DataFrame(trades)
            for t in ['entry_time', 'exit_time']:
                if t in df.columns: df[t+'_dt'] = pd.to_datetime(df[t], unit='ms')
            
            fname = f"trades_{int(time.time())}.csv"
            fpath = os.path.join(self.get_daily_dir(), fname)
            df.to_csv(fpath, index=False, encoding='utf-8-sig')
            return fpath, fname
        except Exception as e:
            logger.error(f"CSV Error: {e}")
            return None, None

    def _format_change_badge(self, change_pct):
        """生成24h涨跌幅的HTML徽章"""
        if change_pct >= 0:
            bg = "#e8f5e9"
            border = "#66bb6a"
            color = "#2e7d32"
            icon = "📈"
            sign = "+"
        else:
            bg = "#ffebee"
            border = "#ef5350"
            color = "#c62828"
            icon = "📉"
            sign = ""
        return f"""
        <div style="background:{bg};padding:15px;border-radius:8px;text-align:center;margin-bottom:20px;border:1px solid {border};">
            <div style="font-size:14px;color:{color};font-weight:bold;">{icon} 24h 涨跌: {sign}{change_pct:.2f}%</div>
        </div>
        """

    def _format_daily_indicator_section(self, daily_indicators):
        if not daily_indicators:
            return ""

        rows = ""
        for key, value in daily_indicators.items():
            label = key.replace('_', ' ').upper()
            if isinstance(value, (int, float)):
                val = f"{value:.4f}"
            else:
                val = str(value)
            rows += f"<tr><td style='padding:6px;border-bottom:1px solid #eee'>{label}</td><td style='padding:6px;border-bottom:1px solid #eee'><b>{val}</b></td></tr>"

        return f"""
        <div style="margin:18px 0;">
            <h3 style="margin-bottom:8px;">📅 日线技术指标快照</h3>
            <table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #eee;border-radius:6px;overflow:hidden;">
                <thead><tr><th style="text-align:left;padding:8px;background:#f6f7f9;">指标</th><th style="text-align:left;padding:8px;background:#f6f7f9;">当前值</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
        """

    def fetch_daily_indicators(self):
        try:
            ex = self._init_daily_exchange()
            ohlcv = ex.fetch_ohlcv(Config.SYMBOL, '1d', limit=150)
            if not ohlcv or len(ohlcv) < 35:
                return None

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['taker_buy'] = df['volume'] * 0.5
            curr_price = float(df.iloc[-1]['close'])

            bb = self._bb.calculate(df)
            st = self._supertrend.calculate(df)
            macd = self._macd.calculate(df)
            fast_macd = self._fast_macd.calculate(df)
            kdj = self._kdj.calculate(df)
            adx = self._adx.calculate(df)
            vwap = self._vwap.calculate(df)
            atr = MathUtils.calc_atr(df).iloc[-1]
            rsi = MathUtils.calc_rsi(df['close']).iloc[-1]

            return {
                'price': curr_price,
                'rsi': float(rsi),
                'atr': float(atr),
                'bb_distance': float(bb['distance']),
                'supertrend_direction': int(st['direction']),
                'macd_histogram': float(macd['histogram']),
                'fast_macd_histogram': float(fast_macd['histogram']),
                'kdj_k': float(kdj['k']),
                'kdj_d': float(kdj['d']),
                'kdj_j': float(kdj['j']),
                'adx': float(adx['adx']),
                'plus_di': float(adx['plus_di']),
                'minus_di': float(adx['minus_di']),
                'vwap_distance': float(vwap['distance']),
            }
        except Exception as e:
            logger.warning(f"Daily indicator snapshot unavailable: {e}")
            return None

    def generate_trade_report_html(self, trades, change_24h=0.0, daily_indicators=None):
        if not trades: return None
        
        # Stats
        df = pd.DataFrame(trades)
        total_pnl = df['pnl'].sum()
        total_fee = df.get('fee', 0).sum()
        curr_bal = df.iloc[-1]['balance']
        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] <= 0]
        win_rate = len(wins)/len(df)*100
        pf = (wins['pnl'].sum() / abs(losses['pnl'].sum())) if len(losses) > 0 else 0
        
        # Drawdown
        bals = df['balance'].values
        peak = np.maximum.accumulate(bals)
        dd = (peak - bals) / peak * 100
        max_dd = dd.max()

        # Graphs
        equity_img = self.generate_equity_curve_b64(trades)
        change_badge = self._format_change_badge(change_24h)
        daily_indicator_section = self._format_daily_indicator_section(daily_indicators)
        
        # HTML Components
        rows = ""
        for t in trades:
            spark = self.generate_sparkline_b64(t.get('snapshots', []))
            spark_html = f'<img src="{spark}" style="height:25px;">' if spark else '-'
            
            pnl_color = "green" if t['pnl'] >= 0 else "red"
            entry_dt = datetime.fromtimestamp(t['entry_time']/1000).strftime('%H:%M')
            
            rows += f"""
            <tr>
                <td>{entry_dt}</td>
                <td><b>{t['action']}</b> <span style="font-size:10px;color:#999">x{t.get('leverage','?')}</span></td>
                <td style="color:{pnl_color}"><b>${t['pnl']:.2f}</b></td>
                <td>{spark_html}</td>
                <td style="font-size:11px">{t.get('reason','')}</td>
            </tr>
            """

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; font-size: 13px; color: #333; }}
                .card {{ background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #ddd; }}
                .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }}
                .val {{ font-size: 18px; font-weight: bold; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th {{ text-align: left; background: #eee; padding: 5px; }}
                td {{ border-bottom: 1px solid #eee; padding: 5px; vertical-align: middle; }}
            </style>
        </head>
        <body>
            <h2>📊 Strategy Report</h2>
            <div class="grid">
                <div class="card"><div class="val">${curr_bal:.2f}</div><div>Equity</div></div>
                <div class="card"><div class="val" style="color:{'green' if total_pnl>=0 else 'red'}">${total_pnl:+.2f}</div><div>Net PnL</div></div>
                <div class="card"><div class="val">{pf:.2f}</div><div>Profit Factor</div></div>
                <div class="card"><div class="val">{win_rate:.0f}%</div><div>Win Rate</div></div>
            </div>
            {change_badge}
            {daily_indicator_section}
            {('<img src="'+equity_img+'" style="width:100%;border:1px solid #eee;border-radius:5px;margin-bottom:20px;">' if equity_img else '')}
            <table>
                <thead><tr><th>EntryTime</th><th>Action</th><th>PnL</th><th>Trend</th><th>Exit</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </body>
        </html>
        """
        return html

    def generate_heartbeat_html(self, status, daily_indicators=None):
        if not status: return "<html><body>No Data</body></html>"
        
        ts = datetime.fromtimestamp(status['timestamp']/1000).strftime('%Y-%m-%d %H:%M:%S')
        change_24h = status.get('change_24h', 0.0)
        change_badge = self._format_change_badge(change_24h)
        daily_indicator_section = self._format_daily_indicator_section(daily_indicators)
        
        return f"""
        <html>
        <body style="font-family: Arial; padding: 20px; color: #333;">
            <h2>😴 Silence Report (No Trades)</h2>
            <p style="color:#666">Last Heartbeat: {ts}</p>
            <div style="background:#f8f9fa; padding: 20px; border-radius: 8px; border:1px solid #ddd; text-align:center;">
                <div style="font-size:32px; font-weight:bold; color:#007bff">${status.get('balance',0):.2f}</div>
                <div style="color:#666">Current Equity</div>
            </div>
            {change_badge}
            {daily_indicator_section}
            <div style="margin-top:20px;">
                <b>Status:</b> {status.get('regime','Unknown')}<br>
                <b>Price:</b> ${status.get('price',0):.4f}<br>
            </div>
        </body>
        </html>
        """
