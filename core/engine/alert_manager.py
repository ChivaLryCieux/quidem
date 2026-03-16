import logging
from datetime import datetime

from core.analysis.bocpd import BOCPDDetector
from core.utils.mailer import MailService

logger = logging.getLogger(__name__)


class AlertManager:
    KDJ_J_OVERBOUGHT = 100
    KDJ_J_OVERSOLD = 0
    KDJ_ADX_FILTER = 25
    ADX_ALERT_THRESHOLD = 75

    def __init__(self):
        self.mail_service = MailService()
        self.bocpd = BOCPDDetector()
        self.last_bocpd_cp = None
        self.last_kdj_state = None
        self.adx_alert_active = False

    def check_and_alert(self, history_5m, analysis):
        if history_5m is None or history_5m.empty or analysis is None:
            return

        self._check_bocpd_alert(history_5m)
        self._check_kdj_j_alert(history_5m, analysis)
        self._check_adx_alert(history_5m, analysis)

    def _check_bocpd_alert(self, history_5m):
        cps = self.bocpd.detect_changepoints(history_5m['close'].values)
        if len(cps) == 0:
            return

        latest_cp = int(cps[-1])
        if self.last_bocpd_cp is not None and latest_cp <= self.last_bocpd_cp:
            return

        if latest_cp != len(history_5m) - 1:
            return

        cp_row = history_5m.iloc[latest_cp]
        ts = datetime.fromtimestamp(int(cp_row['timestamp']) / 1000).strftime('%Y-%m-%d %H:%M:%S')
        price = float(cp_row['close'])
        subject = f"🚨 BOCPD变点预警 | {ts}"
        html = (
            f"<h3>检测到BOCPD变点</h3>"
            f"<p><b>时间:</b> {ts}</p>"
            f"<p><b>价格:</b> {price:.4f}</p>"
            f"<p><b>变点索引:</b> {latest_cp}</p>"
        )
        self.mail_service.send_alert(subject, html)
        self.last_bocpd_cp = latest_cp
        logger.warning("BOCPD changepoint alert triggered at index=%s", latest_cp)

    def _check_kdj_j_alert(self, history_5m, analysis):
        kdj_j = float(analysis.get('kdj_j', 50.0))
        adx = float(analysis.get('adx', 0.0))

        if adx <= self.KDJ_ADX_FILTER:
            self.last_kdj_state = None
            return

        if kdj_j >= self.KDJ_J_OVERBOUGHT:
            state = 'overbought'
            label = 'J值超买'
            icon = '🔴'
        elif kdj_j <= self.KDJ_J_OVERSOLD:
            state = 'oversold'
            label = 'J值超卖'
            icon = '🟢'
        else:
            self.last_kdj_state = None
            return

        if self.last_kdj_state == state:
            return

        last_row = history_5m.iloc[-1]
        ts = datetime.fromtimestamp(int(last_row['timestamp']) / 1000).strftime('%Y-%m-%d %H:%M:%S')
        price = float(last_row['close'])

        subject = f"{icon} KDJ-J值预警 | {label} | ADX {adx:.2f} > {self.KDJ_ADX_FILTER}"
        html = (
            f"<h3>KDJ-J值触发预警</h3>"
            f"<p><b>状态:</b> {label}</p>"
            f"<p><b>J值:</b> {kdj_j:.2f}</p>"
            f"<p><b>ADX:</b> {adx:.2f}</p>"
            f"<p><b>触发条件:</b> ADX>{self.KDJ_ADX_FILTER} 且 J值触及极值</p>"
            f"<p><b>时间:</b> {ts}</p>"
            f"<p><b>价格:</b> {price:.4f}</p>"
        )
        self.mail_service.send_alert(subject, html)
        self.last_kdj_state = state
        logger.warning("KDJ-J alert triggered: state=%s, j=%.2f, adx=%.2f", state, kdj_j, adx)

    def _check_adx_alert(self, history_5m, analysis):
        adx = float(analysis.get('adx', 0.0))

        if adx <= self.ADX_ALERT_THRESHOLD:
            self.adx_alert_active = False
            return

        if self.adx_alert_active:
            return

        last_row = history_5m.iloc[-1]
        ts = datetime.fromtimestamp(int(last_row['timestamp']) / 1000).strftime('%Y-%m-%d %H:%M:%S')
        price = float(last_row['close'])

        subject = "🟣 ADX强趋势预警 | ADX > 75"
        html = (
            f"<h3>ADX触发预警</h3>"
            f"<p><b>状态:</b> ADX超过75，趋势极强</p>"
            f"<p><b>ADX:</b> {adx:.2f}</p>"
            f"<p><b>时间:</b> {ts}</p>"
            f"<p><b>价格:</b> {price:.4f}</p>"
        )
        self.mail_service.send_alert(subject, html)
        self.adx_alert_active = True
        logger.warning("ADX alert triggered: adx=%.2f", adx)
