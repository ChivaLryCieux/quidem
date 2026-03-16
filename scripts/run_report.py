
import sys
import os
import time
import schedule
import json
import resend
import logging

# Fix path
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)

from core.utils.reporting import ReportService
from core.config.settings import Config

# Configurations
MAIL_FROM = Config.MAIL_FROM
MAIL_TO = Config.MAIL_TO
RESEND_API_KEY = Config.RESEND_API_KEY

resend.api_key = RESEND_API_KEY
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ReportRunner")

service = ReportService()

def _format_change(change_pct):
    """格式化24h涨跌幅"""
    if change_pct >= 0:
        return f"📈 +{change_pct:.2f}%"
    else:
        return f"📉 {change_pct:.2f}%"

def job(include_daily_indicators=False):
    logger.info("Starting Report Job...")
    r = service.redis_client
    if not r:
        logger.error("Redis not available")
        return

    # 1. Fetch pending trades
    trades = []
    while True:
        item = r.lpop('trade_journal_pending')
        if not item: break
        try:
            trades.append(json.loads(item))
        except: pass
    
    # 获取24h涨跌幅
    hb_raw = r.get('bot_status_heartbeat')
    status = json.loads(hb_raw) if hb_raw else None
    change_24h = status.get('change_24h', 0.0) if status else 0.0
    change_str = _format_change(change_24h)
    
    daily_indicators = service.fetch_daily_indicators() if include_daily_indicators else None

    # 2. Generate and Send
    try:
        if trades:
            logger.info(f"Generating report for {len(trades)} trades...")
            html = service.generate_trade_report_html(
                trades,
                change_24h=change_24h,
                daily_indicators=daily_indicators
            )
            csv_path, csv_name = service.create_csv_export(trades)
            
            # Read CSV bytes
            csv_content = []
            if csv_path and os.path.exists(csv_path):
                with open(csv_path, 'rb') as f:
                    csv_content = list(f.read())
            
            params = {
                "from": MAIL_FROM, "to": MAIL_TO,
                "subject": f"📊 [Report] CTA q-bot | {len(trades)} Trades | 24h: {change_str}",
                "html": html,
                "attachments": [{"filename": csv_name, "content": csv_content}] if csv_content else []
            }
            resend.Emails.send(params)
            logger.info("Trade Report Sent.")
        else:
            logger.info("No trades. Checking heartbeat...")
            
            html = service.generate_heartbeat_html(status, daily_indicators=daily_indicators)
            bal = status.get('balance', 0) if status else 0
            
            params = {
                "from": MAIL_FROM, "to": MAIL_TO,
                "subject": f"😴 [Silence] CTA q-bot | Bal: ${bal:.2f} | 24h: {change_str}",
                "html": html
            }
            resend.Emails.send(params)
            logger.info("Heartbeat Report Sent.")

    except Exception as e:
        logger.error(f"Failed to send report: {e}")
        # Put trades back if failed
        for t in reversed(trades):
            r.lpush('trade_journal_pending', json.dumps(t))

# Schedule
schedule.every().day.at("11:00").do(lambda: job(include_daily_indicators=True))
schedule.every().day.at("23:00").do(lambda: job(include_daily_indicators=False))

if __name__ == "__main__":
    print(">>> Report Runner Started")
    print(f"Target Emails: {MAIL_TO}")
    
    while True:
        schedule.run_pending()
        time.sleep(1)
