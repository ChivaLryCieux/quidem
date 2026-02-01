
import redis
import json
import time
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

logger = logging.getLogger(__name__)

class ReportService:
    def __init__(self):
        host = getattr(Config, 'REDIS_HOST', 'localhost')
        port = getattr(Config, 'REDIS_PORT', 6379)
        db = getattr(Config, 'REDIS_DB', 0)

        try:
            self.redis_client = redis.Redis(host=host, port=port, db=db, socket_timeout=3)
            self.redis_client.ping()
        except Exception as e:
            logger.error(f"ReportService Redis Connection Failed: {e}")
            self.redis_client = None

        self.archive_dir = os.path.expanduser("~/quant_archive")
        self._ensure_dir(self.archive_dir)

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
            # Simple Processing
            for t in ['entry_time', 'exit_time']:
                if t in df.columns: df[t+'_dt'] = pd.to_datetime(df[t], unit='ms')
            
            fname = f"trades_{int(time.time())}.csv"
            fpath = os.path.join(self.get_daily_dir(), fname)
            df.to_csv(fpath, index=False, encoding='utf-8-sig')
            return fpath, fname
        except Exception as e:
            logger.error(f"CSV Error: {e}")
            return None, None

    def generate_trade_report_html(self, trades):
        if not trades: return None
        
        # 状态映射字典
        state_names = {0: "大跌", 1: "弱跌", 2: "震荡", 3: "弱涨", 4: "大涨", 99: "初始"}
        
        # Stats
        df = pd.DataFrame(trades)
        total_pnl = df['pnl'].sum()
        total_fee = df.get('fee', 0).sum()
        curr_bal = df.iloc[-1]['balance']
        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] <= 0]
        win_rate = len(wins)/len(df)*100
        pf = (wins['pnl'].sum() / abs(losses['pnl'].sum())) if len(losses) > 0 else 0
        
        # 获取当前状态
        current_state_id = df.iloc[-1].get('cluster', 99)
        current_state_name = state_names.get(current_state_id, "未知")
        
        # Drawdown
        bals = df['balance'].values
        peak = np.maximum.accumulate(bals)
        dd = (peak - bals) / peak * 100
        max_dd = dd.max()

        # Graphs
        equity_img = self.generate_equity_curve_b64(trades)
        
        # HTML Components
        rows = ""
        for t in trades:
            spark = self.generate_sparkline_b64(t.get('snapshots', []))
            spark_html = f'<img src="{spark}" style="height:25px;">' if spark else '-'
            
            pnl_color = "green" if t['pnl'] >= 0 else "red"
            entry_dt = datetime.fromtimestamp(t['entry_time']/1000).strftime('%H:%M')
            
            # 获取交易时的状态
            trade_state_id = t.get('cluster', 99)
            trade_state_name = state_names.get(trade_state_id, "未知")
            
            rows += f"""
            <tr>
                <td>{entry_dt}</td>
                <td><b>{t['action']}</b> <span style="font-size:10px;color:#999">x{t.get('leverage','?')}</span></td>
                <td style="color:{pnl_color}"><b>${t['pnl']:.2f}</b></td>
                <td>{spark_html}</td>
                <td style="font-size:11px">S{trade_state_id}({trade_state_name})</td>
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
            <div style="background:#e3f2fd;padding:15px;border-radius:8px;text-align:center;margin-bottom:20px;border:1px solid #90caf9;">
                <div style="font-size:14px;color:#1976d2;font-weight:bold;">当前状态: S{current_state_id} ({current_state_name})</div>
            </div>
            {('<img src="'+equity_img+'" style="width:100%;border:1px solid #eee;border-radius:5px;margin-bottom:20px;">' if equity_img else '')}
            <table>
                <thead><tr><th>Time</th><th>Action</th><th>PnL</th><th>Trend</th><th>State</th><th>Exit</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </body>
        </html>
        """
        return html

    def generate_heartbeat_html(self, status):
        if not status: return "<html><body>No Data</body></html>"
        
        # 状态映射字典
        state_names = {0: "大跌", 1: "弱跌", 2: "震荡", 3: "弱涨", 4: "大涨", 99: "初始"}
        
        ts = datetime.fromtimestamp(status['timestamp']/1000).strftime('%Y-%m-%d %H:%M:%S')
        
        # 获取当前状态
        current_state_id = status.get('cluster', 99)
        current_state_name = state_names.get(current_state_id, "未知")
        
        return f"""
        <html>
        <body style="font-family: Arial; padding: 20px; color: #333;">
            <h2>😴 Silence Report (No Trades)</h2>
            <p style="color:#666">Last Heartbeat: {ts}</p>
            <div style="background:#f8f9fa; padding: 20px; border-radius: 8px; border:1px solid #ddd; text-align:center;">
                <div style="font-size:32px; font-weight:bold; color:#007bff">${status.get('balance',0):.2f}</div>
                <div style="color:#666">Current Equity</div>
            </div>
            <div style="background:#e3f2fd;padding:15px;border-radius:8px;text-align:center;margin-top:20px;border:1px solid #90caf9;">
                <div style="font-size:14px;color:#1976d2;font-weight:bold;">当前状态: S{current_state_id} ({current_state_name})</div>
            </div>
            <div style="margin-top:20px;">
                <b>Status:</b> {status.get('regime','Unknown')}<br>
                <b>Price:</b> ${status.get('price',0):.4f}<br>
                <b>AI Conf:</b> {status.get('ai_conf',0):.2f}<br>
            </div>
        </body>
        </html>
        """