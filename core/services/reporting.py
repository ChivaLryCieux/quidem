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

# [优化] 使用非交互式后端，防止在无 GUI 环境下报错
import matplotlib

matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import matplotlib.dates as mdates

from core.config.settings import Config

logger = logging.getLogger(__name__)


class ReportService:
    def __init__(self):
        # [优化] 从 Config 读取 Redis 配置，保持统一
        # 容错：如果 Config 中没有定义，使用默认值
        host = getattr(Config, 'REDIS_HOST', 'localhost')
        port = getattr(Config, 'REDIS_PORT', 6379)
        db = getattr(Config, 'REDIS_DB', 0)

        try:
            self.redis_client = redis.Redis(host=host, port=port, db=db, socket_timeout=3)
            self.redis_client.ping()
        except Exception as e:
            logger.error(f"ReportService Redis 连接失败: {e}")
            self.redis_client = None

        self.archive_dir = os.path.expanduser("~/quant_archive")
        self.ensure_archive_dir()

    def ensure_archive_dir(self):
        """确保存档目录存在"""
        try:
            if not os.path.exists(self.archive_dir):
                os.makedirs(self.archive_dir)
        except Exception as e:
            logger.error(f"无法创建存档目录: {e}")

    def ensure_daily_dir(self):
        """获取或创建每日目录"""
        today_str = datetime.now().strftime('%Y-%m-%d')
        path = os.path.join(self.archive_dir, today_str)
        if not os.path.exists(path):
            os.makedirs(path)
        return path

    def generate_equity_curve(self, trades, save_dir=None):
        """
        生成权益曲线图
        [优化] 使用面向对象方式绘图，不依赖 plt 全局状态，线程安全
        """
        if not trades:
            return None

        try:
            df = pd.DataFrame(trades)
            # 确保按时间排序
            df['time'] = pd.to_datetime(df['exit_time'], unit='ms')
            df = df.sort_values('time')

            # 计算起始资金 (倒推)
            first_trade = df.iloc[0]
            start_balance = first_trade['balance'] - first_trade['pnl']

            # 构建绘图数据点
            # 在第一个交易前插入一个起始点
            times = [df['time'].iloc[0] - pd.Timedelta(minutes=15)] + df['time'].tolist()
            balances = [start_balance] + df['balance'].tolist()

            # 创建画布 (Figure)
            fig = Figure(figsize=(8, 3.5), dpi=100)
            canvas = FigureCanvas(fig)
            ax = fig.add_subplot(111)

            # 绘制样式
            ax.plot(times, balances, color='#007bff', linewidth=2, label='Equity', drawstyle='steps-post')
            ax.fill_between(times, balances, min(balances) * 0.995, step='post', color='#007bff', alpha=0.1)

            # 装饰
            ax.set_title("Equity Curve (Session)", fontsize=10, weight='bold', pad=10)
            ax.grid(True, which='both', linestyle='--', linewidth=0.5, alpha=0.5)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

            # 自动调整日期标签
            fig.autofmt_xdate(rotation=0, ha='center')

            # 转换为 Base64
            buffer = io.BytesIO()
            fig.savefig(buffer, format='png', bbox_inches='tight')
            buffer.seek(0)
            img_str = base64.b64encode(buffer.read()).decode('utf-8')

            return f"data:image/png;base64,{img_str}"

        except Exception as e:
            logger.error(f"生成权益曲线失败: {e}")
            return None

    def process_trades_to_csv(self, trades, save_dir):
        """将交易记录转换为CSV文件"""
        if not trades:
            return None, None

        try:
            df = pd.DataFrame(trades)

            # 时间戳转换
            if 'entry_time' in df.columns:
                df['entry_time_dt'] = pd.to_datetime(df['entry_time'], unit='ms')
            if 'exit_time' in df.columns:
                df['exit_time_dt'] = pd.to_datetime(df['exit_time'], unit='ms')

            # 重新排列列顺序 (如果存在)
            preferred_cols = ['time', 'entry_time_dt', 'exit_time_dt', 'action', 'symbol', 'entry_price', 'exit_price',
                              'amount', 'pnl', 'fee', 'balance', 'reason']
            cols = [c for c in preferred_cols if c in df.columns] + [c for c in df.columns if c not in preferred_cols]
            df = df[cols]

            filename = f"trades_export_{int(time.time())}.csv"
            filepath = os.path.join(save_dir, filename)

            df.to_csv(filepath, index=False, encoding='utf-8-sig')
            return filepath, filename

        except Exception as e:
            logger.error(f"CSV 生成失败: {e}")
            return None, None

    def generate_sparkline(self, snapshots, trade_id, save_dir=None):
        """生成微型走势图"""
        if not snapshots or len(snapshots) < 2:
            return None

        try:
            df = pd.DataFrame(snapshots)
            df['time'] = pd.to_datetime(df['time'], unit='s')

            # 创建画布
            fig = Figure(figsize=(2.5, 0.6), dpi=80)
            canvas = FigureCanvas(fig)
            ax = fig.add_subplot(111)

            # 绘制基准线
            ax.axhline(y=0, color='#999999', linestyle='--', linewidth=0.5, alpha=0.5)

            # 绘制走势
            pnl_values = df['pnl'].values
            ax.plot(df['time'], pnl_values, color='#333333', linewidth=1)

            # 填充颜色
            ax.fill_between(df['time'], pnl_values, 0, where=(pnl_values >= 0),
                            interpolate=True, color='#28a745', alpha=0.3)
            ax.fill_between(df['time'], pnl_values, 0, where=(pnl_values < 0),
                            interpolate=True, color='#dc3545', alpha=0.3)

            # 标记终点
            final_pnl = pnl_values[-1]
            end_color = '#28a745' if final_pnl >= 0 else '#dc3545'
            ax.scatter(df['time'].iloc[-1], final_pnl, s=15, c=end_color, zorder=5)

            # 移除坐标轴
            ax.axis('off')
            fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

            buffer = io.BytesIO()
            fig.savefig(buffer, format='png', transparent=True)
            buffer.seek(0)
            img_str = base64.b64encode(buffer.read()).decode('utf-8')

            return f"data:image/png;base64,{img_str}"

        except Exception as e:
            logger.error(f"Sparkline 生成失败: {e}")
            return None

    def generate_no_trade_html(self, status_data):
        """生成无交易时的HTML报告"""
        if not status_data:
            return "<html><body><h3>⚠️ 警告：无法获取机器人心跳数据</h3><p>Redis 中没有 bot_status_heartbeat 数据。</p></body></html>"

        try:
            # 解析数据
            ts_dt = datetime.fromtimestamp(status_data['timestamp'] / 1000)
            ts_str = ts_dt.strftime('%Y-%m-%d %H:%M:%S')
            balance = float(status_data.get('balance', 0))
            price = float(status_data.get('price', 0))
            regime = status_data.get('regime', 'Unknown')
            ai_conf = float(status_data.get('ai_conf', 0))
            hf_signal = float(status_data.get('hf_signal', 0))

            # 内联 CSS 确保邮件兼容性
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333; line-height: 1.5; }}
                    .card {{ background: #f8f9fa; border-radius: 8px; padding: 24px; border: 1px solid #e9ecef; text-align: center; margin-bottom: 24px; }}
                    .huge-text {{ font-size: 32px; font-weight: 700; color: #0d6efd; margin-bottom: 8px; }}
                    .label {{ font-size: 13px; color: #6c757d; text-transform: uppercase; letter-spacing: 0.5px; }}
                    .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 50px; font-weight: 600; font-size: 13px; }}
                    .status-grey {{ background: #e9ecef; color: #495057; }}
                    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
                    .item {{ background: #fff; padding: 16px; border: 1px solid #dee2e6; border-radius: 6px; }}
                    .value {{ font-size: 18px; font-weight: 600; margin-top: 4px; color: #212529; }}
                    .footer {{ text-align: center; color: #adb5bd; font-size: 12px; margin-top: 40px; }}
                </style>
            </head>
            <body>
                <h2 style="margin: 0 0 8px 0;">😴 策略静默报告</h2>
                <div style="color: #6c757d; font-size: 13px; margin-bottom: 24px;">
                    生成时间: {datetime.now().strftime('%H:%M')} &bull; 最后心跳: {ts_str}
                </div>

                <div class="card">
                    <div class="huge-text">${balance:,.2f}</div>
                    <div class="label">当前账户权益 (Equity)</div>
                </div>

                <div style="font-weight: 600; margin-bottom: 12px;">市场状态监控</div>
                <div class="grid">
                    <div class="item">
                        <div class="label">当前市场状态</div>
                        <div class="value" style="font-size: 16px;">
                            <span class="status-badge status-grey">{regime}</span>
                        </div>
                    </div>
                    <div class="item">
                        <div class="label">当前价格</div>
                        <div class="value">${price:,.4f}</div>
                    </div>
                    <div class="item">
                        <div class="label">AI 信心 (需>0.4)</div>
                        <div class="value">{ai_conf:.2f}</div>
                    </div>
                    <div class="item">
                        <div class="label">H-infinity 信号</div>
                        <div class="value">{hf_signal:.4f}</div>
                    </div>
                </div>

                <div class="footer">
                    机器人在过去的时间段内持续监控，但未发现高胜率机会。<br>
                    "学会空仓是交易员成熟的第一步。"
                </div>
            </body>
            </html>
            """
            return html
        except Exception as e:
            logger.error(f"生成无交易报告失败: {e}")
            return "<html><body>Error generating report</body></html>"