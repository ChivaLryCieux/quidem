try:
    import resend

    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    resend = None

import os
import logging
from datetime import datetime
from core.config.settings import Config  # 引入统一配置

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, api_key=None, from_email=None):
        """
        初始化通知服务

        Args:
            api_key: Resend API密钥 (优先使用参数，其次读取Config)
            from_email: 发件人邮箱
        """
        self.api_key = api_key or getattr(Config, 'RESEND_API_KEY', os.environ.get('RESEND_API_KEY'))
        self.from_email = from_email or getattr(Config, 'MAIL_FROM', os.environ.get('MAIL_FROM', 'report@quantbot.com'))

        # [优化] 代理配置建议在 main.py 启动时统一设置 (Config.setup_proxy)
        # 避免在这里修改 os.environ 导致影响其他模块(如ccxt)

        # 初始化resend
        if self.api_key and RESEND_AVAILABLE:
            resend.api_key = self.api_key
        elif not RESEND_AVAILABLE:
            logger.warning("未检测到 resend 模块，邮件功能不可用 (pip install resend)")
        elif not self.api_key:
            logger.warning("未配置 RESEND_API_KEY，邮件功能将无法发送")

    def send_email(self, to_emails, subject, html_content, attachments=None):
        """
        发送邮件 (异常安全版本)
        """
        if not RESEND_AVAILABLE or not self.api_key:
            logger.warning("邮件服务未就绪，跳过发送")
            return None

        try:
            # 确保收件人是列表
            to_list = to_emails if isinstance(to_emails, list) else [to_emails]

            params = {
                "from": self.from_email,
                "to": to_list,
                "subject": subject,
                "html": html_content
            }

            if attachments:
                params["attachments"] = attachments

            # [注意] resend.send 是同步阻塞网络IO
            # 如果是在主策略线程调用，务必确保网络通畅，或放到单独线程执行
            result = resend.Emails.send(params)

            # 简单的结果检查 (Resend 返回的是 dict 包含 id)
            if result and result.get('id'):
                logger.info(f"邮件发送成功: {subject} (ID: {result['id']})")
                return result
            else:
                logger.error(f"邮件发送响应异常: {result}")
                return None

        except Exception as e:
            # [致命修复] 捕获所有异常，绝不 crash 交易主程序
            logger.error(f"邮件发送失败 [{subject}]: {str(e)}")
            return None

    def send_trade_alert(self, to_emails, trade_data):
        """发送交易提醒"""
        # 使用 .get 安全获取数据，防止 KeyError
        action = trade_data.get('action', 'Unknown')
        symbol = trade_data.get('symbol', 'Unknown')
        price = trade_data.get('price', 0.0)

        subject = f"🔄 交易提醒 - {action} {symbol} @ ${price:.4f}"

        # 简单的内联样式 CSS
        html_content = f"""
        <html>
        <body style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
            <div style="border-bottom: 2px solid #007bff; padding-bottom: 10px; margin-bottom: 20px;">
                <h2 style="color: #007bff; margin: 0;">🤖 量化交易执行</h2>
            </div>

            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; border: 1px solid #e9ecef;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px 0; color: #666;">动作:</td><td style="font-weight: bold;">{action}</td></tr>
                    <tr><td style="padding: 5px 0; color: #666;">标的:</td><td>{symbol}</td></tr>
                    <tr><td style="padding: 5px 0; color: #666;">价格:</td><td>${price:.4f}</td></tr>
                    <tr><td style="padding: 5px 0; color: #666;">数量:</td><td>{trade_data.get('size', 0)}</td></tr>
                    <tr><td style="padding: 5px 0; color: #666;">杠杆:</td><td>{trade_data.get('leverage', 1)}x</td></tr>
                    <tr>
                        <td style="padding: 5px 0; color: #666;">预估盈亏:</td>
                        <td style="color: {'#28a745' if trade_data.get('pnl', 0) >= 0 else '#dc3545'}; font-weight: bold;">
                            ${trade_data.get('pnl', 0):+.2f}
                        </td>
                    </tr>
                </table>
            </div>

            <div style="margin-top: 15px; font-size: 12px; color: #999; text-align: center;">
                账户余额: ${trade_data.get('balance', 0):.2f} | 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </body>
        </html>
        """

        return self.send_email(to_emails, subject, html_content)

    def send_error_alert(self, to_emails, error_data):
        """发送错误警报"""
        e_type = error_data.get('error_type', 'Unknown Error')
        e_msg = error_data.get('error_message', 'No message provided')

        subject = f"⚠️ 系统警报 - {e_type}"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #dc3545;">🚨 系统异常警报</h2>
            <div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin: 20px 0; border: 1px solid #ffeeba; color: #856404;">
                <p><strong>类型:</strong> {e_type}</p>
                <p><strong>信息:</strong> {e_msg}</p>
                <p><strong>时间:</strong> {error_data.get('timestamp', datetime.now())}</p>
                {f"<div style='margin-top:10px; font-size:12px; white-space:pre-wrap;'>{error_data.get('details', '')}</div>" if error_data.get('details') else ''}
            </div>
        </body>
        </html>
        """

        return self.send_email(to_emails, subject, html_content)

    def send_daily_report(self, to_emails, report_data, attachments=None):
        """发送每日报告"""
        # 兼容 report_data 可能是字典也可能是直接内容的结构
        if isinstance(report_data, dict):
            subject = report_data.get('subject', f"日报 - {datetime.now().strftime('%Y-%m-%d')}")
            html_content = report_data.get('html_content', '无内容')
        else:
            subject = f"日报 - {datetime.now().strftime('%Y-%m-%d')}"
            html_content = str(report_data)

        return self.send_email(to_emails, subject, html_content, attachments)