import numpy as np
from scipy.stats import t as student_t


class MomentumCalculator:
    def __init__(self, periods=[1, 5, 15, 30, 50, 96]):
        self.periods = periods
        self.history = []
        self.max_len = max(periods) + 5

    def update(self, price):
        self.history.append(price)
        if len(self.history) > self.max_len:
            self.history.pop(0)
        return np.array(
            [np.log(self.history[-1] / self.history[-(p + 1)]) if len(self.history) > p else 0.0 for p in self.periods])

    def get_momentum(self, prices, T):
        if len(prices) <= T:
            return None
        momentum = prices[-1] / prices[-(T + 1)]
        return np.log(momentum)

    def calculate_all_momentums(self, prices):
        results = {}
        for T in self.periods:
            results[f"T_{T}"] = self.get_momentum(prices, T)
        return results


class RollingVolatilityCalculator:
    def __init__(self, periods=[5, 10, 25, 50]):
        self.periods = periods

    def update(self, price):
        return {}

    def calculate_all_volatilities(self, prices_list):
        """
        专门处理从列表传入的价格数据
        计算不同窗口期(5, 10, 25, 50)的实际波动率
        """
        results = {}
        # 数据不足保护
        if not prices_list or len(prices_list) < 2:
            for w in self.periods:
                results[f"T_{w}"] = 0.0
            return results

        try:
            # 1. 列表转numpy数组，计算对数收益率
            arr = np.array(prices_list, dtype=float)
            # 避免log(0)或负数
            arr = np.maximum(arr, 1e-9)
            # diff(log(p)) 得到收益率序列
            log_returns = np.diff(np.log(arr))

            # 2. 遍历窗口计算标准差
            for w in self.periods:
                if len(log_returns) >= w:
                    # 取最后 w 个收益率
                    window_slice = log_returns[-w:]
                    vol = np.std(window_slice)
                    results[f"T_{w}"] = vol
                else:
                    # 如果数据不够长，尝试用现有的所有数据，或者返回0
                    if len(log_returns) > 0:
                        results[f"T_{w}"] = np.std(log_returns)
                    else:
                        results[f"T_{w}"] = 0.0

        except Exception as e:
            # 发生任何数学错误，返回0以防崩溃
            for w in self.periods:
                results[f"T_{w}"] = 0.0

        return results

    def calculate_from_history(self, history_df):
        """
        保留此方法，兼容DataFrame输入
        """
        if len(history_df) < max(self.periods) + 2:
            return {f"T_{t}": 0.0 for t in self.periods}

        log_returns = np.log(history_df['close'] / history_df['close'].shift(1)).fillna(0)

        vol_values = {}
        for T in self.periods:
            if len(log_returns) >= T:
                vol = log_returns.tail(T).std()
                if np.isnan(vol): vol = 0.0
                vol_values[f"T_{T}"] = vol
            else:
                vol_values[f"T_{T}"] = 0.0

        return vol_values


class FractalAnalysis:
    def __init__(self, window_size=30):
        self.window, self.data_buffer = window_size, []

    def update(self, price):
        self.data_buffer.append(price)
        if len(self.data_buffer) > self.window: self.data_buffer.pop(0)
        if len(self.data_buffer) < self.window: return 0.5
        rets = np.diff(np.log(np.array(self.data_buffer)))
        if len(rets) < 2 or np.std(rets) == 0: return 0.5
        rs = (np.max(np.cumsum(rets - np.mean(rets))) - np.min(np.cumsum(rets - np.mean(rets)))) / (np.std(rets) + 1e-9)
        return max(0.0, min(1.0, np.log(rs) / np.log(len(rets))))


class OnlineBOCPD:
    def __init__(self, hazard=1 / 100, max_lags=200):
        self.hazard, self.max_lags = hazard, max_lags
        self.R, self.alpha, self.beta, self.kappa, self.mu = np.array([1.0]), np.array([1.0]), np.array(
            [1e-4]), np.array([1.0]), np.array([0.0])

    def update(self, x):
        x = float(x)
        scale = np.sqrt(self.beta * (self.kappa + 1) / (self.alpha * self.kappa))
        pred_probs = student_t.pdf(x, 2 * self.alpha, loc=self.mu, scale=scale)
        growth_probs = pred_probs * self.R * (1 - self.hazard)
        cp_prob = np.sum(pred_probs * self.R * self.hazard)
        new_R = np.append(cp_prob, growth_probs)
        new_R /= np.sum(new_R) + 1e-12
        if len(new_R) > self.max_lags: new_R = new_R[:self.max_lags]; new_R /= np.sum(new_R) + 1e-12
        self.R = new_R
        new_alpha = np.append(1.0, self.alpha + 0.5)
        new_kappa = np.append(1.0, self.kappa + 1)
        new_mu = np.append(0.0, (self.kappa * self.mu + x) / (self.kappa + 1))
        new_beta = np.append(1e-4, self.beta + (self.kappa * (x - self.mu) ** 2) / (2 * (self.kappa + 1)))
        limit = len(self.R)
        self.alpha, self.kappa, self.mu, self.beta = new_alpha[:limit], new_kappa[:limit], new_mu[:limit], new_beta[:limit]
        
        # Return change point probability
        return float(cp_prob)