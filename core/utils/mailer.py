import logging

import resend

from core.config.settings import Config

logger = logging.getLogger(__name__)


class MailService:
    def __init__(self):
        self.enabled = bool(Config.ENABLE_MAIL_REPORT and Config.RESEND_API_KEY and Config.MAIL_TO)
        if self.enabled:
            resend.api_key = Config.RESEND_API_KEY
        else:
            logger.info("MailService disabled (ENABLE_MAIL_REPORT/API key/MAIL_TO not fully configured)")

    def send_alert(self, subject, html):
        if not self.enabled:
            return False

        try:
            resend.Emails.send({
                "from": Config.MAIL_FROM,
                "to": Config.MAIL_TO,
                "subject": subject,
                "html": html,
            })
            logger.info("Alert email sent: %s", subject)
            return True
        except Exception as exc:
            logger.error("Failed to send alert email: %s", exc)
            return False
