"""
Raw indicators and calculators using only numpy/pandas.
Contains classes that use numpy and pandas but not advanced libraries like scipy or pywt.
"""
import math
import numpy as np
import pandas as pd


class MathUtils:
    """Technical indicator calculations using pandas."""

    @staticmethod
    def calc_atr(df, period=14):
        """Calculate Average True Range."""
        high, low, close = df['high'], df['low'], df['close']
        prev_close = close.shift()
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    @staticmethod
    def calc_rsi(series, period=14):
        """Calculate Relative Strength Index."""
        delta = series.diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ma_up = up.ewm(alpha=1 / period, adjust=False).mean()
        ma_down = down.ewm(alpha=1 / period, adjust=False).mean()
        rsi = 100 - (100 / (1 + ma_up / ma_down))
        return rsi


class MomentumCalculator:
    """Calculate momentum indicators across multiple time periods."""
    
    def __init__(self, periods=[1, 5, 15, 30, 50, 96]):
        self.periods = periods
        self.history = []
        self.max_len = max(periods) + 5

    def update(self, price):
        """Update with new price and return momentum array."""
        self.history.append(price)
        if len(self.history) > self.max_len:
            self.history.pop(0)
        return np.array(
            [np.log(self.history[-1] / self.history[-(p + 1)]) if len(self.history) > p else 0.0 
             for p in self.periods])

    def get_momentum(self, prices, T):
        """Calculate momentum for a specific period T."""
        if len(prices) <= T:
            return None
        momentum = prices[-1] / prices[-(T + 1)]
        return np.log(momentum)

    def calculate_all_momentums(self, prices):
        """Calculate all momentum periods and return as dict."""
        results = {}
        for T in self.periods:
            results[f"T_{T}"] = self.get_momentum(prices, T)
        return results


class RollingVolatilityCalculator:
    """Calculate rolling volatility across multiple time windows."""

    def __init__(self, periods=[5, 10, 25, 50]):
        self.periods = periods

    def update(self, price):
        """Placeholder for online updates."""
        return {}

    def calculate_all_volatilities(self, prices_list):
        """Calculate volatilities from price list."""
        results = {}
        # Data validation
        if not prices_list or len(prices_list) < 2:
            for w in self.periods:
                results[f"T_{w}"] = 0.0
            return results

        try:
            # Convert to numpy array and calculate log returns
            arr = np.array(prices_list, dtype=float)
            arr = np.maximum(arr, 1e-9)  # Avoid log(0)
            log_returns = np.diff(np.log(arr))

            # Calculate volatility for each window
            for w in self.periods:
                if len(log_returns) >= w:
                    window_slice = log_returns[-w:]
                    vol = np.std(window_slice)
                    results[f"T_{w}"] = vol
                else:
                    if len(log_returns) > 0:
                        results[f"T_{w}"] = np.std(log_returns)
                    else:
                        results[f"T_{w}"] = 0.0

        except Exception:
            for w in self.periods:
                results[f"T_{w}"] = 0.0

        return results

    def calculate_from_history(self, history_df):
        """Calculate volatilities from DataFrame."""
        if len(history_df) < max(self.periods) + 2:
            return {f"T_{t}": 0.0 for t in self.periods}

        log_returns = np.log(history_df['close'] / history_df['close'].shift(1)).fillna(0)

        vol_values = {}
        for T in self.periods:
            if len(log_returns) >= T:
                vol = log_returns.tail(T).std()
                if np.isnan(vol):
                    vol = 0.0
                vol_values[f"T_{T}"] = vol
            else:
                vol_values[f"T_{T}"] = 0.0

        return vol_values


class OnlineEGARCH:
    """Online EGARCH volatility estimator."""
    
    def __init__(self, decay=0.9, alpha=0.1, theta=-0.05):
        self.decay = decay
        self.alpha = alpha
        self.theta = theta
        self.log_var = 0.0
        self.initialized = False

    def update(self, ret):
        """Update volatility estimate with new return."""
        if not self.initialized:
            self.log_var = np.log(ret ** 2 + 1e-9)
            self.initialized = True
            return abs(ret)
        
        prev_vol = math.sqrt(math.exp(self.log_var))
        std_resid = ret / (prev_vol + 1e-9)
        new_log = (self.decay * self.log_var + 
                   (self.alpha * (abs(std_resid) - 0.7979) + self.theta * std_resid))
        self.log_var = max(min(new_log, 5.0), -10.0)
        return math.sqrt(math.exp(self.log_var))


class FractalAnalysis:
    """Hurst exponent estimation using rescaled range analysis."""
    
    def __init__(self, window_size=30):
        self.window = window_size
        self.data_buffer = []

    def update(self, price):
        """Update with new price and calculate Hurst exponent."""
        self.data_buffer.append(price)
        if len(self.data_buffer) > self.window:
            self.data_buffer.pop(0)
        if len(self.data_buffer) < self.window:
            return 0.5
        
        rets = np.diff(np.log(np.array(self.data_buffer)))
        if len(rets) < 2 or np.std(rets) == 0:
            return 0.5
        
        rs = ((np.max(np.cumsum(rets - np.mean(rets))) - 
               np.min(np.cumsum(rets - np.mean(rets)))) / 
              (np.std(rets) + 1e-9))
        return max(0.0, min(1.0, np.log(rs) / np.log(len(rets))))
