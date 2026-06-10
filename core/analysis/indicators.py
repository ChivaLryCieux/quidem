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
    """MACD指标 - 支持Appel黄金规则"""
    
    def __init__(self, fast=12, slow=26, signal=9):
        self.fast = fast
        self.slow = slow
        self.signal = signal
    
    def calculate(self, df):
        """
        计算MACD + Appel黄金规则信号
        
        Returns dict:
            macd/signal/histogram/normalized: 基础值
            golden_cross: 金叉 (MACD上穿信号线)
            death_cross: 死叉 (MACD下穿信号线)
            above_zero: MACD在零线上方
            hist_turning_up: 直方图从谷底回升 (连续2根下降后回升)
            hist_turning_down: 直方图从峰值回落 (连续2根上升后回落)
            bullish_divergence: 看涨背离 (价格新低但直方图未新低)
            bearish_divergence: 看跌背离 (价格新高但直方图未新高)
        """
        close = df['close']
        
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=self.signal, adjust=False).mean()
        histogram = macd - signal_line
        
        # 归一化: MACD / Close
        normalized = macd / close.replace(0, np.nan)
        normalized = normalized.fillna(0)
        
        n = len(macd)
        
        # === 信号线交叉 (金叉/死叉) ===
        golden_cross = False
        death_cross = False
        if n >= 2:
            prev_diff = float(macd.iloc[-2] - signal_line.iloc[-2])
            curr_diff = float(macd.iloc[-1] - signal_line.iloc[-1])
            golden_cross = (prev_diff <= 0 and curr_diff > 0)
            death_cross = (prev_diff >= 0 and curr_diff < 0)
        
        # === 零线位置 ===
        above_zero = float(macd.iloc[-1]) > 0 if n > 0 else False
        
        # === 直方图转折 ===
        hist_turning_up = False
        hist_turning_down = False
        if n >= 3:
            h1 = float(histogram.iloc[-3])
            h2 = float(histogram.iloc[-2])
            h3 = float(histogram.iloc[-1])
            # 转折向上: 前两根下降(h1>h2)，当前回升(h3>h2)
            hist_turning_up = (h1 > h2 and h3 > h2)
            # 转折向下: 前两根上升(h1<h2)，当前回落(h3<h2)
            hist_turning_down = (h1 < h2 and h3 < h2)
        
        # === 背离检测 (近20根K线) ===
        bullish_divergence = False
        bearish_divergence = False
        lookback = min(20, n - 1)
        if lookback >= 5:
            recent_close = close.iloc[-lookback:].values
            recent_hist = histogram.iloc[-lookback:].values
            
            # 看涨背离: 价格创近期新低，但直方图未创新低
            price_at_new_low = recent_close[-1] <= np.min(recent_close)
            hist_not_new_low = recent_hist[-1] > np.min(recent_hist[:-1])
            bullish_divergence = (price_at_new_low and hist_not_new_low)
            
            # 看跌背离: 价格创近期新高，但直方图未创新高
            price_at_new_high = recent_close[-1] >= np.max(recent_close)
            hist_not_new_high = recent_hist[-1] < np.max(recent_hist[:-1])
            bearish_divergence = (price_at_new_high and hist_not_new_high)
        
        return {
            'macd': float(macd.iloc[-1]) if n > 0 else 0.0,
            'signal': float(signal_line.iloc[-1]) if n > 0 else 0.0,
            'histogram': float(histogram.iloc[-1]) if n > 0 else 0.0,
            'normalized': float(normalized.iloc[-1]) if n > 0 else 0.0,
            'macd_series': macd,
            'signal_series': signal_line,
            # Appel 黄金规则信号
            'golden_cross': golden_cross,
            'death_cross': death_cross,
            'above_zero': above_zero,
            'hist_turning_up': hist_turning_up,
            'hist_turning_down': hist_turning_down,
            'bullish_divergence': bullish_divergence,
            'bearish_divergence': bearish_divergence,
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


# ================================================================
#  Phase 2: Advanced Indicators
# ================================================================


class IchimokuCloud:
    """一目均衡图 (Ichimoku Kinko Hyo)

    五线系统:
      - Tenkan-sen (转换线): 9周期 (high+low)/2
      - Kijun-sen (基准线): 26周期
      - Senkou Span A (先行A): (Tenkan+Kijun)/2 前移26
      - Senkou Span B (先行B): 52周期 前移26
      - Chikou Span (延迟线): close 后移26

    返回最新值 + 多空信号。
    """

    def __init__(self, tenkan=9, kijun=26, senkou_b=52, displacement=26):
        self.tenkan_p = tenkan
        self.kijun_p = kijun
        self.senkou_b_p = senkou_b
        self.disp = displacement

    @staticmethod
    def _mid_channel(high, low, period):
        hh = high.rolling(window=period).max()
        ll = low.rolling(window=period).min()
        return (hh + ll) / 2

    def calculate(self, df):
        high, low, close = df['high'], df['low'], df['close']

        tenkan = self._mid_channel(high, low, self.tenkan_p)
        kijun = self._mid_channel(high, low, self.kijun_p)
        span_a = ((tenkan + kijun) / 2).shift(self.disp)
        span_b = self._mid_channel(high, low, self.senkou_b_p).shift(self.disp)
        chikou = close.shift(-self.disp)

        n = len(close)
        tk = float(tenkan.iloc[-1]) if n >= self.tenkan_p else 0.0
        kj = float(kijun.iloc[-1]) if n >= self.kijun_p else 0.0
        sa = float(span_a.iloc[-1]) if n >= self.tenkan_p + self.disp else 0.0
        sb = float(span_b.iloc[-1]) if n >= self.senkou_b_p + self.disp else 0.0
        ck = float(chikou.iloc[-1]) if n > self.disp else 0.0
        price = float(close.iloc[-1])

        # 信号: 价格相对于云的位置
        cloud_top = max(sa, sb)
        cloud_bottom = min(sa, sb)
        if price > cloud_top:
            cloud_signal = 1  # 多
        elif price < cloud_bottom:
            cloud_signal = -1  # 空
        else:
            cloud_signal = 0  # 云中

        # TK交叉
        tk_cross = 0
        if n >= 2:
            prev_diff = float(tenkan.iloc[-2] - kijun.iloc[-2])
            curr_diff = float(tenkan.iloc[-1] - kijun.iloc[-1])
            if prev_diff <= 0 < curr_diff:
                tk_cross = 1  # 金叉
            elif prev_diff >= 0 > curr_diff:
                tk_cross = -1  # 死叉

        return {
            'tenkan': tk, 'kijun': kj,
            'span_a': sa, 'span_b': sb,
            'chikou': ck,
            'cloud_top': cloud_top, 'cloud_bottom': cloud_bottom,
            'cloud_signal': cloud_signal,
            'tk_cross': tk_cross,
        }


class StochasticRSI:
    """随机RSI (Stochastic RSI)

    对 RSI 应用随机指标公式，比原始 RSI 更敏感。
    周期: RSI(14) → Stoch(14,14) → K(3) → D(3)
    """

    def __init__(self, rsi_period=14, stoch_period=14, k_smooth=3, d_smooth=3):
        self.rsi_p = rsi_period
        self.stoch_p = stoch_period
        self.k_smooth = k_smooth
        self.d_smooth = d_smooth

    def calculate(self, df):
        close = df['close']
        rsi = MathUtils.calc_rsi(close, self.rsi_p)

        rsi_min = rsi.rolling(window=self.stoch_p).min()
        rsi_max = rsi.rolling(window=self.stoch_p).max()
        stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min + 1e-9) * 100

        k = stoch_rsi.ewm(com=self.k_smooth - 1, adjust=False).mean()
        d = k.ewm(com=self.d_smooth - 1, adjust=False).mean()

        n = len(k)
        k_val = float(k.iloc[-1]) if n > 0 else 50.0
        d_val = float(d.iloc[-1]) if n > 0 else 50.0

        golden = False
        death = False
        if n >= 2:
            if k.iloc[-2] < d.iloc[-2] and k.iloc[-1] > d.iloc[-1]:
                golden = True
            if k.iloc[-2] > d.iloc[-2] and k.iloc[-1] < d.iloc[-1]:
                death = True

        return {
            'stoch_rsi_k': k_val, 'stoch_rsi_d': d_val,
            'stoch_rsi_golden': golden, 'stoch_rsi_death': death,
        }


class OBVCalculator:
    """能量潮 (On Balance Volume)

    累积量: close>prev_close → +vol; close<prev_close → -vol
    用于检测量价背离。
    """

    def calculate(self, df):
        close = df['close']
        volume = df['volume']
        direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        obv = (volume * direction).cumsum()

        n = len(obv)
        obv_val = float(obv.iloc[-1]) if n > 0 else 0.0

        # OBV趋势: 用10周期线性回归斜率
        obv_trend = 0.0
        if n >= 10:
            y = obv.iloc[-10:].values
            x = np.arange(10, dtype=float)
            slope = np.polyfit(x, y, 1)[0]
            obv_trend = slope / (abs(obv_val) + 1e-9)

        # 量价背离: 价格新高但OBV未新高(看跌) / 价格新低但OBV未新低(看涨)
        bear_div = False
        bull_div = False
        if n >= 20:
            recent_close = close.iloc[-20:].values
            recent_obv = obv.iloc[-20:].values
            if recent_close[-1] >= np.max(recent_close) and recent_obv[-1] < np.max(recent_obv[:-1]):
                bear_div = True
            if recent_close[-1] <= np.min(recent_close) and recent_obv[-1] > np.min(recent_obv[:-1]):
                bull_div = True

        return {
            'obv': obv_val, 'obv_trend': obv_trend,
            'obv_bearish_div': bear_div, 'obv_bullish_div': bull_div,
        }


class CCICalculator:
    """商品通道指数 (CCI)

    CCI = (TP - SMA(TP)) / (0.015 * MeanDeviation)
    TP = (H+L+C) / 3
    超买 > +100, 超卖 < -100
    """

    def __init__(self, period=20):
        self.period = period

    def calculate(self, df):
        tp = (df['high'] + df['low'] + df['close']) / 3
        sma = tp.rolling(window=self.period).mean()
        mad = tp.rolling(window=self.period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        cci = (tp - sma) / (0.015 * mad + 1e-9)

        n = len(cci)
        cci_val = float(cci.iloc[-1]) if n >= self.period else 0.0
        cci_prev = float(cci.iloc[-2]) if n >= self.period + 1 else 0.0

        return {
            'cci': cci_val,
            'cci_prev': cci_prev,
            'cci_overbought': cci_val > 100,
            'cci_oversold': cci_val < -100,
        }


class WilliamsPercentR:
    """威廉指标 (Williams %R)

    %R = (HH - Close) / (HH - LL) * -100
    范围: -100 (最低) 到 0 (最高)
    超买: > -20, 超卖: < -80
    """

    def __init__(self, period=14):
        self.period = period

    def calculate(self, df):
        hh = df['high'].rolling(window=self.period).max()
        ll = df['low'].rolling(window=self.period).min()
        wr = (hh - df['close']) / (hh - ll + 1e-9) * -100

        n = len(wr)
        wr_val = float(wr.iloc[-1]) if n >= self.period else -50.0

        return {
            'williams_r': wr_val,
            'wr_overbought': wr_val > -20,
            'wr_oversold': wr_val < -80,
        }


class ParabolicSAR:
    """抛物线转向指标 (Parabolic SAR)

    趋势跟随止损系统。
    AF=0.02, step=0.02, max=0.2
    """

    def __init__(self, af_start=0.02, af_step=0.02, af_max=0.2):
        self.af_start = af_start
        self.af_step = af_step
        self.af_max = af_max

    def calculate(self, df):
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        n = len(df)

        if n < 2:
            return {'sar': close[-1] if n > 0 else 0.0, 'sar_direction': 0}

        sar = np.zeros(n)
        direction = np.zeros(n, dtype=int)  # 1=多, -1=空
        af = self.af_start
        ep = high[0]
        is_long = True

        sar[0] = low[0]
        direction[0] = 1

        for i in range(1, n):
            if is_long:
                sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
                sar[i] = min(sar[i], low[i - 1])
                if i >= 2:
                    sar[i] = min(sar[i], low[i - 2])

                if low[i] < sar[i]:
                    is_long = False
                    sar[i] = ep
                    ep = low[i]
                    af = self.af_start
                else:
                    if high[i] > ep:
                        ep = high[i]
                        af = min(af + self.af_step, self.af_max)
            else:
                sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
                sar[i] = max(sar[i], high[i - 1])
                if i >= 2:
                    sar[i] = max(sar[i], high[i - 2])

                if high[i] > sar[i]:
                    is_long = True
                    sar[i] = ep
                    ep = high[i]
                    af = self.af_start
                else:
                    if low[i] < ep:
                        ep = low[i]
                        af = min(af + self.af_step, self.af_max)

            direction[i] = 1 if is_long else -1

        return {
            'sar': float(sar[-1]),
            'sar_direction': int(direction[-1]),
        }


class VWMACalculator:
    """成交量加权移动平均 (VWMA)

    VWMA = SUM(close * volume, N) / SUM(volume, N)
    与SMA的区别在于考虑了成交量权重。
    """

    def __init__(self, period=20):
        self.period = period

    def calculate(self, df):
        cv = df['close'] * df['volume']
        vwma = cv.rolling(window=self.period).sum() / (df['volume'].rolling(window=self.period).sum() + 1e-9)
        sma = df['close'].rolling(window=self.period).mean()

        n = len(vwma)
        vwma_val = float(vwma.iloc[-1]) if n >= self.period else float(df['close'].iloc[-1])
        sma_val = float(sma.iloc[-1]) if n >= self.period else 0.0

        # VWMA > SMA → 买方主导 (正偏差)
        deviation = (vwma_val - sma_val) / (sma_val + 1e-9) * 100

        return {
            'vwma': vwma_val,
            'vwma_sma_deviation': deviation,
            'vwma_bullish': vwma_val > sma_val,
        }


class ChaikinMoneyFlow:
    """蔡金资金流量 (CMF)

    MF Multiplier = ((Close - Low) - (High - Close)) / (High - Low)
    MF Volume = MF Multiplier * Volume
    CMF = SUM(MFV, 20) / SUM(Volume, 20)
    范围: [-1, 1]
    > 0 → 买方主导, < 0 → 卖方主导
    """

    def __init__(self, period=20):
        self.period = period

    def calculate(self, df):
        hl = df['high'] - df['low']
        mf_mult = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (hl + 1e-9)
        mf_vol = mf_mult * df['volume']
        cmf = mf_vol.rolling(window=self.period).sum() / (df['volume'].rolling(window=self.period).sum() + 1e-9)

        n = len(cmf)
        cmf_val = float(cmf.iloc[-1]) if n >= self.period else 0.0

        return {
            'cmf': cmf_val,
            'cmf_bullish': cmf_val > 0.05,
            'cmf_bearish': cmf_val < -0.05,
        }


class VolumeProfile:
    """成交量分布 (Volume Profile)

    将价格区间分为N个bin，统计每个价格区间的累计成交量。
    返回POC(最大成交量价格)、VAH(价值区高值)、VAL(价值区低值)。
    """

    def __init__(self, bins=50, value_area_pct=0.70):
        self.bins = bins
        self.va_pct = value_area_pct

    def calculate(self, df):
        if len(df) < 10:
            price = float(df['close'].iloc[-1]) if len(df) > 0 else 0.0
            return {'poc': price, 'vah': price, 'val': price}

        prices = df['close'].values
        volumes = df['volume'].values
        price_min, price_max = prices.min(), prices.max()

        if price_max == price_min:
            return {'poc': price_min, 'vah': price_min, 'val': price_min}

        bin_edges = np.linspace(price_min, price_max, self.bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        vol_profile = np.zeros(self.bins)

        for p, v in zip(prices, volumes):
            idx = int((p - price_min) / (price_max - price_min) * (self.bins - 1))
            idx = max(0, min(self.bins - 1, idx))
            vol_profile[idx] += v

        # POC = 最大成交量价格
        poc_idx = np.argmax(vol_profile)
        poc = float(bin_centers[poc_idx])

        # Value Area: 从POC向两侧扩展，直到包含 va_pct 的总成交量
        total_vol = vol_profile.sum()
        target_vol = total_vol * self.va_pct
        accumulated = vol_profile[poc_idx]
        lo_idx, hi_idx = poc_idx, poc_idx

        while accumulated < target_vol and (lo_idx > 0 or hi_idx < self.bins - 1):
            expand_lo = vol_profile[lo_idx - 1] if lo_idx > 0 else 0
            expand_hi = vol_profile[hi_idx + 1] if hi_idx < self.bins - 1 else 0
            if expand_lo >= expand_hi and lo_idx > 0:
                lo_idx -= 1
                accumulated += vol_profile[lo_idx]
            elif hi_idx < self.bins - 1:
                hi_idx += 1
                accumulated += vol_profile[hi_idx]
            else:
                lo_idx -= 1
                accumulated += vol_profile[lo_idx]

        return {
            'poc': poc,
            'vah': float(bin_centers[hi_idx]),
            'val': float(bin_centers[lo_idx]),
        }
