from core.config import Config

class PortfolioManager:
    def __init__(self, initial_balance=100.0):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.margin_used = 0.0
        self.unrealized_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.max_drawdown = 0.0
        self.peak_balance = initial_balance
        
    def update_balance(self, new_balance):
        """更新账户余额"""
        self.current_balance = new_balance
        
        # 更新最大回撤
        if new_balance > self.peak_balance:
            self.peak_balance = new_balance
        else:
            drawdown = (self.peak_balance - new_balance) / self.peak_balance
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown
                
    def update_margin(self, margin):
        """更新已用保证金"""
        self.margin_used = margin
        
    def update_unrealized_pnl(self, pnl):
        """更新未实现盈亏"""
        self.unrealized_pnl = pnl
        
    def record_trade(self, is_win):
        """记录交易结果"""
        self.total_trades += 1
        if is_win:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
            
    def get_win_rate(self):
        """获取胜率"""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades
        
    def get_total_pnl(self):
        """获取总盈亏"""
        return self.current_balance - self.initial_balance + self.unrealized_pnl
        
    def get_return_rate(self):
        """获取收益率"""
        return self.get_total_pnl() / self.initial_balance
        
    def get_margin_ratio(self):
        """获取保证金比例"""
        if self.current_balance == 0:
            return 0.0
        return self.margin_used / self.current_balance
        
    def is_risk_limit_exceeded(self):
        """检查是否超出风险限制"""
        # 检查最大回撤
        if self.max_drawdown > Config.MAX_DRAWDOWN:
            return True, f"最大回撤超限: {self.max_drawdown:.2%}"
            
        # 检查保证金比例
        if self.get_margin_ratio() > Config.MAX_MARGIN_RATIO:
            return True, f"保证金比例超限: {self.get_margin_ratio():.2%}"
            
        # 检查单日亏损
        daily_loss = self.initial_balance - self.current_balance
        if daily_loss > Config.MAX_DAILY_LOSS:
            return True, f"单日亏损超限: {daily_loss:.2f}"
            
        return False, ""
        
    def get_portfolio_summary(self):
        """获取投资组合摘要"""
        return {
            'initial_balance': self.initial_balance,
            'current_balance': self.current_balance,
            'margin_used': self.margin_used,
            'unrealized_pnl': self.unrealized_pnl,
            'total_pnl': self.get_total_pnl(),
            'return_rate': self.get_return_rate(),
            'win_rate': self.get_win_rate(),
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'max_drawdown': self.max_drawdown,
            'margin_ratio': self.get_margin_ratio()
        }