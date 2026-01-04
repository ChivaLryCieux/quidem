import math
import numpy as np
import pandas as pd
import pywt
from scipy.stats import t as student_t


# ==========================================
# 数学与分析工具集：指标与特征
# ==========================================
class MathUtils:
    @staticmethod
    def calc_atr(df, period=14):
        high, low, close = df['high'], df['low'], df['close']
        prev_close = close.shift()
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    @staticmethod
    def calc_rsi(series, period=14):
        delta = series.diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ma_up = up.ewm(alpha=1 / period, adjust=False).mean()
        ma_down = down.ewm(alpha=1 / period, adjust=False).mean()
        rsi = 100 - (100 / (1 + ma_up / ma_down))
        return rsi


class HInfinityFilter1D:
    def __init__(self, gamma=0.13, process_noise=0.01, measurement_noise=0.002, estimated_error=0.02):
        self.Q, self.R, self.P, self.x = process_noise, measurement_noise, estimated_error, 0
        self.gamma_sq = gamma ** 2

    def update(self, z):
        if self.x == 0: self.x = z
        x_pred, P_pred = self.x, self.P + self.Q
        term = (1 / (self.R + 1e-9)) - (1 / (self.gamma_sq + 1e-9))
        denom = 1 + P_pred * term
        if denom <= 1e-6:
            self.P = P_pred;
            K = 0.0
        else:
            K = P_pred * (1 / (self.R + 1e-9)) / denom;
            self.P = P_pred / denom
        self.x = x_pred + K * (z - x_pred)
        return self.x


class OnlineEGARCH:
    def __init__(self, decay=0.75, alpha=0.05, theta=-0.05):
        self.decay, self.alpha, self.theta = decay, alpha, theta
        self.log_var, self.initialized = 0.0, False

    def update(self, ret):
        if not self.initialized: self.log_var = np.log(ret ** 2 + 1e-9); self.initialized = True; return abs(ret)
        prev_vol = math.sqrt(math.exp(self.log_var))
        std_resid = ret / (prev_vol + 1e-9)
        self.log_var = max(
            min(self.decay * self.log_var + (self.alpha * (abs(std_resid) - 0.7979) + self.theta * std_resid), 5), -10)
        return math.sqrt(math.exp(self.log_var))


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
        self.alpha, self.kappa, self.mu, self.beta = new_alpha[:limit], new_kappa[:limit], new_mu[:limit], new_beta[
                                                                                                           :limit]
        return self.R[0]


class WaveletAnalyzer:
    def __init__(self, wavelet='sym5', level=2):
        self.wavelet, self.level = wavelet, level

    def process(self, data_series):
        data = np.array(data_series)
        if len(data) < 16: return data[-1], 0.0
        mult = 2 ** self.level
        pad_len = mult - (len(data) % mult) if len(data) % mult != 0 else 0
        data_padded = np.pad(data, (0, pad_len), 'symmetric') if pad_len else data
        coeffs = pywt.swt(data_padded, self.wavelet, level=self.level)
        valid_idx = len(data_padded) - pad_len - 1
        high_freq_coeffs = coeffs[-1][1]
        sigma = np.median(np.abs(high_freq_coeffs)) / 0.6745
        threshold = sigma * 0.001
        denoised_coeffs = [(cA, pywt.threshold(cD, value=threshold, mode='soft')) for cA, cD in coeffs]
        denoised_series = pywt.iswt(denoised_coeffs, self.wavelet)[:len(data)]
        return denoised_series[-1], high_freq_coeffs[valid_idx] ** 2


class MomentumCalculator:
    def __init__(self, periods=[5, 10, 25, 50]):
        self.periods = periods
        self.price_history = []

    def update(self, price):
        self.price_history.append(price)
        max_period = max(self.periods)
        if len(self.price_history) > max_period:
            self.price_history.pop(0)

        momentum_values = {}
        current_price = price

        for T in self.periods:
            if len(self.price_history) >= T + 1:
                price_T_periods_ago = self.price_history[-(T + 1)]
                momentum = current_price / price_T_periods_ago
                # 取对数输出
                momentum_values[f"T_{T}"] = np.log(momentum)
            else:
                momentum_values[f"T_{T}"] = None

        return momentum_values

    def get_momentum(self, prices, T):
        if len(prices) <= T:
            return None
        momentum = prices[-1] / prices[-(T + 1)]
        # 取对数输出
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