import math
import numpy as np
import pandas as pd


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