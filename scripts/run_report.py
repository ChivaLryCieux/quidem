
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

from core.services.reporting import ReportService
from core.config.settings import Config

# Configurations (Should ideally be in Config, but kept here for now as in original)
MAIL_FROM = "XRP Bot <report@abyssalfish.top>"
# You might want to move these to Config.SETTINGS_MAIL_TO if appropriate
MAIL_TO = getattr(Config, "MAIL_TO", ["3433551710@qq.com", "2874575651@qq.com", "2129325064@qq.com"])
RESEND_API_KEY = getattr(Config, "RESEND_API_KEY", "re_39zFrC4s_KhUDNyHg8ZFRR8LkXg8cN8Ry")

resend.api_key = RESEND_API_KEY
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ReportRunner")

service = ReportService()

def job():
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
    
    # 2. Generate and Send
    try:
        if trades:
            logger.info(f"Generating report for {len(trades)} trades...")
            html = service.generate_trade_report_html(trades)
            csv_path, csv_name = service.create_csv_export(trades)
            
            # Read CSV bytes
            csv_content = []
            if csv_path and os.path.exists(csv_path):
                with open(csv_path, 'rb') as f:
                    csv_content = list(f.read())
            
            params = {
                "from": MAIL_FROM, "to": MAIL_TO,
                "subject": f"📊 [Report] XRP Bot | {len(trades)} Trades",
                "html": html,
                "attachments": [{"filename": csv_name, "content": csv_content}] if csv_content else []
            }
            resend.Emails.send(params)
            logger.info("Trade Report Sent.")
        else:
            logger.info("No trades. Checking heartbeat...")
            hb_raw = r.get('bot_status_heartbeat')
            status = json.loads(hb_raw) if hb_raw else None
            
            html = service.generate_heartbeat_html(status)
            bal = status.get('balance', 0) if status else 0
            
            params = {
                "from": MAIL_FROM, "to": MAIL_TO,
                "subject": f"😴 [Silence] XRP Bot | Bal: ${bal:.2f}",
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
schedule.every().day.at("11:00").do(job)
schedule.every().day.at("23:00").do(job)

if __name__ == "__main__":
    print(">>> Report Runner Started")
    print(f"Target Emails: {MAIL_TO}")
    # Run once on start for testing? No, just loop.
    
    while True:
        schedule.run_pending()
        time.sleep(1)
