import numpy as np
import pandas as pd
from river import compose, preprocessing
from river.forest import ARFClassifier as AdaptiveRandomForestClassifier
from colorama import Fore

from config import Config
from math_tools import MathUtils, HInfinityFilter1D, OnlineEGARCH, FractalAnalysis, OnlineBOCPD, WaveletAnalyzer, MomentumCalculator


# ==========================================
# 1. 盘口分析器
# ==========================================
class OrderBookAnalyzer:
    def analyze(self, orderbook):
        if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
            return 0.0, 0.0
        TARGET_DEPTH = 20
        bids = orderbook['bids'][:TARGET_DEPTH]
        asks = orderbook['asks'][:TARGET_DEPTH]
        if not bids or not asks: return 0.0, 0.0
        w_bid_vol = sum(o[1] * (TARGET_DEPTH - i) / TARGET_DEPTH for i, o in enumerate(bids))
        w_ask_vol = sum(o[1] * (TARGET_DEPTH - i) / TARGET_DEPTH for i, o in enumerate(asks))
        total_vol = w_bid_vol + w_ask_vol + 1e-9
        obi = (w_bid_vol - w_ask_vol) / total_vol
        mid_price = (bids[0][0] + asks[0][0]) / 2
        spread_pct = (asks[0][0] - bids[0][0]) / mid_price
        return obi, spread_pct


# ==========================================
# 2. 随机森林分类器 - 负责机器学习功能
# ==========================================
class RandomForestClassifier:
    def __init__(self):
        self.hf = HInfinityFilter1D(gamma=0.03)
        self.egarch, self.bocpd, self.fractal, self.wavelet = OnlineEGARCH(), OnlineBOCPD(), FractalAnalysis(), WaveletAnalyzer()
        self.momentum_calc = MomentumCalculator()
        self.rf_model = compose.Pipeline(
            preprocessing.StandardScaler(),
            AdaptiveRandomForestClassifier(n_models=10, seed=42)
        )
        self.prev_features = None
        self.history = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        self.last_price = 0.0

    def ingest_candle(self, item):
        # item 格式: [timestamp, open, high, low, close, volume]
        row = pd.DataFrame([{'timestamp': item[0], 'open': float(item[1]), 'high': float(item[2]),
                             'low': float(item[3]), 'close': float(item[4]), 'volume': float(item[5])}])
        if self.history.empty:
            self.history = row
        else:
            # 如果时间戳相同，更新最后一行（WS推送实时变动）
            if self.history.iloc[-1]['timestamp'] == item[0]:
                self.history.iloc[-1] = row.iloc[0]
            # 如果是新时间戳，追加
            elif item[0] > self.history.iloc[-1]['timestamp']:
                self.history = pd.concat([self.history, row], ignore_index=True)

        self.history = self.history.iloc[-100:]  # 保持滑动窗口

    def extract_features(self):
        df = self.history
        if len(df) < 30: return None
        curr_price = df['close'].iloc[-1]
        log_ret = np.log(curr_price / self.last_price) if self.last_price else 0.0
        self.last_price = curr_price

        # 仅当价格变化时更新复杂滤波器，避免重复计算
        eg_vol = self.egarch.update(log_ret)
        cp_prob = self.bocpd.update(log_ret)
        hurst = self.fractal.update(curr_price)

        hf_val = self.hf.update(curr_price)
        wav_res, wav_eng = self.wavelet.process(df['close'].values)

        rsi = MathUtils.calc_rsi(df['close']).iloc[-1]
        atr = MathUtils.calc_atr(df).iloc[-1]

        curr_tr = max(df['high'].iloc[-1] - df['low'].iloc[-1], abs(df['high'].iloc[-1] - df['close'].iloc[-2]))
        prev_atr = MathUtils.calc_atr(df.iloc[:-1]).iloc[-1]
        vol_expl = curr_tr / (prev_atr + 1e-9)
        range_pct = (df['high'].iloc[-1] - df['low'].iloc[-1]) / df['open'].iloc[-1]

        hf_diff = (curr_price - hf_val) / hf_val
        
        # 计算四个时间段的动量
        momentums = self.momentum_calc.update(curr_price)
        mom_5 = momentums.get('T_5', 0.0) if momentums.get('T_5') is not None else 0.0
        mom_10 = momentums.get('T_10', 0.0) if momentums.get('T_10') is not None else 0.0
        mom_25 = momentums.get('T_25', 0.0) if momentums.get('T_25') is not None else 0.0
        mom_50 = momentums.get('T_50', 0.0) if momentums.get('T_50') is not None else 0.0

        features = np.array([
            hf_diff,
            eg_vol * 1000,
            rsi / 100.0,
            cp_prob,
            hurst,
            vol_expl,
            range_pct,
            (curr_price - wav_res) / curr_price * 100,
            np.log1p(wav_eng),
            mom_5,
            mom_10,
            mom_25,
            mom_50
        ]).reshape(1, -1)

        return {
            'features': features, 'price': curr_price, 'atr': atr, 'rsi': rsi,
            'vol_explosion': vol_expl, 'hurst': hurst, 'cp_prob': cp_prob,
            'hf_diff': hf_diff, 'wavelet_energy': wav_eng,
            'mom_5': mom_5, 'mom_10': mom_10, 'mom_25': mom_25, 'mom_50': mom_50,
            'range_pct': range_pct
        }

    def train(self, features, label):
        curr_x = {f"f{i}": v for i, v in enumerate(features.flatten())}
        if self.prev_features:
            self.rf_model.learn_one(self.prev_features, label)
        self.prev_features = curr_x

    def predict(self, features):
        x = {f"f{i}": v for i, v in enumerate(features.flatten())}
        probs = self.rf_model.predict_proba_one(x)
        if not probs: return 0, 0.0
        return (1, probs.get(1, 0.0)) if probs.get(1, 0.0) > probs.get(-1, 0.0) else (-1, probs.get(-1, 0.0))


# ==========================================
# 3. 状态机 - 负责市场状态判断和交易信号生成
# ==========================================
class StateMachine:
    def __init__(self):
        self.state, self.color = "INIT", Fore.WHITE
        self.ob_analyzer = OrderBookAnalyzer()

    def determine_regime(self, range_pct, vol_expl, hurst, cp_prob):
        prev = self.state
        if range_pct < 0.0015:
            self.state, self.color = "💤 NOISE", Fore.WHITE
        elif vol_expl > 1.5 or (vol_expl > 1.05 and cp_prob > 0.25):
            self.state, self.color = "💥 BREAKOUT", Fore.MAGENTA
        elif hurst > 0.55:
            if prev == "🚀 TREND" and cp_prob > 0.5:
                self.state, self.color = "🦀 RANGE", Fore.YELLOW
            else:
                self.state, self.color = "🚀 TREND", Fore.CYAN
        else:
            self.state, self.color = "🦀 RANGE", Fore.YELLOW
        return self.state, self.color

    def get_entry_signal(self, analysis_data, current_price):
        """
        根据当前市场状态和指标计算交易信号
        返回: (signal, leverage)
        signal: 1 (Buy), -1 (Sell), 0 (None)
        """
        # 获取订单簿分析（如果已计算则使用已有值，否则计算）
        if 'obi' in analysis_data and 'spread_pct' in analysis_data:
            obi = analysis_data['obi']
            spread_pct = analysis_data['spread_pct']
        else:
            obi, spread_pct = self.ob_analyzer.analyze(analysis_data.get('orderbook', {}))
        
        features = analysis_data['features']
        ai_dir, ai_conf = analysis_data['ai_prediction']

        sig = 0
        lev = Config.MIN_LEVERAGE
        regime = self.state

        # 1. 基础过滤 (Spread & ATR)
        if spread_pct > Config.MAX_SPREAD_PCT:
            return 0, lev
        if analysis_data['atr'] < current_price * Config.MIN_ATR_PCT:
            return 0, lev

        # 2. 策略核心逻辑
        if regime == "🦀 RANGE":
            # 震荡策略: RSI 反转
            if analysis_data['rsi'] > 70 and ai_dir != 1:
                sig = -1
            elif analysis_data['rsi'] < 30 and ai_dir != -1:
                sig = 1
            lev = 15  # 激进震荡杠杆

        elif regime == "🚀 TREND":
            # 趋势策略: H-inf滤波 + AI方向 + OBI盘口
            filt = 1 if analysis_data['hf_diff'] > 0 else -1

            # 顺势做多
            if filt == 1 and ai_dir == 1 and obi >= Config.OBI_THRESHOLD_TREND:
                sig = 1
            # 顺势做空
            elif filt == -1 and ai_dir == -1 and obi <= -Config.OBI_THRESHOLD_TREND:
                sig = -1
            lev = 20  # 趋势跟随杠杆

        elif regime == "💥 BREAKOUT":
            # 突破策略: 高AI置信度 + OBI 确认
            if ai_conf > 0.5:
                if obi > Config.OBI_THRESHOLD_BREAKOUT:
                    sig = 1
                elif obi < -Config.OBI_THRESHOLD_BREAKOUT:
                    sig = -1
                lev = Config.MAX_LEVERAGE

        return sig, lev


# ==========================================
# 4. 策略大脑 - 协调随机森林和状态机
# ==========================================
class StrategyBrain:
    def __init__(self):
        self.rf_classifier = RandomForestClassifier()
        self.state_machine = StateMachine()
        self.state = self.state_machine.state
        self.color = self.state_machine.color

    def ingest_candle(self, item):
        self.rf_classifier.ingest_candle(item)

    def analyze(self, orderbook=None):
        # 提取特征
        feature_data = self.rf_classifier.extract_features()
        if not feature_data:
            return None
            
        # 添加订单簿数据
        feature_data['orderbook'] = orderbook
        
        # 分析订单簿获取OBI和spread_pct
        obi, spread_pct = self.state_machine.ob_analyzer.analyze(orderbook)
        feature_data['obi'] = obi
        feature_data['spread_pct'] = spread_pct
        
        # 确定市场状态
        self.state, self.color = self.state_machine.determine_regime(
            feature_data['range_pct'], 
            feature_data['vol_explosion'], 
            feature_data['hurst'], 
            feature_data['cp_prob']
        )
        
        # AI预测
        ai_dir, ai_conf = self.rf_classifier.predict(feature_data['features'])
        feature_data['ai_prediction'] = (ai_dir, ai_conf)
        
        return feature_data

    def train_ai(self, features, label):
        self.rf_classifier.train(features, label)

    def get_entry_signal(self, analysis_data, current_price):
        return self.state_machine.get_entry_signal(analysis_data, current_price)