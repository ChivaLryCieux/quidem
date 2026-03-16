import logging
import os
import sys
import time
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Tuple

import requests

# Fix path
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)

from core.config.settings import Config
from core.utils.mailer import MailService

logger = logging.getLogger("LiquidationAlert")


class BinanceLiquidationWatcher:
    """监控 Binance 强平订单并在短时间内累计爆仓量过阈值时触发邮件预警。"""

    BASE_URL = "https://fapi.binance.com"
    FORCE_ORDERS_API = "/fapi/v1/allForceOrders"

    def __init__(
        self,
        symbol: str,
        window_sec: int,
        threshold_usd: float,
        poll_interval_sec: int,
        cooldown_sec: int,
        timeout_sec: int = 8,
    ):
        self.symbol = symbol.upper()
        self.window_ms = max(10, int(window_sec)) * 1000
        self.threshold_usd = float(threshold_usd)
        self.poll_interval_sec = max(5, int(poll_interval_sec))
        self.cooldown_sec = max(0, int(cooldown_sec))
        self.timeout_sec = timeout_sec

        self.session = requests.Session()
        self.mail_service = MailService()
        self._events: Deque[Dict] = deque()
        self._event_keys = set()
        self._last_fetch_ms = 0
        self._last_alert_ts = 0.0

    def _build_event_key(self, item: Dict) -> Tuple:
        return (
            item.get("orderId"),
            item.get("symbol"),
            item.get("time"),
            item.get("side"),
            item.get("origQty"),
            item.get("avgPrice") or item.get("price"),
        )

    def _extract_notional(self, item: Dict) -> float:
        price = float(item.get("avgPrice") or item.get("price") or 0)
        qty = float(item.get("origQty") or item.get("executedQty") or 0)
        return abs(price * qty)

    def fetch_force_orders(self) -> List[Dict]:
        now_ms = int(time.time() * 1000)
        if self._last_fetch_ms > 0:
            start_ms = max(self._last_fetch_ms - 5000, now_ms - self.window_ms)
        else:
            start_ms = now_ms - self.window_ms

        params = {
            "symbol": self.symbol,
            "startTime": start_ms,
            "endTime": now_ms,
            "limit": 1000,
        }
        resp = self.session.get(
            f"{self.BASE_URL}{self.FORCE_ORDERS_API}",
            params=params,
            timeout=self.timeout_sec,
        )
        resp.raise_for_status()
        self._last_fetch_ms = now_ms
        return resp.json() or []

    def _push_new_events(self, orders: List[Dict]):
        for item in orders:
            key = self._build_event_key(item)
            if key in self._event_keys:
                continue
            notional = self._extract_notional(item)
            event = {
                "key": key,
                "time": int(item.get("time") or 0),
                "side": item.get("side", "UNKNOWN"),
                "qty": float(item.get("origQty") or 0),
                "price": float(item.get("avgPrice") or item.get("price") or 0),
                "notional": notional,
            }
            self._events.append(event)
            self._event_keys.add(key)

    def _prune_old_events(self):
        threshold = int(time.time() * 1000) - self.window_ms
        while self._events and self._events[0]["time"] < threshold:
            old = self._events.popleft()
            self._event_keys.discard(old["key"])

    def _compute_window_stats(self) -> Dict:
        total = 0.0
        buy_total = 0.0
        sell_total = 0.0
        for event in self._events:
            n = event["notional"]
            total += n
            if event["side"] == "BUY":
                buy_total += n
            elif event["side"] == "SELL":
                sell_total += n

        return {
            "count": len(self._events),
            "total_usd": total,
            "buy_total_usd": buy_total,
            "sell_total_usd": sell_total,
        }

    def _send_alert_if_needed(self, stats: Dict):
        total = stats["total_usd"]
        now = time.time()
        if total < self.threshold_usd:
            return

        if now - self._last_alert_ts < self.cooldown_sec:
            logger.info(
                "Threshold reached but in cooldown. total=%.2f threshold=%.2f",
                total,
                self.threshold_usd,
            )
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = (
            f"🚨 Binance爆仓预警 | {self.symbol} | "
            f"{self.window_ms // 1000}s内 ${total:,.0f}"
        )
        html = (
            f"<h3>Binance 爆仓量阈值触发</h3>"
            f"<p><b>交易对:</b> {self.symbol}</p>"
            f"<p><b>统计窗口:</b> {self.window_ms // 1000} 秒</p>"
            f"<p><b>阈值:</b> ${self.threshold_usd:,.0f}</p>"
            f"<p><b>当前爆仓总额:</b> <span style='color:#d93025;'>${total:,.2f}</span></p>"
            f"<p><b>爆空(BUY):</b> ${stats['buy_total_usd']:,.2f}</p>"
            f"<p><b>爆多(SELL):</b> ${stats['sell_total_usd']:,.2f}</p>"
            f"<p><b>事件数量:</b> {stats['count']}</p>"
            f"<p><b>触发时间:</b> {ts}</p>"
            f"<p><b>说明:</b> 数据来源 Binance /fapi/v1/allForceOrders。</p>"
        )
        sent = self.mail_service.send_alert(subject, html)
        if sent:
            self._last_alert_ts = now
            logger.warning(
                "Liquidation alert sent. symbol=%s total=%.2f threshold=%.2f",
                self.symbol,
                total,
                self.threshold_usd,
            )

    def run_forever(self):
        logger.info(
            "Start liquidation watcher symbol=%s window=%ss threshold=%.2f poll=%ss cooldown=%ss",
            self.symbol,
            self.window_ms // 1000,
            self.threshold_usd,
            self.poll_interval_sec,
            self.cooldown_sec,
        )
        while True:
            try:
                orders = self.fetch_force_orders()
                self._push_new_events(orders)
                self._prune_old_events()
                stats = self._compute_window_stats()
                logger.info(
                    "Window stats symbol=%s count=%d total=%.2f buy=%.2f sell=%.2f",
                    self.symbol,
                    stats["count"],
                    stats["total_usd"],
                    stats["buy_total_usd"],
                    stats["sell_total_usd"],
                )
                self._send_alert_if_needed(stats)
            except requests.RequestException as exc:
                logger.error("Binance API request failed: %s", exc)
            except Exception as exc:
                logger.exception("Watcher loop error: %s", exc)

            time.sleep(self.poll_interval_sec)


def main():
    logging.basicConfig(
        level=getattr(logging, str(Config.LOG_LEVEL).upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if not Config.ENABLE_LIQUIDATION_ALERT:
        logger.warning("ENABLE_LIQUIDATION_ALERT=False, watcher will exit.")
        return

    watcher = BinanceLiquidationWatcher(
        symbol=Config.LIQUIDATION_ALERT_SYMBOL,
        window_sec=Config.LIQUIDATION_ALERT_WINDOW_SEC,
        threshold_usd=Config.LIQUIDATION_ALERT_THRESHOLD_USD,
        poll_interval_sec=Config.LIQUIDATION_ALERT_POLL_INTERVAL_SEC,
        cooldown_sec=Config.LIQUIDATION_ALERT_COOLDOWN_SEC,
    )
    watcher.run_forever()


if __name__ == "__main__":
    main()
