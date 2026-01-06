import logging
import threading
import copy
from core.config.settings import Config

logger = logging.getLogger(__name__)


class PositionManager:
    def __init__(self):
        self.positions = {}
        self.max_positions = Config.MAX_POSITIONS
        # 兼容配置中可能没有定义 MAX_POSITION_SIZE 的情况
        self.max_position_size = getattr(Config, 'MAX_POSITION_SIZE', 10000.0)

        # [优化] 引入线程锁，保证多线程读写安全
        self._lock = threading.Lock()

    def add_position(self, symbol, position_data):
        """添加新仓位"""
        with self._lock:
            if len(self.positions) >= self.max_positions:
                return False, f"达到最大仓位数量限制 ({self.max_positions})"

            # [优化] 简单的参数校验
            size = position_data.get('size', 0)
            if abs(size) == 0:
                return False, "仓位大小不能为0"

            if abs(size) > self.max_position_size:
                return False, f"仓位大小 ({abs(size)}) 超过限制 ({self.max_position_size})"

            # 如果已存在，发出警告或覆盖（视策略而定，这里选择覆盖）
            if symbol in self.positions:
                logger.warning(f"覆盖已存在的仓位: {symbol}")

            self.positions[symbol] = position_data
            logger.info(f"仓位添加成功: {symbol} Size:{size}")
            return True, "仓位添加成功"

    def remove_position(self, symbol):
        """移除仓位"""
        with self._lock:
            if symbol in self.positions:
                del self.positions[symbol]
                return True, "仓位移除成功"
            return False, "仓位不存在"

    def update_position(self, symbol, updates):
        """更新仓位信息"""
        with self._lock:
            if symbol in self.positions:
                self.positions[symbol].update(updates)
                return True, "仓位更新成功"
            return False, "仓位不存在"

    def get_position(self, symbol):
        """获取特定仓位 (返回副本以防外部修改)"""
        with self._lock:
            pos = self.positions.get(symbol, None)
            if pos:
                return pos.copy()
            return None

    def get_all_positions(self):
        """获取所有仓位"""
        with self._lock:
            # [优化] 使用 deepcopy，防止外部修改返回的字典导致内部数据污染
            return copy.deepcopy(self.positions)

    def calculate_total_exposure(self):
        """
        计算总敞口 (Notional Value)
        优先计算: sum(abs(size) * entry_price)
        如果只有 size，则计算: sum(abs(size))
        """
        with self._lock:
            total_exposure = 0.0
            for pos in self.positions.values():
                size = abs(pos.get('size', 0.0))
                entry_price = pos.get('entry_price', 0.0)

                # 如果有入场价，计算名义价值 (USDT本位)
                if entry_price > 0:
                    total_exposure += size * entry_price
                else:
                    # 只有数量，只能加数量 (Fallback)
                    total_exposure += size

            return total_exposure

    def is_position_limit_reached(self):
        """检查是否达到仓位限制"""
        with self._lock:
            return len(self.positions) >= self.max_positions

    def clear_all_positions(self):
        """清空所有仓位"""
        with self._lock:
            self.positions.clear()
            logger.info("所有仓位记录已清空")
            return True, "所有仓位已清空"