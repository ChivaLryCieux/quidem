"""
市场状态检测器 (Regime Detector)

使用 Hidden Markov Model (HMM) 检测市场状态:
  State 0: 低波动震荡 (Ranging/Low Vol)
  State 1: 上升趋势 (Trending Up)
  State 2: 下降趋势 (Trending Down)
  State 3: 高波动震荡 (High Volatility/Choppy)

输入特征:
  - 对数收益率
  - 波动率 (rolling std)
  - 成交量变化率
  - ADX值

输出:
  - 最可能的状态序列
  - 各状态概率
  - 转移概率矩阵

用途:
  - 趋势行情 → 积极跟随
  - 震荡行情 → 均值回归或观望
  - 高波动 → 降低仓位/收紧止损
"""

import logging
import warnings
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 抑制hmmlearn的收敛警告
warnings.filterwarnings('ignore', category=DeprecationWarning)


class MarketRegime:
    """市场状态枚举"""
    RANGING_LOW = 0      # 低波动震荡
    TRENDING_UP = 1      # 上升趋势
    TRENDING_DOWN = 2    # 下降趋势
    HIGH_VOL = 3         # 高波动

    LABELS = {
        0: "🦀 低波动震荡",
        1: "📈 上升趋势",
        2: "📉 下降趋势",
        3: "🔥 高波动",
    }

    @classmethod
    def label(cls, state: int) -> str:
        return cls.LABELS.get(state, "❓ 未知")


class RegimeDetector:
    """基于HMM的市场状态检测器"""

    def __init__(self, n_states: int = 4, lookback: int = 100, retrain_interval: int = 50):
        self.n_states = n_states
        self.lookback = lookback
        self.retrain_interval = retrain_interval
        self.model = None
        self.current_state = -1
        self.state_probs = np.ones(n_states) / n_states
        self.bars_since_train = 0
        self.is_fitted = False
        self._feature_cache = []

    def _extract_features(self, df: pd.DataFrame) -> np.ndarray:
        """从K线DataFrame提取HMM输入特征"""
        if len(df) < 20:
            return np.array([])

        close = df['close'].values
        volume = df['volume'].values

        # 1. 对数收益率
        log_returns = np.diff(np.log(np.maximum(close, 1e-9)))

        # 2. 波动率 (20周期滚动标准差)
        vol = pd.Series(log_returns).rolling(window=20, min_periods=5).std().fillna(0).values

        # 3. 成交量变化率
        vol_change = np.diff(np.log(np.maximum(volume[1:], 1e-9)))
        vol_change = np.concatenate([[0], vol_change])

        # 4. 归一化ADX (从DataFrame获取或计算近似值)
        # 用收益率的绝对值作为趋势强度的代理
        trend_strength = np.abs(log_returns)

        # 对齐长度
        min_len = min(len(log_returns), len(vol), len(vol_change), len(trend_strength))
        features = np.column_stack([
            log_returns[-min_len:],
            vol[-min_len:],
            vol_change[-min_len:],
            trend_strength[-min_len:],
        ])

        # 标准化
        mean = np.nanmean(features, axis=0)
        std = np.nanstd(features, axis=0) + 1e-9
        features = (features - mean) / std

        # 处理NaN/Inf
        features = np.nan_to_num(features, nan=0.0, posinf=3.0, neginf=-3.0)

        return features

    def fit(self, df: pd.DataFrame) -> bool:
        """训练HMM模型"""
        try:
            from hmmlearn.hmm import GaussianHMM
        except ImportError:
            logger.warning("hmmlearn not installed, regime detection disabled")
            return False

        features = self._extract_features(df)
        if len(features) < 50:
            return False

        try:
            model = GaussianHMM(
                n_components=self.n_states,
                covariance_type='full',
                n_iter=100,
                random_state=42,
                tol=1e-4,
            )
            model.fit(features)
            self.model = model
            self.is_fitted = True
            self.bars_since_train = 0

            # 预测当前状态
            states = model.predict(features)
            self.current_state = int(states[-1])
            self.state_probs = model.predict_proba(features)[-1]

            logger.info(f"HMM fitted: {self.n_states} states, current={MarketRegime.label(self.current_state)}")
            return True

        except Exception as e:
            logger.debug(f"HMM fit failed: {e}")
            return False

    def update(self, df: pd.DataFrame) -> int:
        """更新状态检测

        Args:
            df: 包含close/volume列的DataFrame

        Returns:
            current_state: 当前市场状态 (0-3)
        """
        if not self.is_fitted or self.model is None:
            # 首次调用或模型未就绪，尝试训练
            if len(df) >= self.lookback:
                self.fit(df.iloc[-self.lookback:])
            return self.current_state

        self.bars_since_train += 1

        # 定期重新训练
        if self.bars_since_train >= self.retrain_interval:
            self.fit(df.iloc[-self.lookback:])

        # 在线预测
        features = self._extract_features(df.iloc[-30:])
        if len(features) == 0:
            return self.current_state

        try:
            states = self.model.predict(features)
            self.current_state = int(states[-1])
            self.state_probs = self.model.predict_proba(features)[-1]
        except Exception as e:
            logger.debug(f"HMM predict failed: {e}")

        return self.current_state

    def get_state_info(self) -> dict:
        """获取当前状态详情"""
        return {
            'state': self.current_state,
            'label': MarketRegime.label(self.current_state),
            'probs': self.state_probs.tolist() if self.state_probs is not None else [],
            'is_trending': self.current_state in (MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN),
            'is_ranging': self.current_state == MarketRegime.RANGING_LOW,
            'is_high_vol': self.current_state == MarketRegime.HIGH_VOL,
            'confidence': float(max(self.state_probs)) if self.state_probs is not None else 0.0,
        }

    def get_strategy_params(self) -> dict:
        """根据当前状态返回策略参数建议

        Returns:
            dict with strategy parameter adjustments
        """
        state = self.current_state

        if state == MarketRegime.TRENDING_UP:
            return {
                'mode': 'trend_follow',
                'direction_bias': 1,
                'position_scale': 1.2,      # 加大仓位
                'tp_multiplier': 1.3,        # 放宽止盈 (让利润奔跑)
                'sl_multiplier': 1.0,        # 正常止损
                'adx_threshold': 18,         # 降低ADX门槛 (更容易入场)
                'confluence_threshold': 0.85, # 降低共识阈值
            }
        elif state == MarketRegime.TRENDING_DOWN:
            return {
                'mode': 'trend_follow',
                'direction_bias': -1,
                'position_scale': 1.2,
                'tp_multiplier': 1.3,
                'sl_multiplier': 1.0,
                'adx_threshold': 18,
                'confluence_threshold': 0.85,
            }
        elif state == MarketRegime.HIGH_VOL:
            return {
                'mode': 'defensive',
                'direction_bias': 0,
                'position_scale': 0.5,       # 大幅减仓
                'tp_multiplier': 0.8,        # 收紧止盈 (快进快出)
                'sl_multiplier': 1.3,        # 放宽止损 (避免被洗)
                'adx_threshold': 30,         # 提高ADX门槛 (更严格)
                'confluence_threshold': 1.3,  # 提高共识阈值
            }
        else:  # RANGING_LOW
            return {
                'mode': 'mean_revert',
                'direction_bias': 0,
                'position_scale': 0.7,       # 适度减仓
                'tp_multiplier': 0.7,        # 收紧止盈 (小波段)
                'sl_multiplier': 0.8,        # 收紧止损
                'adx_threshold': 25,         # 提高门槛
                'confluence_threshold': 1.2,  # 提高共识阈值
            }
