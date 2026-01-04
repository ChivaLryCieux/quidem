from config import Config

class PositionManager:
    def __init__(self):
        self.positions = {}
        self.max_positions = Config.MAX_POSITIONS
        self.max_position_size = Config.MAX_POSITION_SIZE
        
    def add_position(self, symbol, position_data):
        """添加新仓位"""
        if len(self.positions) >= self.max_positions:
            return False, "达到最大仓位数量限制"
            
        if abs(position_data['size']) > self.max_position_size:
            return False, "仓位大小超过限制"
            
        self.positions[symbol] = position_data
        return True, "仓位添加成功"
        
    def remove_position(self, symbol):
        """移除仓位"""
        if symbol in self.positions:
            del self.positions[symbol]
            return True, "仓位移除成功"
        return False, "仓位不存在"
        
    def update_position(self, symbol, updates):
        """更新仓位信息"""
        if symbol in self.positions:
            self.positions[symbol].update(updates)
            return True, "仓位更新成功"
        return False, "仓位不存在"
        
    def get_position(self, symbol):
        """获取特定仓位"""
        return self.positions.get(symbol, None)
        
    def get_all_positions(self):
        """获取所有仓位"""
        return self.positions.copy()
        
    def calculate_total_exposure(self):
        """计算总敞口"""
        total_size = sum(abs(pos['size']) for pos in self.positions.values())
        return total_size
        
    def is_position_limit_reached(self):
        """检查是否达到仓位限制"""
        return len(self.positions) >= self.max_positions
        
    def clear_all_positions(self):
        """清空所有仓位"""
        self.positions.clear()
        return True, "所有仓位已清空"