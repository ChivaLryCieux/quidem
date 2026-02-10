import math
import numpy as np
import pandas as pd


class MathUtils:
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


class BollingerBands:
    """布林带指标 (20周期, 2倍标准差)"""
    
    def __init__(self, period=20, std_mult=2.0):
        self.period = period
        self.std_mult = std_mult
    
    def calculate(self, df):
        """
        计算布林带
        Returns: (middle, upper, lower, distance)
            middle: 中轨 (SMA)
            upper: 上轨
            lower: 下轨
            distance: 归一化距离 (close - middle) / (upper - lower)
        """
        close = df['close']
        middle = close.rolling(window=self.period).mean()
        std = close.rolling(window=self.period).std()
        upper = middle + self.std_mult * std
        lower = middle - self.std_mult * std
        
        # 归一化距离: (close - middle) / (upper - lower)
        band_width = upper - lower
        distance = (close - middle) / band_width.replace(0, np.nan)
        distance = distance.fillna(0)
        
        return {
            'middle': middle.iloc[-1] if len(middle) > 0 else 0.0,
            'upper': upper.iloc[-1] if len(upper) > 0 else 0.0,
            'lower': lower.iloc[-1] if len(lower) > 0 else 0.0,
            'distance': distance.iloc[-1] if len(distance) > 0 else 0.0,
            'middle_series': middle,
            'upper_series': upper,
            'lower_series': lower
        }
    
    def get_latest(self, df):
        """获取最新的布林带值"""
        result = self.calculate(df)
        return result['middle'], result['upper'], result['lower'], result['distance']


class SuperTrend:
    """SuperTrend指标 (ATR周期10, 乘数3)"""
    
    def __init__(self, atr_period=10, multiplier=3.0):
        self.atr_period = atr_period
        self.multiplier = multiplier
    
    def calculate(self, df):
        """
        计算SuperTrend
        Returns: (value, direction)
            value: SuperTrend值
            direction: 1=绿(多), -1=红(空)
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # 计算ATR
        atr = MathUtils.calc_atr(df, self.atr_period)
        
        # 计算基础上下轨
        hl2 = (high + low) / 2
        upper_basic = hl2 + self.multiplier * atr
        lower_basic = hl2 - self.multiplier * atr
        
        # 初始化SuperTrend
        supertrend = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(index=df.index, dtype=int)
        
        # 第一个值
        supertrend.iloc[0] = upper_basic.iloc[0]
        direction.iloc[0] = -1
        
        # 递归计算
        for i in range(1, len(df)):
            # 更新上轨
            if lower_basic.iloc[i] > supertrend.iloc[i-1] or close.iloc[i-1] < supertrend.iloc[i-1]:
                upper = upper_basic.iloc[i]
            else:
                upper = min(upper_basic.iloc[i], supertrend.iloc[i-1])
            
            # 更新下轨
            if upper_basic.iloc[i] < supertrend.iloc[i-1] or close.iloc[i-1] > supertrend.iloc[i-1]:
                lower = lower_basic.iloc[i]
            else:
                lower = max(lower_basic.iloc[i], supertrend.iloc[i-1])
            
            # 判断方向和SuperTrend值
            if close.iloc[i] > supertrend.iloc[i-1]:
                supertrend.iloc[i] = lower
                direction.iloc[i] = 1  # 绿色(多)
            else:
                supertrend.iloc[i] = upper
                direction.iloc[i] = -1  # 红色(空)
        
        return {
            'value': supertrend.iloc[-1] if len(supertrend) > 0 else 0.0,
            'direction': direction.iloc[-1] if len(direction) > 0 else 0,
            'value_series': supertrend,
            'direction_series': direction
        }
    
    def get_latest(self, df):
        """获取最新的SuperTrend值和方向"""
        result = self.calculate(df)
        return result['value'], result['direction']


class MACDCalculator:
    """MACD指标 (12, 26, 9)"""
    
    def __init__(self, fast=12, slow=26, signal=9):
        self.fast = fast
        self.slow = slow
        self.signal = signal
    
    def calculate(self, df):
        """
        计算MACD
        Returns: (macd, signal, histogram, normalized)
            macd: MACD线 (快线-慢线)
            signal: 信号线
            histogram: 柱状图
            normalized: 归一化MACD (MACD/Close)
        """
        close = df['close']
        
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=self.signal, adjust=False).mean()
        histogram = macd - signal
        
        # 归一化: MACD / Close
        normalized = macd / close.replace(0, np.nan)
        normalized = normalized.fillna(0)
        
        return {
            'macd': macd.iloc[-1] if len(macd) > 0 else 0.0,
            'signal': signal.iloc[-1] if len(signal) > 0 else 0.0,
            'histogram': histogram.iloc[-1] if len(histogram) > 0 else 0.0,
            'normalized': normalized.iloc[-1] if len(normalized) > 0 else 0.0,
            'macd_series': macd,
            'signal_series': signal
        }
    
    def get_latest(self, df):
        """获取最新的MACD值"""
        result = self.calculate(df)
        return result['macd'], result['signal'], result['histogram'], result['normalized']


class KDJCalculator:
    """KDJ指标 (9, 3, 3)"""
    
    def __init__(self, k_period=9, d_period=3, j_smooth=3):
        self.k_period = k_period
        self.d_period = d_period
        self.j_smooth = j_smooth
    
    def calculate(self, df):
        """
        计算KDJ
        Returns: (k, d, j, k_minus_d, golden_cross, death_cross)
            k: K值
            d: D值
            j: J值
            k_minus_d: K-D差值
            golden_cross: 是否金叉 (K上穿D)
            death_cross: 是否死叉 (K下穿D)
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # 计算RSV (Raw Stochastic Value)
        lowest_low = low.rolling(window=self.k_period).min()
        highest_high = high.rolling(window=self.k_period).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-9) * 100
        
        # 计算K值 (RSV的EMA)
        k = rsv.ewm(com=self.d_period - 1, adjust=False).mean()
        
        # 计算D值 (K的EMA)
        d = k.ewm(com=self.j_smooth - 1, adjust=False).mean()
        
        # 计算J值
        j = 3 * k - 2 * d
        
        # K-D差值
        k_minus_d = k - d
        
        # 金叉/死叉判断
        golden_cross = False
        death_cross = False
        if len(k) >= 2 and len(d) >= 2:
            # 金叉: K从下往上穿过D
            if k.iloc[-2] < d.iloc[-2] and k.iloc[-1] > d.iloc[-1]:
                golden_cross = True
            # 死叉: K从上往下穿过D
            if k.iloc[-2] > d.iloc[-2] and k.iloc[-1] < d.iloc[-1]:
                death_cross = True
        
        return {
            'k': k.iloc[-1] if len(k) > 0 else 50.0,
            'd': d.iloc[-1] if len(d) > 0 else 50.0,
            'j': j.iloc[-1] if len(j) > 0 else 50.0,
            'k_minus_d': k_minus_d.iloc[-1] if len(k_minus_d) > 0 else 0.0,
            'golden_cross': golden_cross,
            'death_cross': death_cross,
            'k_series': k,
            'd_series': d
        }
    
    def get_latest(self, df):
        """获取最新的KDJ值"""
        result = self.calculate(df)
        return result['k'], result['d'], result['j'], result['k_minus_d'], result['golden_cross'], result['death_cross']


class ADXCalculator:
    """ADX指标 (Average Directional Index)
    
    用于判断趋势强度：
    - ADX > 25: 强趋势 → 适合趋势跟随
    - ADX 20-25: 弱趋势 → 谨慎交易
    - ADX < 20: 无趋势/震荡 → 禁止开仓
    """
    
    def __init__(self, period=14):
        self.period = period
    
    def calculate(self, df):
        """
        计算ADX (使用标准Wilder平滑)
        Returns: dict with adx, plus_di, minus_di, adx_rising
        """
        if len(df) < self.period * 2:
            return {
                'adx': 0.0, 'plus_di': 0.0, 'minus_di': 0.0,
                'adx_rising': False, 'adx_series': pd.Series(dtype=float),
                'plus_di_series': pd.Series(dtype=float),
                'minus_di_series': pd.Series(dtype=float)
            }
        
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        n = len(df)
        period = self.period
        
        # 计算 True Range, +DM, -DM
        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        
        for i in range(1, n):
            h_diff = high[i] - high[i-1]
            l_diff = low[i-1] - low[i]
            
            tr[i] = max(high[i] - low[i], 
                       abs(high[i] - close[i-1]), 
                       abs(low[i] - close[i-1]))
            
            if h_diff > l_diff and h_diff > 0:
                plus_dm[i] = h_diff
            if l_diff > h_diff and l_diff > 0:
                minus_dm[i] = l_diff
        
        # Wilder平滑 (初始值用简单求和，之后递推)
        atr_smooth = np.zeros(n)
        plus_dm_smooth = np.zeros(n)
        minus_dm_smooth = np.zeros(n)
        
        # 初始值: 前period个的简单求和
        atr_smooth[period] = np.sum(tr[1:period+1])
        plus_dm_smooth[period] = np.sum(plus_dm[1:period+1])
        minus_dm_smooth[period] = np.sum(minus_dm[1:period+1])
        
        # Wilder递推
        for i in range(period + 1, n):
            atr_smooth[i] = atr_smooth[i-1] - atr_smooth[i-1] / period + tr[i]
            plus_dm_smooth[i] = plus_dm_smooth[i-1] - plus_dm_smooth[i-1] / period + plus_dm[i]
            minus_dm_smooth[i] = minus_dm_smooth[i-1] - minus_dm_smooth[i-1] / period + minus_dm[i]
        
        # +DI, -DI
        plus_di_arr = np.zeros(n)
        minus_di_arr = np.zeros(n)
        dx_arr = np.zeros(n)
        
        for i in range(period, n):
            if atr_smooth[i] > 0:
                plus_di_arr[i] = 100 * plus_dm_smooth[i] / atr_smooth[i]
                minus_di_arr[i] = 100 * minus_dm_smooth[i] / atr_smooth[i]
            
            di_sum = plus_di_arr[i] + minus_di_arr[i]
            if di_sum > 0:
                dx_arr[i] = 100 * abs(plus_di_arr[i] - minus_di_arr[i]) / di_sum
        
        # ADX: DX的Wilder平滑
        adx_arr = np.zeros(n)
        start = period * 2
        if start < n:
            adx_arr[start] = np.mean(dx_arr[period:start+1])
            for i in range(start + 1, n):
                adx_arr[i] = (adx_arr[i-1] * (period - 1) + dx_arr[i]) / period
        
        # 转为Series
        idx = df.index
        adx_series = pd.Series(adx_arr, index=idx)
        plus_di_series = pd.Series(plus_di_arr, index=idx)
        minus_di_series = pd.Series(minus_di_arr, index=idx)
        
        adx_val = float(adx_arr[-1])
        adx_rising = adx_arr[-1] > adx_arr[-3] if n >= 3 else False
        
        return {
            'adx': adx_val,
            'plus_di': float(plus_di_arr[-1]),
            'minus_di': float(minus_di_arr[-1]),
            'adx_rising': bool(adx_rising),
            'adx_series': adx_series,
            'plus_di_series': plus_di_series,
            'minus_di_series': minus_di_series
        }
    
    def get_latest(self, df):
        """获取最新ADX值"""
        result = self.calculate(df)
        return result['adx'], result['plus_di'], result['minus_di'], result['adx_rising']


class VWAPCalculator:
    """VWAP指标 (Volume Weighted Average Price)
    
    用于确认交易方向：
    - 价格 > VWAP: 买方主导 → 偏向做多
    - 价格 < VWAP: 卖方主导 → 偏向做空
    
    使用滚动窗口VWAP (适配5分钟K线，288根=1天)
    """
    
    def __init__(self, period=288):
        self.period = period  # 滚动窗口 (288根5分钟K线 = 1天)
    
    def calculate(self, df):
        """
        计算VWAP
        Returns: dict with vwap, distance (百分比), upper_band, lower_band
        """
        close = df['close']
        volume = df['volume']
        high = df['high']
        low = df['low']
        
        # 典型价格 = (High + Low + Close) / 3
        typical_price = (high + low + close) / 3
        
        # 使用min_periods=1避免NaN
        win = min(self.period, len(df))
        tp_vol = typical_price * volume
        rolling_tp_vol = tp_vol.rolling(window=win, min_periods=1).sum()
        rolling_vol = volume.rolling(window=win, min_periods=1).sum()
        
        vwap = rolling_tp_vol / (rolling_vol + 1e-9)
        
        # VWAP标准差带
        tp_diff_sq = ((typical_price - vwap) ** 2) * volume
        rolling_var = tp_diff_sq.rolling(window=win, min_periods=1).sum() / (rolling_vol + 1e-9)
        vwap_std = np.sqrt(rolling_var.clip(lower=0))
        
        upper_band = vwap + 2 * vwap_std
        lower_band = vwap - 2 * vwap_std
        
        # 百分比距离: (close - vwap) / vwap * 100
        # 正值=价格在VWAP上方, 负值=价格在VWAP下方
        distance = ((close - vwap) / (vwap + 1e-9)) * 100
        distance = distance.fillna(0).clip(-5, 5)
        
        vwap_val = float(vwap.iloc[-1]) if len(vwap) > 0 else float(close.iloc[-1])
        dist_val = float(distance.iloc[-1]) if len(distance) > 0 else 0.0
        
        # NaN保护
        if np.isnan(vwap_val): vwap_val = float(close.iloc[-1])
        if np.isnan(dist_val): dist_val = 0.0
        
        return {
            'vwap': vwap_val,
            'distance': dist_val,
            'upper_band': float(upper_band.iloc[-1]) if len(upper_band) > 0 else 0.0,
            'lower_band': float(lower_band.iloc[-1]) if len(lower_band) > 0 else 0.0,
            'vwap_series': vwap,
            'distance_series': distance
        }
    
    def get_latest(self, df):
        """获取最新的VWAP值"""
        result = self.calculate(df)
        return result['vwap'], result['distance']
