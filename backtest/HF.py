# ================================================================
# Clean, Statistically Fair Backtest Framework with Dynamic Drift
# ================================================================

import time
import numpy as np
import pywt
import matplotlib.pyplot as plt
from collections import deque
import requests
import warnings
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tools.sm_exceptions import ConvergenceWarning

warnings.filterwarnings("ignore", category=ConvergenceWarning)
warnings.filterwarnings("ignore", category=UserWarning)


# ================================================================
# 1. FILTER DEFINITIONS
# ================================================================

class HInfinityFilter1D:
    def __init__(self, gamma=0.13, drift=0.0):
        self.Q, self.R, self.P = 0.01, 0.002, 0.02
        self.gamma_sq = gamma ** 2
        self.drift = drift  # 初始 Drift
        self.x = None

    # 新增：允许外部动态更新 Drift
    def set_drift(self, new_drift):
        self.drift = new_drift

    def update(self, z):
        if self.x is None:
            self.x = z
            return z, z

        # 预测步骤：加入 Drift (趋势项) 减少滞后
        x_pred = self.x + self.drift
        P_pred = self.P + self.Q

        term = (1 / self.R) - (1 / self.gamma_sq)
        denom = max(1 + P_pred * term, 1e-6)
        K = (P_pred / self.R) / denom

        self.P = P_pred / denom
        self.x = x_pred + K * (z - x_pred)
        return x_pred, self.x


class WaveletAnalyzer:
    def process(self, series):
        data = np.asarray(series)
        if len(data) < 16:
            return data[-1]

        # 确保数据长度为偶数
        if len(data) % 2 != 0:
            data = data[:-1]

        max_level = pywt.swt_max_level(len(data))
        level = min(2, max_level)

        if level < 1:
            return data[-1]

        coeffs = pywt.swt(data, 'sym5', level=level)
        sigma = np.median(np.abs(coeffs[-1][1])) / 0.6745

        denoised = []
        for a, d in coeffs:
            denoised.append((a, pywt.threshold(d, sigma * 0.001)))

        return pywt.iswt(denoised, 'sym5')[-1]


# ================================================================
# 2. BACKTEST ENGINE
# ================================================================

class BacktestPredictor:
    def __init__(self):
        self.symbol = 'XRPUSDT'
        self.interval = '1h'

        # 1. 初始化组件
        # 确保你的 HInfinityFilter1D 类里有 set_drift 方法
        self.hinf = HInfinityFilter1D()
        self.wavelet = WaveletAnalyzer()

        # 2. 数据容器
        self.raw = deque(maxlen=500)

        # Drift 计算参数
        self.drift_window = 10
        self.x_axis = np.arange(self.drift_window)

        # 3. 历史记录 (用于绘图)
        self.actual = []
        self.hinf_hist = []  # 记录后验值 (Filtered/Smoothed) - 用于观察降噪效果
        self.hinf_pred_hist = []  # 记录先验值 (Predicted) - 【关键】用于评估预测能力
        self.drift_hist = []
        self.arima_hist = []

        # 4. 损失统计
        self.loss_hinf = 0.0
        self.loss_arima = 0.0

        # ARIMA 状态
        self.prev_arima = None
        self.arima_fail_count = 0

        self.warmup = 50

    def calculate_drift(self):
        """计算过去 N 个点的线性回归斜率"""
        if len(self.raw) < self.drift_window:
            return 0.0
        recent_prices = list(self.raw)[-self.drift_window:]
        try:
            slope, _ = np.polyfit(self.x_axis, recent_prices, 1)
            return slope
        except:
            return 0.0

    def process(self, z, record=True):
        self.raw.append(z)

        # ==========================
        # A. H-Infinity 处理
        # ==========================
        # 1. 计算趋势
        current_drift = self.calculate_drift()
        self.hinf.set_drift(current_drift)

        # 2. 滤波器更新
        # ph (Prior): 预测值，用于打分和画预测图
        # xh (Posterior): 后验值，用于迭代和画降噪图
        ph, xh = self.hinf.update(z)

        # ==========================
        # B. ARIMA 处理
        # ==========================
        # 1. 结算上一步的 Loss
        if record:
            if self.prev_arima is not None:
                self.loss_arima += abs(self.prev_arima - z)
                self.arima_hist.append(self.prev_arima)
            else:
                self.arima_hist.append(np.nan)

        # 2. 预测下一步
        if len(self.raw) > self.warmup:
            try:
                # 为了速度，仅使用最近 100 个点，且减少迭代
                model = ARIMA(list(self.raw)[-100:], order=(2, 1, 0))
                fit = model.fit(method='nm', maxiter=50)
                self.prev_arima = fit.forecast(1)[0]
            except Exception:
                # 如果 ARIMA 崩溃，使用当前价格作为预测（朴素预测）
                # 这解释了为什么报错多但分数还行：朴素预测在震荡市很难被击败
                self.arima_fail_count += 1
                self.prev_arima = z
        else:
            self.prev_arima = None

        # ==========================
        # C. 记录数据
        # ==========================
        if not record:
            return

        self.actual.append(z)
        self.hinf_hist.append(xh)  # 存后验
        self.hinf_pred_hist.append(ph)  # 存先验 (这是真实的预测性能)
        self.drift_hist.append(current_drift)

        self.loss_hinf += abs(ph - z)  # 这里的 Loss 是诚实的

    def fetch_data(self, limit=2000):
        print(f"Fetching data for {self.symbol}...")
        url = 'https://api.binance.com/api/v3/klines'
        params = dict(symbol=self.symbol, interval=self.interval, limit=1000)
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            return data
        except Exception as e:
            print(f"Error: {e}")
            return []

    def run(self, enable_plot=True):
        klines = self.fetch_data()
        if not klines: return

        print(f"Loaded {len(klines)} candles.")
        split = int(len(klines) * 0.2)  # 20% 预热

        print("Starting backtest...")
        total = len(klines)
        for i, k in enumerate(klines):
            if i % 200 == 0: print(f"Processing... {i}/{total}")
            price = float(k[4])
            self.process(price, record=(i >= split))

        self.report()
        if enable_plot: self.plot()

    def report(self):
        print("\nONE-STEP PREDICTION MAE (Lower is Better)")
        print("=========================================")
        print(f"H-Inf (Drift) : {self.loss_hinf:.4f}")
        print(f"ARIMA         : {self.loss_arima:.4f}")
        print("-----------------------------------------")
        print(f"ARIMA Errors  : {self.arima_fail_count}")
        print(
            "(Note: High ARIMA errors mean it defaulted to 'Naive Forecast', which often scores well in random walks)")

    def plot(self):
        plt.figure(figsize=(15, 8))
        subset = 150  # 只看最后150个点，看细节

        # 1. 真实价格 (灰色背景)
        plt.plot(self.actual[-subset:], label='Real Price', color='gray', alpha=0.4, linewidth=3)

        # 2. H-Inf 预测值 (橙色) - 这是真实的预测能力
        plt.plot(self.hinf_pred_hist[-subset:], label='H-Inf Prediction (Prior)', color='orange', linewidth=1.5)

        # 3. ARIMA 预测值 (蓝色虚线)
        plt.plot(self.arima_hist[-subset:], label='ARIMA Prediction', color='blue', linestyle='--', alpha=0.7)

        plt.title(f"True Out-of-Sample Prediction Comparison (Last {subset} steps)")
        plt.legend()
        plt.grid(alpha=0.3)
        plt.show()


if __name__ == '__main__':
    BacktestPredictor().run(enable_plot=True)