import math
import numpy as np
from scipy.stats import t as student_t
import pywt


class MultivariateHInfinityFilter:
    def __init__(self, n_features, gamma=0.49, q_base=0.00001, r_base=1e-3, p_init=0.1):
        self.n = n_features
        self.I = np.eye(self.n)
        self.q_base = q_base
        self.x = np.zeros((self.n, 1))
        self.P = np.eye(self.n) * p_init
        self.R = np.array([[r_base]])
        self.Q = np.eye(self.n) * q_base
        self.gamma_sq = gamma ** 2

    def predict(self, features):
        H = np.array(features).reshape(1, -1)
        pred = H @ self.x
        return pred[0, 0]

    def update(self, prev_features, actual_return, cp_prob=0.0):
        y = np.array([[actual_return]])
        H = np.array(prev_features).reshape(1, -1)
        # 动态 Q
        dynamic_scale = 1.0 + (cp_prob * 100.0)
        current_Q = self.Q * dynamic_scale

        x_pred = self.x
        P_pred = self.P + current_Q

        try:
            P_pred_inv = np.linalg.inv(P_pred)
            R_inv = np.linalg.inv(self.R)
            HT_Rinv_H = H.T @ R_inv @ H
            Gamma_term = self.I * (1.0 / (self.gamma_sq + 1e-9))
            P_new_inv = P_pred_inv + HT_Rinv_H - Gamma_term
            self.P = np.linalg.inv(P_new_inv)

            if np.any(np.diag(self.P) < 0): self.P = np.eye(self.n) * 0.1

            K = self.P @ H.T @ R_inv
            innovation = y - H @ x_pred
            self.x = x_pred + K @ innovation
        except np.linalg.LinAlgError:
            self.P *= 0.95
        return self.x.flatten()


class WaveletAnalyzer:
    def __init__(self, wavelet='sym5', level=1):
        self.wavelet, self.level, self.buffer = wavelet, level, []

    def process(self, price):
        self.buffer.append(price)
        if len(self.buffer) > 32: self.buffer.pop(0)
        if len(self.buffer) < 16: return price
        data = np.array(self.buffer)
        if len(data) % 2 != 0: data = np.pad(data, (0, 1), 'edge')
        try:
            coeffs = pywt.swt(data, self.wavelet, level=self.level)
            threshold = np.median(np.abs(coeffs[0][1])) / 0.6745 * 1.5
            new_coeffs = [(cA, pywt.threshold(cD, threshold, 'soft')) for cA, cD in coeffs]
            return pywt.iswt(new_coeffs, self.wavelet)[-2 if len(self.buffer) % 2 != 0 else -1]
        except:
            return price


class OnlineEGARCH:
    def __init__(self, decay=0.9, alpha=0.1, theta=-0.05):
        self.decay, self.alpha, self.theta = decay, alpha, theta
        self.log_var = 0.0
        self.initialized = False

    def update(self, ret):
        if not self.initialized:
            self.log_var = np.log(ret ** 2 + 1e-9)
            self.initialized = True
            return abs(ret)
        prev_vol = math.sqrt(math.exp(self.log_var))
        std_resid = ret / (prev_vol + 1e-9)
        new_log = self.decay * self.log_var + (self.alpha * (abs(std_resid) - 0.7979) + self.theta * std_resid)
        self.log_var = max(min(new_log, 5.0), -10.0)
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
        # Handle scalar input
        if np.isscalar(data_series):
            return float(data_series), 0.0
            
        # Convert to numpy array
        data = np.array(data_series)
        
        # Handle insufficient data
        if len(data) < 16: 
            return float(data[-1]) if len(data) > 0 else 0.0, 0.0
            
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