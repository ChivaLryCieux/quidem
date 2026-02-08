"""
策略分析器 - 纯技术指标高频版本

不依赖HMM模型，直接使用技术指标生成信号
目标：每天10-15次开仓，每次3-5%本金盈利
"""

import numpy as np
import pandas as pd
import logging
from colorama import Fore, Style

from core.config.settings import Config

logger = logging.getLogger(__name__)


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


class StateMachine:
    """纯技术指标信号生成器"""
    
    def __init__(self):
        self.state, self.color = "INIT", Fore.WHITE
        self.ob_analyzer = OrderBookAnalyzer()
        self.last_cluster = 99
        self.supertrend_15m_direction = 0
        
        # 交易冷却计数器
        self.bars_since_last_trade = 0

    def update_15m_supertrend(self, direction):
        self.supertrend_15m_direction = direction

    def get_entry_signal(self, analysis_data, current_price):
        """
        纯技术指标信号生成
        
        信号优先级：
        1. MACD柱状图翻转 (最敏感)
        2. 布林带边界 + KDJ超买超卖
        3. SuperTrend趋势跟随
        """
        if not analysis_data: 
            return 0, Config.DEFAULT_LEVERAGE

        self.bars_since_last_trade += 1
        
        # 冷却期：至少间隔2根K线
        if self.bars_since_last_trade < 2:
            return 0, Config.DEFAULT_LEVERAGE

        spread_pct = analysis_data.get('spread_pct', 0.0)
        sig, lev = 0, Config.DEFAULT_LEVERAGE

        # Spread 过滤 (实盘)
        if (not getattr(Config, "BACKTEST_MODE", False)) and spread_pct > Config.MAX_SPREAD_PCT:
            return 0, lev

        # 获取技术指标
        bb_distance = analysis_data.get('bb_distance', 0)
        kdj_k = analysis_data.get('kdj_k', 50)
        kdj_d = analysis_data.get('kdj_d', 50)
        macd = analysis_data.get('macd', 0)
        macd_signal = analysis_data.get('macd_signal', 0)
        macd_histogram = analysis_data.get('macd_histogram', 0)
        supertrend_5m = analysis_data.get('supertrend_direction', 0)
        supertrend_15m = self.supertrend_15m_direction
        
        # HMM状态 (仅用于日志，不影响信号)
        cluster_data = analysis_data.get('cluster', (99, 0.0))
        state_id = cluster_data[0]

        # ================================================================
        # 信号1: MACD柱状图方向 + SuperTrend确认 (最常用)
        # ================================================================
        # 做多: MACD柱正 + 5m趋势上 + 价格不在布林上轨
        if macd_histogram > 0 and supertrend_5m == 1 and bb_distance < 0.6:
            if kdj_k < 75:  # 不追高
                sig = 1
                logger.info(f"✅ MACD+ST做多 | Hist={macd_histogram:.5f}, ST={supertrend_5m}, BB={bb_distance:.2f}")
                self.bars_since_last_trade = 0
                return sig, lev
        
        # 做空: MACD柱负 + 5m趋势下 + 价格不在布林下轨
        if macd_histogram < 0 and supertrend_5m == -1 and bb_distance > -0.6:
            if kdj_k > 25:  # 不追低
                sig = -1
                logger.info(f"✅ MACD+ST做空 | Hist={macd_histogram:.5f}, ST={supertrend_5m}, BB={bb_distance:.2f}")
                self.bars_since_last_trade = 0
                return sig, lev

        # ================================================================
        # 信号2: 布林带边界 + KDJ极值 (均值回归)
        # ================================================================
        # 超卖做多: 价格在布林下轨 + KDJ超卖
        if bb_distance <= -0.6 and kdj_k < 25:
            sig = 1
            logger.info(f"✅ 超卖做多 | BB={bb_distance:.2f}, K={kdj_k:.1f}")
            self.bars_since_last_trade = 0
            return sig, lev
        
        # 超买做空: 价格在布林上轨 + KDJ超买
        if bb_distance >= 0.6 and kdj_k > 75:
            sig = -1
            logger.info(f"✅ 超买做空 | BB={bb_distance:.2f}, K={kdj_k:.1f}")
            self.bars_since_last_trade = 0
            return sig, lev

        # ================================================================
        # 信号3: 双趋势一致性 (趋势跟随)
        # ================================================================
        # 5m和15m趋势都向上 + 回调入场
        if supertrend_5m == 1 and supertrend_15m == 1:
            if bb_distance <= 0.2 and kdj_k < 60:
                sig = 1
                logger.info(f"✅ 双趋势做多 | ST5={supertrend_5m}, ST15={supertrend_15m}, BB={bb_distance:.2f}")
                self.bars_since_last_trade = 0
                return sig, lev
        
        # 5m和15m趋势都向下 + 反弹入场
        if supertrend_5m == -1 and supertrend_15m == -1:
            if bb_distance >= -0.2 and kdj_k > 40:
                sig = -1
                logger.info(f"✅ 双趋势做空 | ST5={supertrend_5m}, ST15={supertrend_15m}, BB={bb_distance:.2f}")
                self.bars_since_last_trade = 0
                return sig, lev

        # ================================================================
        # 信号4: 单独5m SuperTrend + 价格确认 (备选)
        # ================================================================
        # 只用5m趋势，条件更宽松
        if supertrend_5m == 1 and bb_distance < 0.3 and kdj_k < 55 and macd_histogram > -0.0001:
            sig = 1
            logger.info(f"✅ ST单趋势做多 | ST5={supertrend_5m}, BB={bb_distance:.2f}, K={kdj_k:.1f}")
            self.bars_since_last_trade = 0
            return sig, lev
        
        if supertrend_5m == -1 and bb_distance > -0.3 and kdj_k > 45 and macd_histogram < 0.0001:
            sig = -1
            logger.info(f"✅ ST单趋势做空 | ST5={supertrend_5m}, BB={bb_distance:.2f}, K={kdj_k:.1f}")
            self.bars_since_last_trade = 0
            return sig, lev

        return 0, lev


def check_forced_exit(state_id, position_size):
    """检查是否需要强制平仓"""
    if position_size == 0:
        return False, ""
    
    # State 0: 大跌 - 平掉多单
    if state_id == 0 and position_size > 0:
        return True, "State 0 大跌 - 平多单"
    
    # State 4: 大涨 - 平掉空单
    if state_id == 4 and position_size < 0:
        return True, "State 4 大涨 - 平空单"
    
    return False, ""
