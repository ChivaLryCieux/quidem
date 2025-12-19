import math
import numpy as np
import pandas as pd
import pywt
from scipy.stats import t as student_t

# ==========================================
# 数学与分析工具集
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