try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    resend = None

import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self, api_key=None, from_email=None, proxy_config=None):
        """
        初始化通知服务
        
        Args:
            api_key: Resend API密钥
            from_email: 发件人邮箱
            proxy_config: 代理配置字典，如 {'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890'}
        """
        self.api_key = api_key or os.environ.get('RESEND_API_KEY')
        self.from_email = from_email or os.environ.get('MAIL_FROM', 'report@abyssalfish.top')
        
        # 设置代理
        if proxy_config:
            os.environ["HTTP_PROXY"] = proxy_config.get('http', '')
            os.environ["HTTPS_PROXY"] = proxy_config.get('https', '')
            
        # 初始化resend
        if self.api_key and RESEND_AVAILABLE:
            resend.api_key = self.api_key
        elif not RESEND_AVAILABLE:
            logger.warning("resend module not available. Email functionality will be limited.")
            
    def send_email(self, to_emails, subject, html_content, attachments=None):
        """
        发送邮件
        
        Args:
            to_emails: 收件人邮箱列表
            subject: 邮件主题
            html_content: HTML内容
            attachments: 附件列表，格式为 [{'filename': 'file.csv', 'content': bytes}]
            
        Returns:
            发送结果
        """
        if not RESEND_AVAILABLE:
            logger.warning("resend module not available. Cannot send email.")
            return None
            
        try:
            params = {
                "from": self.from_email,
                "to": to_emails if isinstance(to_emails, list) else [to_emails],
                "subject": subject,
                "html": html_content
            }
            
            if attachments:
                params["attachments"] = attachments
                
            result = resend.Emails.send(params)
            logger.info(f"邮件发送成功: {subject}")
            return result
            
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            raise e
            
    def send_trade_alert(self, to_emails, trade_data):
        """发送交易提醒"""
        subject = f"🔄 交易提醒 - {trade_data['action']} {trade_data['symbol']} @ ${trade_data['price']:.4f}"
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #007bff;">交易提醒</h2>
            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>交易动作:</strong> {trade_data['action']}</p>
                <p><strong>交易品种:</strong> {trade_data['symbol']}</p>
                <p><strong>交易价格:</strong> ${trade_data['price']:.4f}</p>
                <p><strong>仓位大小:</strong> {trade_data['size']}</p>
                <p><strong>杠杆倍数:</strong> {trade_data['leverage']}x</p>
                <p><strong>盈亏:</strong> ${trade_data['pnl']:+.2f}</p>
                <p><strong>当前余额:</strong> ${trade_data['balance']:.2f}</p>
            </div>
            <p style="color: #666; font-size: 12px;">
                发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </p>
        </body>
        </html>
        """
        
        return self.send_email(to_emails, subject, html_content)
        
    def send_error_alert(self, to_emails, error_data):
        """发送错误警报"""
        subject = f"⚠️ 系统错误 - {error_data['error_type']}"
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #dc3545;">系统错误警报</h2>
            <div style="background: #f8d7da; padding: 15px; border-radius: 8px; margin: 20px 0; border: 1px solid #f5c6cb;">
                <p><strong>错误类型:</strong> {error_data['error_type']}</p>
                <p><strong>错误信息:</strong> {error_data['error_message']}</p>
                <p><strong>发生时间:</strong> {error_data['timestamp']}</p>
                {f"<p><strong>详细信息:</strong> {error_data.get('details', '')}</p>" if error_data.get('details') else ''}
            </div>
            <p style="color: #666; font-size: 12px;">
                发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </p>
        </body>
        </html>
        """
        
        return self.send_email(to_emails, subject, html_content)
        
    def send_daily_report(self, to_emails, report_data, attachments=None):
        """发送每日报告"""
        subject = report_data['subject']
        html_content = report_data['html_content']
        
        return self.send_email(to_emails, subject, html_content, attachments)