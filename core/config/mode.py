"""
交易模式定义

三态模式：
- DASHBOARD: 看盘模式（仅行情/策略展示，不交易）
- PAPER:     模拟交易（paper order 记录，不调用真实 API 下单）
- LIVE:      实盘交易（调用真实交易所 API）

模式仅允许单向升级：DASHBOARD -> PAPER -> LIVE
"""

from enum import Enum


class TradingMode(str, Enum):
    """交易模式枚举"""

    DASHBOARD = "dashboard"
    PAPER = "paper"
    LIVE = "live"

    @property
    def label(self) -> str:
        """中文标签"""
        return {
            TradingMode.DASHBOARD: "看盘模式",
            TradingMode.PAPER: "模拟盘",
            TradingMode.LIVE: "实盘",
        }[self]

    @property
    def level(self) -> int:
        """模式等级，用于单向升级校验"""
        return {
            TradingMode.DASHBOARD: 0,
            TradingMode.PAPER: 1,
            TradingMode.LIVE: 2,
        }[self]


def can_switch(current: "TradingMode", target: "TradingMode") -> bool:
    """校验是否允许从 current 切换到 target（仅允许单向升级）"""
    if not isinstance(current, TradingMode):
        current = TradingMode(current)
    if not isinstance(target, TradingMode):
        target = TradingMode(target)
    return target.level > current.level


def parse_mode(value: str) -> TradingMode:
    """从字符串解析模式，无效时返回 DASHBOARD"""
    try:
        return TradingMode(value)
    except (ValueError, TypeError):
        return TradingMode.DASHBOARD
