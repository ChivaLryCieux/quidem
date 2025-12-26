import redis
import json
import time
import schedule
import resend
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import base64
import io
import os
import numpy as np
from datetime import datetime

# === 配置区域 ===
os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"

REDIS_HOST = 'localhost'
RESEND_API_KEY = "re_39zFrC4s_KhUDNyHg8ZFRR8LkXg8cN8Ry"  # 你的 Key
MAIL_FROM = "XRP量化交易机器人 <report@abyssalfish.top>"
MAIL_TO = ["3433551710@qq.com", "2874575651@qq.com","2129325064@qq.com"]

# 自动处理路径
ARCHIVE_DIR = os.path.expanduser("~/quant_archive")

# 设置 Matplotlib 后端
plt.switch_backend('Agg')

# 初始化
r = redis.Redis(host=REDIS_HOST, port=6379, db=0)
resend.api_key = RESEND_API_KEY


def ensure_daily_dir():
    today_str = datetime.now().strftime('%Y-%m-%d')
    path = os.path.join(ARCHIVE_DIR, today_str)
    if not os.path.exists(path): os.makedirs(path)
    return path


def generate_equity_curve(trades, save_dir):
    """
    绘制基于时间的账户余额变化曲线
    """
    if not trades: return None
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


def process_trades_to_csv(trades, save_dir):
    """
    将交易记录转换为 CSV 文件并保存
    """
    if not trades:
        return None, None

    # 将列表转换为 DataFrame
    df = pd.DataFrame(trades)

    # 简单的格式化处理：将时间戳转换为可读时间
    if 'entry_time' in df.columns:
        df['entry_time_dt'] = pd.to_datetime(df['entry_time'], unit='ms')
    if 'exit_time' in df.columns:
        df['exit_time_dt'] = pd.to_datetime(df['exit_time'], unit='ms')

    # 如果 snapshots 数据太大，可以选择在 CSV 中移除它，保持表格整洁
    # if 'snapshots' in df.columns:
    #     df = df.drop(columns=['snapshots'])

    # 生成文件名
    filename = f"trades_export_{int(time.time())}.csv"
    filepath = os.path.join(save_dir, filename)

    # 保存文件
    df.to_csv(filepath, index=False, encoding='utf-8-sig')

    return filepath, filename


def generate_sparkline(snapshots, trade_id, save_dir):
    if not snapshots or len(snapshots) < 2: return None
    df = pd.DataFrame(snapshots)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    fig, ax = plt.subplots(figsize=(2, 0.5))
    ax.axhline(y=0, color='#666666', linestyle='--', linewidth=0.5, alpha=0.8)
    ax.plot(df['time'], df['pnl'], color='#333333', linewidth=0.8, alpha=0.8)
    ax.fill_between(df['time'], df['pnl'], 0, where=(df['pnl'] >= 0), interpolate=True, color='#00a65a', alpha=0.3)
    ax.fill_between(df['time'], df['pnl'], 0, where=(df['pnl'] < 0), interpolate=True, color='#dd4b39', alpha=0.3)

    final_pnl = snapshots[-1]['pnl']
    end_color = '#00a65a' if final_pnl >= 0 else '#dd4b39'
    ax.scatter(df['time'].iloc[-1], final_pnl, s=10, c=end_color, zorder=5)

    ax.axis('off')
    plt.margins(0.05, 0.1)

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight', pad_inches=0, transparent=True, dpi=100)
    buffer.seek(0)
    img_str = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close(fig)
    return f"data:image/png;base64,{img_str}"


def generate_no_trade_html(status_data):
    """
    生成静默期间的心跳报告
    """
    if not status_data:
        return "<html><body><h1>⚠️ 警告：无法获取机器人心跳数据</h1><p>Redis 中没有 bot_status_heartbeat 数据，请检查 main.py 是否运行。</p></body></html>"

    # 解析数据
    ts = datetime.fromtimestamp(status_data['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
    balance = status_data['balance']
    price = status_data['price']
    regime = status_data['regime']
    ai_conf = status_data['ai_conf']

    # 简单的 CSS
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

def generate_report(trades):
    if not trades: return None, None, None
    daily_dir = ensure_daily_dir()

    # 1. 生成附件 (CSV 和 资金曲线)
    csv_path, csv_filename = process_trades_to_csv(trades, daily_dir)
    equity_curve_b64 = generate_equity_curve(trades, daily_dir)

    # 2. 计算宏观指标 (用于显示在邮件顶部的卡片)
    df_t = pd.DataFrame(trades)

    # 基础数据
    total_pnl = df_t['pnl'].sum()
    total_fee = df_t.get('fee', pd.Series([0] * len(df_t))).sum()
    current_balance = df_t.iloc[-1]['balance'] if not df_t.empty else 0.0

    # 胜率与盈亏比
    wins = df_t[df_t['pnl'] > 0]
    losses = df_t[df_t['pnl'] <= 0]
    win_rate = (len(wins) / len(df_t) * 100) if len(df_t) > 0 else 0

    # 获利因子 (Profit Factor)
    gross_profit = wins['pnl'].sum()
    gross_loss = abs(losses['pnl'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss != 0 else (gross_profit if gross_profit > 0 else 0)

    # 最大回撤 (简单的基于余额序列计算)
    balances_arr = df_t['balance'].values
    # 累积最大值
    peak = np.maximum.accumulate(balances_arr)
    # 当前回撤百分比
    drawdowns = (peak - balances_arr) / (peak + 1e-9)
    max_drawdown = drawdowns.max() * 100 if len(drawdowns) > 0 else 0

    # 3. 定义 CSS 样式 (合并了基础样式和你的自定义样式)
    css = """
        body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #333; font-size: 13px; max-width: 800px; margin: 0 auto; padding: 20px; }
        .header-title { font-size: 20px; font-weight: bold; margin-bottom: 5px; }
        .header-sub { color: #666; font-size: 12px; margin-bottom: 20px; }

        .summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }
        .metric-card { background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 15px 10px; text-align: center; }
        .metric-label { color: #6c757d; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px; }
        .metric-value { font-size: 18px; font-weight: 700; }
        .metric-sub { font-size: 10px; color: #999; margin-top: 3px; }

        .green { color: #28a745; } .red { color: #dc3545; } .blue { color: #007bff; }

        .chart-box { margin-bottom: 25px; border: 1px solid #eee; padding: 10px; border-radius: 8px; background: #fff; text-align: center;}
        .chart-img { max-width: 100%; height: auto; }

        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }
        th { background: #f1f3f5; padding: 8px; border-bottom: 2px solid #dee2e6; text-align: left; color: #495057; }
        td { padding: 8px; border-bottom: 1px solid #e9ecef; vertical-align: middle; }
        .sparkline { height: 30px; vertical-align: middle; }

        /* 标签与徽章样式 */
        .tag { display: inline-block; padding: 2px 6px; font-size: 10px; border-radius: 4px; border: 1px solid #eee; background: #f8f9fa; color: #666; }
        .badge-tp { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .badge-bail { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
        .badge-sl { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .cluster-tag { font-family: monospace; font-weight: bold; color: #6610f2; background: #f3f0ff; border: 1px solid #e0cffc; padding: 1px 4px; border-radius: 4px; }
    """

    # 4. 构建表格行 HTML
    table_header = "<thead><tr><th>Time</th><th>Action/Cluster</th><th>PnL (Net)</th><th>Trend</th><th>Exit Reason</th></tr></thead>"
    rows_html = ""

    for t in trades:
        # 微型走势图
        spark_b64 = generate_sparkline(t.get('snapshots', []), t['entry_time'], daily_dir)
        img_tag = f'<img src="{spark_b64}" class="sparkline">' if spark_b64 else '<span style="color:#ccc">-</span>'

        # PnL 颜色
        pnl_cls = "green" if t['pnl'] >= 0 else "red"

        # 时间格式化
        t_str = datetime.fromtimestamp(t['entry_time'] / 1000).strftime('%H:%M')

        # Cluster ID (新增)
        c_id = t.get('cluster', '?')

        # Exit Reason 样式处理 (新增)
        reason_raw = t.get('reason', 'Unknown')
        reason_cls = "tag"  # 默认基础样式

        # 根据关键词添加特定颜色类
        if any(x in reason_raw for x in ["TP", "Profit", "Target", "Win"]):
            reason_cls += " badge-tp"
        elif any(x in reason_raw for x in ["Bailout", "Flip", "Esc", "逃逸"]):
            reason_cls += " badge-bail"
        elif any(x in reason_raw for x in ["SL", "Loss", "Stop", "熔断"]):
            reason_cls += " badge-sl"

        # 构建单行 HTML
        rows_html += f"""
        <tr>
            <td>{t_str}</td>
            <td>
                <b>{t['action']}</b> <span style="color:#999;font-size:10px;">x{t['leverage']}</span><br>
                <span class="cluster-tag">C{c_id}</span>
            </td>
            <td class="{pnl_cls}"><strong>${t['pnl']:+.2f}</strong><br><span style="font-size:10px;color:#999">Fee: -{t.get('fee', 0):.2f}</span></td>
            <td>{img_tag}</td>
            <td>
                <span class="{reason_cls}">{reason_raw}</span><br>
                <span style="font-size:10px;color:#ccc">{t['regime']}</span>
            </td>
        </tr>
        """

    # 5. 组装最终 HTML
    html = f"""
    <html><head><style>{css}</style></head>
    <body>
        <div class="header-title">📊 XRP 量化策略复盘报告</div>
        <div class="header-sub">{datetime.now().strftime('%Y-%m-%d %H:%M')} | Auto-generated by Quant System</div>

        <div class="summary-grid">
            <div class="metric-card">
                <div class="metric-label">当前总资产 (Equity)</div>
                <div class="metric-value blue">${current_balance:.2f}</div>
                <div class="metric-sub">净盈亏: <span class="{'green' if total_pnl >= 0 else 'red'}">${total_pnl:+.2f}</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-label">获利因子 (PF)</div>
                <div class="metric-value {'green' if profit_factor > 1.5 else 'red'}">{profit_factor:.2f}</div>
                <div class="metric-sub">Wins: {len(wins)} | Loss: {len(losses)}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">胜率 (WinRate)</div>
                <div class="metric-value">{win_rate:.1f}%</div>
                <div class="metric-sub">MaxDD: <span class="red">-{max_drawdown:.2f}%</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-label">总手续费 (Fees)</div>
                <div class="metric-value red">-${total_fee:.2f}</div>
                <div class="metric-sub">Trades: {len(df_t)}</div>
            </div>
        </div>

        <div class="chart-box">
            <img src="{equity_curve_b64}" class="chart-img">
        </div>

        <table>
            {table_header}
            <tbody>
            {rows_html}
            </tbody>
        </table>
        <p style='text-align:center;color:#999;margin-top:20px;'>Generated by Abyssalfish Quant System</p>
    </body></html>
    """

    # 6. 保存到文件
    html_filename = f"report_{int(time.time())}.html"
    with open(os.path.join(daily_dir, html_filename), "w", encoding="utf-8") as f:
        f.write(html)

    return html, csv_path, csv_filename


def send_digest():
    print(f"[{datetime.now()}] 准备生成报告...")

    # 1. 尝试获取交易列表
    trades = []
    while True:
        item = r.lpop('trade_journal_pending')
        if not item: break
        trades.append(json.loads(item))

    # 2. 分情况处理
    if trades:
        # A. 有交易：发送完整战报
        print(f"检测到 {len(trades)} 笔新交易，生成详细战报...")
        try:
            html, csv_path, csv_name = generate_report(trades)
            with open(csv_path, 'rb') as f:
                csv_bytes = f.read()

            try:
                pf_val = html.split('获利因子 (PF)')[1].split('metric-value')[1].split('>')[1].split('<')[0]
            except:
                pf_val = "N/A"

            params = {
                "from": MAIL_FROM, "to": MAIL_TO,
                "subject": f"📊 [战报] XRP 策略简报 | {len(trades)} Trades | PF:{pf_val}",
                "html": html,
                "attachments": [{"filename": csv_name, "content": list(csv_bytes)}]
            }
            resend.Emails.send(params)
            print("✅ 战报邮件发送成功！")
        except Exception as e:
            print(f"❌ 战报发送失败: {e}")
            for t in reversed(trades): r.lpush('trade_journal_pending', json.dumps(t))

    else:
        print("无新交易，生成静默心跳报告...")
        try:
            heartbeat_raw = r.get('bot_status_heartbeat')
            status_data = json.loads(heartbeat_raw) if heartbeat_raw else None
            html = generate_no_trade_html(status_data)
            current_balance = status_data['balance'] if status_data else 0.0

            params = {
                "from": MAIL_FROM, "to": MAIL_TO,
                "subject": f"😴 [静默] XRP 运行日报 | Bal:${current_balance:.2f} | No Trades",
                "html": html
            }
            resend.Emails.send(params)
            print("✅ 静默邮件发送成功！")
        except Exception as e:
            print(f"❌ 静默邮件发送失败: {e}")


schedule.every().day.at("11:00").do(send_digest)
schedule.every().day.at("23:00").do(send_digest)

if __name__ == "__main__":
    if not os.path.exists(ARCHIVE_DIR): os.makedirs(ARCHIVE_DIR)
    print(f"=== 报告服务 (Equity Curve & Risk Analysis) 已启动 ===")
    while True: schedule.run_pending(); time.sleep(1)