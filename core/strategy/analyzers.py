"""
策略分析器 - ADX+VWAP三层过滤版本

三层过滤逻辑：
  Layer 1: ADX趋势强度过滤 → ADX < 20 禁止开仓
  Layer 2: VWAP方向确认 → 价格>VWAP偏多，价格<VWAP偏空
  Layer 3: 技术指标入场触发 → MACD/KDJ/SuperTrend确认
"""

import numpy as np
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
    """ADX+VWAP三层过滤策略"""
    
    # ADX阈值
    ADX_TREND = 20       # ADX > 20: 有趋势，可以开仓
    ADX_STRONG = 30      # ADX > 30: 强趋势，加大信心
    
    def __init__(self):
        self.state, self.color = "INIT", Fore.WHITE
        self.ob_analyzer = OrderBookAnalyzer()
        self.last_cluster = 99
        self.supertrend_15m_direction = 0
        self.bars_since_last_trade = 99  # 初始设为大值，允许首次交易

    def update_15m_supertrend(self, direction):
        self.supertrend_15m_direction = direction

    def get_entry_signal(self, analysis_data, current_price):
        if not analysis_data: 
            return 0, Config.DEFAULT_LEVERAGE

        self.bars_since_last_trade += 1
        
        # 冷却期：至少间隔3根K线 (15分钟)
        if self.bars_since_last_trade < 3:
            return 0, Config.DEFAULT_LEVERAGE

        spread_pct = analysis_data.get('spread_pct', 0.0)
        lev = Config.DEFAULT_LEVERAGE

        # Spread 过滤 (实盘)
        if (not getattr(Config, "BACKTEST_MODE", False)) and spread_pct > Config.MAX_SPREAD_PCT:
            return 0, lev

        # ========================================
        # 获取所有指标
        # ========================================
        adx = analysis_data.get('adx', 0)
        plus_di = analysis_data.get('plus_di', 0)
        minus_di = analysis_data.get('minus_di', 0)
        adx_rising = analysis_data.get('adx_rising', False)
        
        vwap_distance = analysis_data.get('vwap_distance', 0)
        
        bb_distance = analysis_data.get('bb_distance', 0)
        kdj_k = analysis_data.get('kdj_k', 50)
        macd_histogram = analysis_data.get('macd_histogram', 0)
        supertrend_5m = analysis_data.get('supertrend_direction', 0)
        supertrend_15m = self.supertrend_15m_direction

        # ================================================================
        # Layer 1: ADX 趋势强度过滤
        # ================================================================
        if adx < self.ADX_TREND:
            # 无趋势/震荡行情 → 只允许极端超买超卖的均值回归
            if bb_distance <= -0.85 and kdj_k < 15:
                sig = 1
                logger.info(f"✅ [震荡]极端超卖做多 | ADX={adx:.1f}, BB={bb_distance:.2f}, K={kdj_k:.1f}")
                self.bars_since_last_trade = 0
                return sig, lev
            if bb_distance >= 0.85 and kdj_k > 85:
                sig = -1
                logger.info(f"✅ [震荡]极端超买做空 | ADX={adx:.1f}, BB={bb_distance:.2f}, K={kdj_k:.1f}")
                self.bars_since_last_trade = 0
                return sig, lev
            
            logger.debug(f"⛔ ADX过低({adx:.1f}<{self.ADX_TREND}), 跳过")
            return 0, lev

        # ================================================================
        # Layer 2: VWAP 方向确认 + DI方向
        # ================================================================
        # 确定允许的交易方向
        vwap_bias = 0  # 0=无偏好, 1=偏多, -1=偏空
        
        # VWAP距离现在是百分比 (close-vwap)/vwap*100
        if vwap_distance > 0.05 and plus_di > minus_di:
            vwap_bias = 1   # 价格在VWAP上方0.05%+ → 只做多
        elif vwap_distance < -0.05 and minus_di > plus_di:
            vwap_bias = -1  # 价格在VWAP下方0.05%+ → 只做空
        elif plus_di > minus_di:
            vwap_bias = 1   # DI方向偏多
        elif minus_di > plus_di:
            vwap_bias = -1  # DI方向偏空

        if vwap_bias == 0:
            logger.debug(f"⛔ VWAP/DI方向不明 | VWAP_d={vwap_distance:.2f}, +DI={plus_di:.1f}, -DI={minus_di:.1f}")
            return 0, lev

        # ================================================================
        # Layer 3: 入场触发信号
        # ================================================================
        sig = 0
        
        # ------ 做多信号 ------
        if vwap_bias == 1:
            # 信号A: MACD柱正 + SuperTrend绿 + KDJ不超买 (趋势确认)
            if macd_histogram > 0 and supertrend_5m == 1 and kdj_k < 70:
                sig = 1
                logger.info(
                    f"✅ [趋势多]MACD+ST | ADX={adx:.1f}, VWAP_d={vwap_distance:.2f}, "
                    f"Hist={macd_histogram:.5f}, K={kdj_k:.1f}")
            
            # 信号B: 回调至VWAP附近做多 (VWAP回测)
            elif -0.1 < vwap_distance < 0.1 and kdj_k < 40 and supertrend_15m == 1:
                sig = 1
                logger.info(
                    f"✅ [回调多]VWAP回测 | ADX={adx:.1f}, VWAP_d={vwap_distance:.2f}, "
                    f"K={kdj_k:.1f}, ST15={supertrend_15m}")
            
            # 信号C: 强趋势 + 双SuperTrend一致 (高信心)
            elif adx > self.ADX_STRONG and supertrend_5m == 1 and supertrend_15m == 1:
                if bb_distance < 0.5 and kdj_k < 65:
                    sig = 1
                    logger.info(
                        f"✅ [强势多]双ST | ADX={adx:.1f}, BB={bb_distance:.2f}, K={kdj_k:.1f}")
        
        # ------ 做空信号 ------
        elif vwap_bias == -1:
            # 信号A: MACD柱负 + SuperTrend红 + KDJ不超卖 (趋势确认)
            if macd_histogram < 0 and supertrend_5m == -1 and kdj_k > 30:
                sig = -1
                logger.info(
                    f"✅ [趋势空]MACD+ST | ADX={adx:.1f}, VWAP_d={vwap_distance:.2f}, "
                    f"Hist={macd_histogram:.5f}, K={kdj_k:.1f}")
            
            # 信号B: 反弹至VWAP附近做空 (VWAP回测)
            elif -0.1 < vwap_distance < 0.1 and kdj_k > 60 and supertrend_15m == -1:
                sig = -1
                logger.info(
                    f"✅ [反弹空]VWAP回测 | ADX={adx:.1f}, VWAP_d={vwap_distance:.2f}, "
                    f"K={kdj_k:.1f}, ST15={supertrend_15m}")
            
            # 信号C: 强趋势 + 双SuperTrend一致 (高信心)
            elif adx > self.ADX_STRONG and supertrend_5m == -1 and supertrend_15m == -1:
                if bb_distance > -0.5 and kdj_k > 35:
                    sig = -1
                    logger.info(
                        f"✅ [强势空]双ST | ADX={adx:.1f}, BB={bb_distance:.2f}, K={kdj_k:.1f}")

        if sig != 0:
            self.bars_since_last_trade = 0
        
        return sig, lev


def check_forced_exit(state_id, position_size):
    """检查是否需要强制平仓"""
    if position_size == 0:
        return False, ""
    if state_id == 0 and position_size > 0:
        return True, "State 0 大跌 - 平多单"
    if state_id == 4 and position_size < 0:
        return True, "State 4 大涨 - 平空单"
    return False, ""
