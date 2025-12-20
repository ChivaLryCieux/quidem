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


# 对数收益率的滚动标准差 ，不是严谨的已实现波动率
class RealizedVolatilityCalculator:
    def __init__(self, periods=[5, 10, 25, 50]):
        self.periods = periods
        self.price_history = []
        self.log_returns = []

    def update(self, price):
        self.price_history.append(price)
        max_period = max(self.periods)
        if len(self.price_history) > max_period + 1:  # 需要额外一个点计算收益率
            self.price_history.pop(0)
        
        # 计算对数收益率
        if len(self.price_history) >= 2:
            log_ret = np.log(self.price_history[-1] / self.price_history[-2])
            self.log_returns.append(log_ret)
            # 保持对数收益率历史长度与最大周期一致
            if len(self.log_returns) > max_period:
                self.log_returns.pop(0)
        
        volatility_values = {}
        
        for T in self.periods:
            if len(self.log_returns) >= T:
                # 使用对数收益率的滚动标准差计算已实现波动率
                volatility = np.std(self.log_returns[-T:])
                volatility_values[f"T_{T}"] = volatility
            else:
                volatility_values[f"T_{T}"] = None
        
        return volatility_values

    def get_volatility(self, prices, T):
        if len(prices) <= T:
            return None
        # 计算对数收益率
        log_returns = []
        for i in range(1, len(prices)):
            log_returns.append(np.log(prices[i] / prices[i-1]))
        
        if len(log_returns) < T:
            return None
            
        # 使用对数收益率的滚动标准差计算已实现波动率
        return np.std(log_returns[-T:])
    
    def calculate_all_volatilities(self, prices):
        results = {}
        for T in self.periods:
            results[f"T_{T}"] = self.get_volatility(prices, T)
        return results