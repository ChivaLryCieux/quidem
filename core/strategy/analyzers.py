"""
策略分析器 - ADX+VWAP+Appel黄金规则

三层过滤逻辑：
  Layer 1: ADX趋势强度过滤 → ADX < 20 禁止开仓
  Layer 2: VWAP方向确认 → 价格>VWAP偏多，价格<VWAP偏空
  Layer 3: Appel黄金规则入场 → 双MACD交叉/零线/直方图转折/背离
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
        # Layer 3: Appel 黄金规则入场触发
        # ================================================================
        sig = 0
        
        # 获取 Appel 信号
        # 快速 MACD (8,17,9) — 买入专用
        fast_golden = analysis_data.get('fast_macd_golden_cross', False)
        fast_above_zero = analysis_data.get('fast_macd_above_zero', False)
        fast_hist_up = analysis_data.get('fast_macd_hist_turning_up', False)
        
        # 标准 MACD (12,26,9) — 卖出专用 + 背离
        std_death = analysis_data.get('macd_death_cross', False)
        std_above_zero = analysis_data.get('macd_above_zero', False)
        std_hist_down = analysis_data.get('macd_hist_turning_down', False)
        std_hist_up = analysis_data.get('macd_hist_turning_up', False)
        bullish_div = analysis_data.get('macd_bullish_divergence', False)
        bearish_div = analysis_data.get('macd_bearish_divergence', False)
        
        supertrend_5m = analysis_data.get('supertrend_direction', 0)
        supertrend_15m = self.supertrend_15m_direction
        
        # ------ 做多信号 (快MACD 8,17) ------
        if vwap_bias == 1:
            # 信号A: 快MACD金叉 + 零线上方 + ST绿 (Appel趋势做多)
            if fast_golden and fast_above_zero and supertrend_5m == 1:
                sig = 1
                logger.info(
                    f"✅ [Appel多A] 快MACD金叉+零线上 | ADX={adx:.1f}, VWAP_d={vwap_distance:.2f}, "
                    f"ST5={supertrend_5m}")
            
            # 信号B: 直方图转折向上 + KDJ不超买 (Appel动量做多)
            elif (fast_hist_up or std_hist_up) and kdj_k < 55 and supertrend_5m == 1:
                sig = 1
                logger.info(
                    f"✅ [Appel多B] 直方图转折↑ | ADX={adx:.1f}, K={kdj_k:.1f}, "
                    f"FastHist↑={fast_hist_up}, StdHist↑={std_hist_up}")
            
            # 信号C: 看涨背离 + ADX>25 (Appel反转做多)
            elif bullish_div and adx > 25 and kdj_k < 40:
                sig = 1
                logger.info(
                    f"✅ [Appel多C] 看涨背离 | ADX={adx:.1f}, K={kdj_k:.1f}")
            
            # 信号D: 强趋势 + 双ST一致 (原有高信心信号保留)
            elif adx > self.ADX_STRONG and supertrend_5m == 1 and supertrend_15m == 1:
                if bb_distance < 0.5 and kdj_k < 65:
                    sig = 1
                    logger.info(
                        f"✅ [强势多] 双ST | ADX={adx:.1f}, BB={bb_distance:.2f}, K={kdj_k:.1f}")
        
        # ------ 做空信号 (标准MACD 12,26) ------
        elif vwap_bias == -1:
            # 信号A: 标准MACD死叉 + 零线下方 + ST红 (Appel趋势做空)
            if std_death and not std_above_zero and supertrend_5m == -1:
                sig = -1
                logger.info(
                    f"✅ [Appel空A] 标准MACD死叉+零线下 | ADX={adx:.1f}, VWAP_d={vwap_distance:.2f}, "
                    f"ST5={supertrend_5m}")
            
            # 信号B: 直方图转折向下 + KDJ不超卖 (Appel动量做空)
            elif std_hist_down and kdj_k > 45 and supertrend_5m == -1:
                sig = -1
                logger.info(
                    f"✅ [Appel空B] 直方图转折↓ | ADX={adx:.1f}, K={kdj_k:.1f}")
            
            # 信号C: 看跌背离 + ADX>25 (Appel反转做空)
            elif bearish_div and adx > 25 and kdj_k > 60:
                sig = -1
                logger.info(
                    f"✅ [Appel空C] 看跌背离 | ADX={adx:.1f}, K={kdj_k:.1f}")
            
            # 信号D: 强趋势 + 双ST一致 (原有高信心信号保留)
            elif adx > self.ADX_STRONG and supertrend_5m == -1 and supertrend_15m == -1:
                if bb_distance > -0.5 and kdj_k > 35:
                    sig = -1
                    logger.info(
                        f"✅ [强势空] 双ST | ADX={adx:.1f}, BB={bb_distance:.2f}, K={kdj_k:.1f}")

        if sig != 0:
            self.bars_since_last_trade = 0
        
        return sig, lev
