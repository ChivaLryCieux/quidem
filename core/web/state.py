"""
Web 共享状态管理

线程安全的共享状态，用于在主循环和 Web 服务器之间传递数据。
"""

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class WebState:
    """线程安全的共享状态管理器"""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {
            'market': {
                'price': 0.0,
                'kline_5m': None,
                'kline_15m': None,
                'kline_1h': None,
                'orderbook': None,
                'funding_rate': 0.0,
                'btc_price': 0.0,
                'change_24h': 0.0,
            },
            'strategy': {
                'state': '⏳ 等待',
                'color': 'white',
                'adx': 0.0,
                'macd': 0.0,
                'reversal': 0.0,
                'supertrend_5m': 0,
                'supertrend_15m': 0,
                'supertrend_1h': 0,
            },
            'position': {
                'size': 0.0,
                'entry_price': 0.0,
                'sl': 0.0,
                'tp': 0.0,
                'entry_time': 0,
                'leverage': 10.0,
                'unrealized_pnl': 0.0,
            },
            'account': {
                'balance': 0.0,
                'mode': 'Dashboard',
                'symbol': 'SOL/USDT',
            },
            'trades': [],
            'alerts': [],
            'system': {
                'status': 'initializing',
                'uptime': 0,
                'start_time': time.time(),
                'ws_connected': False,
                'exchange_connected': False,
                'error_message': '',
                'trading_mode': 'dashboard',
            },
        }

        # WebSocket 订阅者
        self._subscribers: Set[Callable] = set()
        self._subscriber_lock = threading.Lock()

        # 交易记录限制
        self._max_trades = 100
        self._max_alerts = 50

    def subscribe(self, callback: Callable) -> None:
        """添加 WebSocket 订阅者"""
        with self._subscriber_lock:
            self._subscribers.add(callback)
            logger.debug(f"WebSocket subscriber added, total: {len(self._subscribers)}")

    def unsubscribe(self, callback: Callable) -> None:
        """移除 WebSocket 订阅者"""
        with self._subscriber_lock:
            self._subscribers.discard(callback)
            logger.debug(f"WebSocket subscriber removed, total: {len(self._subscribers)}")

    def _notify_subscribers(self, event_type: str, data: Any) -> None:
        """通知所有订阅者"""
        with self._subscriber_lock:
            subscribers = list(self._subscribers)

        message = json.dumps({
            'type': event_type,
            'data': data,
            'timestamp': int(time.time() * 1000),
        })

        for callback in subscribers:
            try:
                callback(message)
            except Exception as e:
                logger.error(f"Subscriber notification error: {e}")

    # ==================== 市场数据更新 ====================

    def update_market(self, **kwargs) -> None:
        """更新市场数据"""
        with self._lock:
            self._data['market'].update(kwargs)
        self._notify_subscribers('market', self._data['market'])

    def update_price(self, price: float) -> None:
        """更新当前价格"""
        with self._lock:
            self._data['market']['price'] = price
        self._notify_subscribers('price', {'price': price})

    def update_orderbook(self, orderbook: Dict) -> None:
        """更新订单簿"""
        with self._lock:
            self._data['market']['orderbook'] = orderbook

    def update_kline(self, timeframe: str, kline: List) -> None:
        """更新K线数据"""
        key = f'kline_{timeframe}'
        with self._lock:
            self._data['market'][key] = kline

    # ==================== 策略状态更新 ====================

    def update_strategy(self, **kwargs) -> None:
        """更新策略状态"""
        with self._lock:
            self._data['strategy'].update(kwargs)
        self._notify_subscribers('strategy', self._data['strategy'])

    def update_analysis(self, analysis: Dict) -> None:
        """更新分析数据"""
        if not analysis:
            return

        strategy_update = {
            'adx': analysis.get('adx', 0.0),
            'macd': analysis.get('macd_histogram', 0.0),
            'reversal': analysis.get('reversal_factor', 0.0),
            'supertrend_5m': analysis.get('supertrend_direction', 0),
        }

        with self._lock:
            self._data['strategy'].update(strategy_update)

    # ==================== 持仓信息更新 ====================

    def update_position(self, position: Dict, unrealized_pnl: float = 0.0) -> None:
        """更新持仓信息"""
        with self._lock:
            self._data['position'].update({
                'size': position.get('size', 0.0),
                'entry_price': position.get('entry_price', 0.0),
                'sl': position.get('sl', 0.0),
                'tp': position.get('tp', 0.0),
                'entry_time': position.get('entry_time', 0),
                'leverage': position.get('leverage', 10.0),
                'unrealized_pnl': unrealized_pnl,
            })
        self._notify_subscribers('position', self._data['position'])

    # ==================== 账户信息更新 ====================

    def update_account(self, **kwargs) -> None:
        """更新账户信息"""
        with self._lock:
            self._data['account'].update(kwargs)
        self._notify_subscribers('account', self._data['account'])

    def update_balance(self, balance: float) -> None:
        """更新余额"""
        with self._lock:
            self._data['account']['balance'] = balance

    # ==================== 交易记录 ====================

    def add_trade(self, trade: Dict) -> None:
        """添加交易记录"""
        with self._lock:
            self._data['trades'].insert(0, trade)
            if len(self._data['trades']) > self._max_trades:
                self._data['trades'] = self._data['trades'][:self._max_trades]
        self._notify_subscribers('trade', trade)

    def log_entry(self, side: str, price: float, leverage: float, sl: float, tp: float, regime: str) -> None:
        """记录开仓"""
        trade = {
            'type': 'entry',
            'side': side,
            'price': price,
            'leverage': leverage,
            'sl': sl,
            'tp': tp,
            'regime': regime,
            'time': int(time.time() * 1000),
        }
        self.add_trade(trade)

    def log_exit(self, reason: str, price: float, pnl: float, fee: float, balance: float) -> None:
        """记录平仓"""
        trade = {
            'type': 'exit',
            'reason': reason,
            'price': price,
            'pnl': pnl,
            'fee': fee,
            'balance': balance,
            'time': int(time.time() * 1000),
        }
        self.add_trade(trade)

    # ==================== 告警 ====================

    def add_alert(self, alert_type: str, message: str, details: Optional[Dict] = None) -> None:
        """添加告警"""
        alert = {
            'type': alert_type,
            'message': message,
            'details': details or {},
            'time': int(time.time() * 1000),
        }
        with self._lock:
            self._data['alerts'].insert(0, alert)
            if len(self._data['alerts']) > self._max_alerts:
                self._data['alerts'] = self._data['alerts'][:self._max_alerts]
        self._notify_subscribers('alert', alert)

    # ==================== 系统状态 ====================

    def update_system(self, **kwargs) -> None:
        """更新系统状态"""
        with self._lock:
            self._data['system'].update(kwargs)
            self._data['system']['uptime'] = int(time.time() - self._data['system']['start_time'])
        self._notify_subscribers('system', self._data['system'])

    def set_status(self, status: str) -> None:
        """设置系统状态"""
        self.update_system(status=status)

    def set_ws_connected(self, connected: bool) -> None:
        """设置 WebSocket 连接状态"""
        self.update_system(ws_connected=connected)

    def set_trading_mode(self, mode: str) -> None:
        """设置交易模式（dashboard / paper / live）"""
        self.update_system(trading_mode=mode)

    # ==================== 数据获取 ====================

    def get_snapshot(self) -> Dict[str, Any]:
        """获取完整快照"""
        with self._lock:
            snapshot = {
                'market': self._data['market'].copy(),
                'strategy': self._data['strategy'].copy(),
                'position': self._data['position'].copy(),
                'account': self._data['account'].copy(),
                'trades': self._data['trades'][:20],  # 最近20条
                'alerts': self._data['alerts'][:10],   # 最近10条
                'system': self._data['system'].copy(),
            }
        return snapshot

    def get_market(self) -> Dict[str, Any]:
        """获取市场数据"""
        with self._lock:
            return self._data['market'].copy()

    def get_strategy(self) -> Dict[str, Any]:
        """获取策略状态"""
        with self._lock:
            return self._data['strategy'].copy()

    def get_position(self) -> Dict[str, Any]:
        """获取持仓信息"""
        with self._lock:
            return self._data['position'].copy()

    def get_trades(self, limit: int = 50) -> List[Dict]:
        """获取交易历史"""
        with self._lock:
            return self._data['trades'][:limit]

    def get_alerts(self, limit: int = 20) -> List[Dict]:
        """获取告警历史"""
        with self._lock:
            return self._data['alerts'][:limit]

    def get_system(self) -> Dict[str, Any]:
        """获取系统状态"""
        with self._lock:
            return self._data['system'].copy()
