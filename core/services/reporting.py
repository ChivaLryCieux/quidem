import redis
import json
import time
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import base64
import io
import os
import numpy as np
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class ReportService:
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, db=redis_db)
        self.archive_dir = os.path.expanduser("~/quant_archive")
        self.ensure_archive_dir()
        
        # 设置 matplotlib 后端
        plt.switch_backend('Agg')
        
    def ensure_archive_dir(self):
        """确保存档目录存在"""
        if not os.path.exists(self.archive_dir):
            os.makedirs(self.archive_dir)
            
    def ensure_daily_dir(self):
        """获取或创建每日目录"""
        today_str = datetime.now().strftime('%Y-%m-%d')
        path = os.path.join(self.archive_dir, today_str)
        if not os.path.exists(path):
            os.makedirs(path)
        return path
        
    def generate_equity_curve(self, trades, save_dir):
        """生成权益曲线图"""
        if not trades:
            return None
            
        df = pd.DataFrame(trades)
        df['time'] = pd.to_datetime(df['exit_time'], unit='ms')
        df = df.sort_values('time')
        
        first_trade = df.iloc[0]
        start_balance = first_trade['balance'] - first_trade['pnl']
        start_time = first_trade['time'] - pd.Timedelta(minutes=5)
        
        times = [start_time] + df['time'].tolist()
        balances = [start_balance] + df['balance'].tolist()
        
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.plot(times, balances, color='#007bff', linewidth=2, label='Equity', drawstyle='steps-post')
        ax.fill_between(times, balances, min(balances) * 0.99, step='post', color='#007bff', alpha=0.1)
        
        ax.set_title("Account Equity Curve (Session)", fontsize=10, pad=10)
        ax.grid(True, which='both', linestyle='--', linewidth=0.5, alpha=0.5)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        
        plt.xticks(fontsize=8, rotation=0)
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', bbox_inches='tight', dpi=100)
        buffer.seek(0)
        img_str = base64.b64encode(buffer.read()).decode('utf-8')
        plt.close(fig)
        
        return f"data:image/png;base64,{img_str}"
        
    def process_trades_to_csv(self, trades, save_dir):
        """将交易记录转换为CSV文件"""
        if not trades:
            return None, None
            
        # 将列表转换为DataFrame
        df = pd.DataFrame(trades)
        
        # 简单的格式化处理：将时间戳转换为可读时间
        if 'entry_time' in df.columns:
            df['entry_time_dt'] = pd.to_datetime(df['entry_time'], unit='ms')
        if 'exit_time' in df.columns:
            df['exit_time_dt'] = pd.to_datetime(df['exit_time'], unit='ms')
            
        # 生成文件名
        filename = f"trades_export_{int(time.time())}.csv"
        filepath = os.path.join(save_dir, filename)
        
        # 保存文件
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        return filepath, filename
        
    def generate_sparkline(self, snapshots, trade_id, save_dir):
        """生成微型走势图"""
        if not snapshots or len(snapshots) < 2:
            return None
            
        df = pd.DataFrame(snapshots)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        fig, ax = plt.subplots(figsize=(2, 0.5))
        ax.axhline(y=0, color='#666666', linestyle='--', linewidth=0.5, alpha=0.8)
        ax.plot(df['time'], df['pnl'], color='#333333', linewidth=0.8, alpha=0.8)
        ax.fill_between(df['time'], df['pnl'], 0, where=(df['pnl'] >= 0), 
                       interpolate=True, color='#00a65a', alpha=0.3)
        ax.fill_between(df['time'], df['pnl'], 0, where=(df['pnl'] < 0), 
                       interpolate=True, color='#dd4b39', alpha=0.3)
        
        final_pnl = snapshots[-1]['pnl']
        end_color = '#00a65a' if final_pnl >= 0 else '#dd4b39'
        ax.scatter(df['time'].iloc[-1], final_pnl, s=10, c=end_color, zorder=5)
        
        ax.axis('off')
        plt.margins(0.05, 0.1)
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', bbox_inches='tight', pad_inches=0, 
                   transparent=True, dpi=100)
        buffer.seek(0)
        img_str = base64.b64encode(buffer.read()).decode('utf-8')
        plt.close(fig)
        
        return f"data:image/png;base64,{img_str}"
        
    def generate_no_trade_html(self, status_data):
        """生成无交易时的HTML报告"""
        if not status_data:
            return "<html><body><h1>⚠️ 警告：无法获取机器人心跳数据</h1><p>Redis 中没有 bot_status_heartbeat 数据，请检查 main.py 是否运行。</p></body></html>"
            
        # 解析数据
        ts = datetime.fromtimestamp(status_data['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
        balance = status_data['balance']
        price = status_data['price']
        regime = status_data['regime']
        ai_conf = status_data['ai_conf']
        
        # 简单的CSS
        css = """
            body { font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333; }
            .card { background: #f8f9fa; border-radius: 8px; padding: 20px; border: 1px solid #e9ecef; text-align: center; margin-bottom: 20px; }
            .huge-text { font-size: 24px; font-weight: bold; color: #007bff; }
            .label { font-size: 12px; color: #999; text-transform: uppercase; margin-top: 5px; }
            .status-badge { display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: bold; font-size: 12px; }
            .status-green { background: #d4edda; color: #155724; }
            .status-grey { background: #e2e3e5; color: #383d41; }
            .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; text-align: left; }
            .info-item { background: #fff; padding: 10px; border: 1px solid #eee; border-radius: 6px; }
        """
        
        html = f"""
        <html>
        <head><style>{css}</style></head>
        <body>
            <h2 style="margin-bottom: 5px;">😴 策略静默报告 (No Trades)</h2>
            <div style="color: #999; font-size: 12px; margin-bottom: 20px;">生成时间: {datetime.now().strftime('%H:%M')} | 最后心跳: {ts}</div>

            <div class="card">
                <div class="huge-text">${balance:.2f}</div>
                <div class="label">当前权益 (Equity) - 资金安全</div>
            </div>

            <div style="margin-bottom: 10px; font-weight: bold;">为什么没有交易？</div>
            <div class="info-grid">
                <div class="info-item">
                    <div class="label">当前市场状态</div>
                    <div style="font-size: 16px; margin-top: 5px;">
                        <span class="status-badge status-grey">{regime}</span>
                    </div>
                </div>
                <div class="info-item">
                    <div class="label">AI 观测信心</div>
                    <div style="font-size: 16px; margin-top: 5px;">
                        {ai_conf:.2f} <span style="color:#ccc; font-size:10px;">(需 >0.4 开仓)</span>
                    </div>
                </div>
                <div class="info-item">
                    <div class="label">当前价格</div>
                    <div>${price:.4f}</div>
                </div>
                <div class="info-item">
                    <div class="label">系统状态</div>
                    <div style="color: #28a745;">● 在线运行中</div>
                </div>
            </div>

            <p style="text-align: center; color: #ccc; font-size: 12px; margin-top: 30px;">
                机器人在过去的时间段内持续监控，但未发现高胜率机会。<br>
                空仓也是一种交易。
            </p>
        </body>
        </html>
        """
        
        return html