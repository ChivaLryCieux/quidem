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
MAIL_FROM = "XRP量化基金 <report@abyssalfish.top>"
MAIL_TO = ["3433551710@qq.com", "2874575651@qq.com"]

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


# === 新增：生成资金权益曲线大图 ===
def generate_equity_curve(trades, save_dir):
    """
    绘制基于时间的账户余额变化曲线
    """
    if not trades: return None

    # 提取时间与余额
    df = pd.DataFrame(trades)
    df['time'] = pd.to_datetime(df['exit_time'], unit='ms')

    # 构造数据：包含初始状态（假设第一笔交易前的余额）
    # 这里简化处理，直接画出每一笔交易后的余额连线
    times = df['time'].tolist()
    balances = df['balance'].tolist()

    fig, ax = plt.subplots(figsize=(8, 3))  # 宽8高3，适合邮件阅读

    # 绘制曲线
    ax.plot(times, balances, color='#007bff', linewidth=2, label='Equity')
    ax.fill_between(times, balances, min(balances) * 0.99, color='#007bff', alpha=0.1)

    # 样式优化
    ax.set_title("Account Equity Curve (Session)", fontsize=10, pad=10)
    ax.grid(True, which='both', linestyle='--', linewidth=0.5, alpha=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # 格式化时间轴
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.xticks(fontsize=8)
    plt.yticks(fontsize=8)

    # 保存
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight', dpi=100)
    buffer.seek(0)
    img_str = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close(fig)
    return f"data:image/png;base64,{img_str}"


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


def process_trades_to_csv(trades, save_dir):
    csv_rows = []
    columns = ["Trade_ID", "Mode", "Action", "Leverage", "Entry_Price", "Exit_Price",
               "Final_PnL", "Fee", "Snapshot_Time", "Current_Price", "Current_PnL", "Regime"]

    for t in trades:
        if t.get('snapshots'):
            for s in t['snapshots']:
                csv_rows.append({
                    "Trade_ID": t['entry_time'], "Mode": t['mode'], "Action": t['action'],
                    "Leverage": t['leverage'], "Entry_Price": t['entry_price'], "Exit_Price": t['exit_price'],
                    "Final_PnL": t['pnl'], "Fee": t.get('fee', 0),
                    "Snapshot_Time": datetime.fromtimestamp(s['time']).strftime('%Y-%m-%d %H:%M:%S'),
                    "Current_Price": s['price'], "Current_PnL": s['pnl'], "Regime": s['regime']
                })
        else:
            csv_rows.append({
                "Trade_ID": t['entry_time'], "Mode": t['mode'], "Action": t['action'],
                "Final_PnL": t['pnl'], "Fee": t.get('fee', 0), "Regime": "NO_DATA"
            })
        empty_row = {col: "" for col in columns}
        csv_rows.extend([empty_row] * 3)

    df = pd.DataFrame(csv_rows)
    df = df[columns]
    filename = f"details_{int(time.time())}.csv"
    filepath = os.path.join(save_dir, filename)
    df.to_csv(filepath, index=False, encoding='utf-8-sig', na_rep='')
    return filepath, filename


def generate_report(trades):
    if not trades: return None, None, None
    daily_dir = ensure_daily_dir()
    print(f"📂 生成报告中: {daily_dir}")

    csv_path, csv_filename = process_trades_to_csv(trades, daily_dir)
    equity_curve_b64 = generate_equity_curve(trades, daily_dir)

    # === 增强版宏观指标计算 ===
    df_t = pd.DataFrame(trades)
    total_pnl = df_t['pnl'].sum()
    total_fee = df_t.get('fee', pd.Series([0] * len(df_t))).sum()

    # 1. 最终资产 (取最后一笔交易的余额)
    current_balance = df_t.iloc[-1]['balance'] if not df_t.empty else 0.0

    # 2. 胜率 & 盈亏比
    wins = df_t[df_t['pnl'] > 0]
    losses = df_t[df_t['pnl'] <= 0]
    win_rate = (len(wins) / len(df_t) * 100) if len(df_t) > 0 else 0

    avg_win = wins['pnl'].mean() if not wins.empty else 0
    avg_loss = abs(losses['pnl'].mean()) if not losses.empty else 0
    # 盈亏比 (Risk/Reward Ratio)
    rr_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0

    # 3. 获利因子 (PF)
    gross_profit = wins['pnl'].sum()
    gross_loss = abs(losses['pnl'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss != 0 else 99.99

    # 4. 最大回撤 (Max Drawdown)
    # 构造余额序列
    balances = df_t['balance'].values
    # 计算累计最大值 (High Watermark)
    peak = np.maximum.accumulate(balances)
    # 计算回撤
    drawdowns = (peak - balances) / peak
    max_drawdown = drawdowns.max() * 100 if len(drawdowns) > 0 else 0

    css = """
        body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #333; font-size: 13px; max-width: 800px; margin: 0 auto; padding: 20px; }
        .header-title { font-size: 20px; font-weight: bold; margin-bottom: 5px; }
        .header-sub { color: #666; font-size: 12px; margin-bottom: 20px; }

        /* 核心大卡片 */
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
        .tag { display: inline-block; padding: 2px 5px; font-size: 10px; border-radius: 3px; background: #eee; color: #555; }
    """

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
                <div class="metric-sub">每亏$1赚${profit_factor:.2f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">胜率 & 盈亏比</div>
                <div class="metric-value">{win_rate:.1f}%</div>
                <div class="metric-sub">平均盈亏比: 1:{rr_ratio:.2f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">最大回撤 (MDD)</div>
                <div class="metric-value red">-{max_drawdown:.2f}%</div>
                <div class="metric-sub">手续费: -${total_fee:.2f}</div>
            </div>
        </div>

        <div class="chart-box">
            <img src="{equity_curve_b64}" class="chart-img">
        </div>

        <table>
            <thead><tr><th>Time</th><th>Action</th><th>PnL (Net)</th><th>Trend</th><th>Details</th></tr></thead>
            <tbody>
    """

    for t in trades:
        spark_b64 = generate_sparkline(t.get('snapshots', []), t['entry_time'], daily_dir)
        img_tag = f'<img src="{spark_b64}" class="sparkline">' if spark_b64 else '<span style="color:#ccc">-</span>'
        pnl_cls = "green" if t['pnl'] >= 0 else "red"
        t_str = datetime.fromtimestamp(t['entry_time'] / 1000).strftime('%H:%M')

        html += f"""
        <tr>
            <td>{t_str}</td>
            <td><b>{t['action']}</b> <span style="color:#999;font-size:10px;">x{t['leverage']}</span></td>
            <td class="{pnl_cls}"><strong>${t['pnl']:+.2f}</strong><br><span style="font-size:10px;color:#999">Fee: -{t.get('fee', 0):.2f}</span></td>
            <td>{img_tag}</td>
            <td>
                <span class="tag">{t['regime']}</span><br>
                <span style="font-size:10px;color:#999">{t['reason']}</span>
            </td>
        </tr>
        """

    html += "</tbody></table><p style='text-align:center;color:#999;margin-top:20px;'>Generated by Abyssalfish Quant System</p></body></html>"

    html_filename = f"report_{int(time.time())}.html"
    with open(os.path.join(daily_dir, html_filename), "w", encoding="utf-8") as f:
        f.write(html)
    return html, csv_path, csv_filename


def send_digest():
    print(f"[{datetime.now()}] 准备生成报告...")
    trades = []
    while True:
        item = r.lpop('trade_journal_pending')
        if not item: break
        trades.append(json.loads(item))

    if not trades: print("无交易数据，跳过。"); return

    try:
        html, csv_path, csv_name = generate_report(trades)
        with open(csv_path, 'rb') as f:
            csv_bytes = f.read()

        params = {
            "from": MAIL_FROM, "to": MAIL_TO,
            "subject": f"📊 [复盘] XRP 策略简报 | PF:{html.split('metric-value')[3].split('<')[0].split('>')[1]}",
            # 标题直接带PF
            "html": html,
            "attachments": [{"filename": csv_name, "content": list(csv_bytes)}]
        }
        resend.Emails.send(params)
        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 失败: {e}")
        for t in reversed(trades): r.lpush('trade_journal_pending', json.dumps(t))


schedule.every().day.at("11:00").do(send_digest)
schedule.every().day.at("23:00").do(send_digest)

if __name__ == "__main__":
    if not os.path.exists(ARCHIVE_DIR): os.makedirs(ARCHIVE_DIR)
    print(f"=== 基金级报告服务 (Equity Curve & Risk Analysis) 已启动 ===")
    while True: schedule.run_pending(); time.sleep(1)