"""
策略分析器 - ADX+VWAP+Appel黄金规则

三层过滤逻辑：
  Layer 1: ADX趋势强度过滤 → ADX < 20 禁止开仓
  Layer 2: VWAP方向确认 → 价格>VWAP偏多，价格<VWAP偏空
  Layer 3: Appel黄金规则入场 → 双MACD交叉/零线/直方图转折/背离
"""

import logging
from colorama import Fore

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


class SignalEngine:
    """多信号共识短线信号引擎 (v2)

    核心改进:
    1. 多信号投票系统: 每个指标投票(+1多/-1空/0中性)，加权求和
    2. 自适应阈值: 趋势行情降低阈值(更积极)，震荡行情提高阈值(更保守)
    3. 新增指标共识: Ichimoku/StochRSI/OBV/CCI/CMF/SAR/VWMA
    """
    
    # ADX阈值
    ADX_TREND = 20       # ADX > 20: 有趋势，可以开仓
    ADX_STRONG = 30      # ADX > 30: 强趋势，加大信心
    ADX_CHOP_GUARD = 26  # 26以下容易在震荡里来回打脸，需更严格确认

    # 信号权重 (每个指标的最大投票权重)
    SIGNAL_WEIGHTS = {
        'adx_vwap': 2.0,       # ADX+VWAP方向 (基础过滤)
        'macd_fast': 1.5,      # 快MACD (Appel买入)
        'macd_std': 1.5,       # 标准MACD (Appel卖出)
        'supertrend': 1.5,     # SuperTrend方向
        'ichimoku': 1.0,       # 一目均衡云
        'stoch_rsi': 1.0,      # 随机RSI
        'obv_div': 1.0,        # OBV背离
        'cci': 0.5,            # CCI
        'cmf': 0.5,            # CMF资金流
        'psar': 0.5,           # SAR方向
        'vwma': 0.5,           # VWMA偏差
    }

    # 共识阈值: 趋势行情需要 > threshold 分才开仓
    CONFLUENCE_TREND_THRESHOLD = 3.0    # ADX > 20: 趋势行情
    CONFLUENCE_CHOP_THRESHOLD = 5.0     # ADX < 20: 震荡行情 (更严格)
    
    def __init__(self):
        self.state, self.color = "INIT", Fore.WHITE
        self.ob_analyzer = OrderBookAnalyzer()
        self.supertrend_15m_direction = 0
        self.supertrend_1h_direction = 0
        self.bars_since_last_trade = 99

    def update_15m_supertrend(self, direction):
        self.supertrend_15m_direction = direction

    def update_1h_supertrend(self, direction):
        self.supertrend_1h_direction = direction

    def get_entry_signal(self, analysis_data, current_price):
        if not analysis_data: 
            return 0, Config.DEFAULT_LEVERAGE

        self.bars_since_last_trade += 1
        
        # 冷却期：至少间隔3根K线，避免震荡区间频繁追单
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
        vwap_distance = analysis_data.get('vwap_distance', 0)
        
        bb_distance = analysis_data.get('bb_distance', 0)
        kdj_k = analysis_data.get('kdj_k', 50)
        reversal_factor = analysis_data.get('reversal_factor', 0.0)

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
        vwap_bias = 0
        
        if vwap_distance > 0.05 and plus_di > minus_di:
            vwap_bias = 1
        elif vwap_distance < -0.05 and minus_di > plus_di:
            vwap_bias = -1
        elif plus_di > minus_di:
            vwap_bias = 1
        elif minus_di > plus_di:
            vwap_bias = -1

        if vwap_bias == 0:
            logger.debug(f"⛔ VWAP/DI方向不明 | VWAP_d={vwap_distance:.2f}, +DI={plus_di:.1f}, -DI={minus_di:.1f}")
            return 0, lev

        # 震荡保护
        if adx < self.ADX_CHOP_GUARD and abs(vwap_distance) < 0.03:
            logger.debug(f"⛔ ChopGuard | ADX={adx:.1f}, VWAP_d={vwap_distance:.3f}")
            return 0, lev

        if adx < self.ADX_CHOP_GUARD and 45 <= kdj_k <= 55:
            logger.debug(f"⛔ KDJ噪音带过滤 | ADX={adx:.1f}, K={kdj_k:.1f}")
            return 0, lev

        # ================================================================
        # Layer 3: Multi-Signal Confluence (多信号共识)
        # ================================================================
        long_score = 0.0
        short_score = 0.0
        votes_long = []
        votes_short = []

        # --- ADX+VWAP基础方向 (已确认，直接加分) ---
        if vwap_bias == 1:
            long_score += self.SIGNAL_WEIGHTS['adx_vwap']
            votes_long.append('ADX+VWAP')
        elif vwap_bias == -1:
            short_score += self.SIGNAL_WEIGHTS['adx_vwap']
            votes_short.append('ADX+VWAP')

        # --- MACD Appel信号 ---
        fast_golden = analysis_data.get('fast_macd_golden_cross', False)
        fast_above_zero = analysis_data.get('fast_macd_above_zero', False)
        fast_hist_up = analysis_data.get('fast_macd_hist_turning_up', False)
        std_death = analysis_data.get('macd_death_cross', False)
        std_above_zero = analysis_data.get('macd_above_zero', False)
        std_hist_down = analysis_data.get('macd_hist_turning_down', False)
        std_hist_up = analysis_data.get('macd_hist_turning_up', False)
        bullish_div = analysis_data.get('macd_bullish_divergence', False)
        bearish_div = analysis_data.get('macd_bearish_divergence', False)

        # 做多MACD信号
        if fast_golden and fast_above_zero:
            long_score += self.SIGNAL_WEIGHTS['macd_fast']
            votes_long.append('FastMACD金叉')
        elif fast_hist_up and kdj_k < 55:
            long_score += self.SIGNAL_WEIGHTS['macd_fast'] * 0.6
            votes_long.append('FastHist↑')
        elif std_hist_up and kdj_k < 55:
            long_score += self.SIGNAL_WEIGHTS['macd_std'] * 0.4
            votes_long.append('StdHist↑')
        elif bullish_div:
            long_score += self.SIGNAL_WEIGHTS['macd_std'] * 0.8
            votes_long.append('MACD牛背离')

        # 做空MACD信号
        if std_death and not std_above_zero:
            short_score += self.SIGNAL_WEIGHTS['macd_std']
            votes_short.append('StdMACD死叉')
        elif std_hist_down and kdj_k > 45:
            short_score += self.SIGNAL_WEIGHTS['macd_std'] * 0.6
            votes_short.append('StdHist↓')
        elif bearish_div:
            short_score += self.SIGNAL_WEIGHTS['macd_std'] * 0.8
            votes_short.append('MACD熊背离')

        # --- SuperTrend方向 ---
        supertrend_5m = analysis_data.get('supertrend_direction', 0)
        supertrend_15m = self.supertrend_15m_direction
        supertrend_1h = self.supertrend_1h_direction

        if supertrend_5m == 1:
            long_score += self.SIGNAL_WEIGHTS['supertrend'] * 0.5
            votes_long.append('ST5↑')
        elif supertrend_5m == -1:
            short_score += self.SIGNAL_WEIGHTS['supertrend'] * 0.5
            votes_short.append('ST5↓')

        if supertrend_15m == 1:
            long_score += self.SIGNAL_WEIGHTS['supertrend'] * 0.5
            votes_long.append('ST15↑')
        elif supertrend_15m == -1:
            short_score += self.SIGNAL_WEIGHTS['supertrend'] * 0.5
            votes_short.append('ST15↓')

        # --- Ichimoku云信号 ---
        ichimoku_cloud = analysis_data.get('ichimoku_cloud_signal', 0)
        ichimoku_tk = analysis_data.get('ichimoku_tk_cross', 0)

        if ichimoku_cloud == 1:
            long_score += self.SIGNAL_WEIGHTS['ichimoku'] * 0.5
            votes_long.append('一目云上')
        elif ichimoku_cloud == -1:
            short_score += self.SIGNAL_WEIGHTS['ichimoku'] * 0.5
            votes_short.append('一目云下')

        if ichimoku_tk == 1:
            long_score += self.SIGNAL_WEIGHTS['ichimoku'] * 0.5
            votes_long.append('TK金叉')
        elif ichimoku_tk == -1:
            short_score += self.SIGNAL_WEIGHTS['ichimoku'] * 0.5
            votes_short.append('TK死叉')

        # --- Stochastic RSI ---
        stoch_rsi_k = analysis_data.get('stoch_rsi_k', 50)
        stoch_rsi_golden = analysis_data.get('stoch_rsi_golden', False)
        stoch_rsi_death = analysis_data.get('stoch_rsi_death', False)

        if stoch_rsi_golden and stoch_rsi_k < 80:
            long_score += self.SIGNAL_WEIGHTS['stoch_rsi']
            votes_long.append('StochRSI金叉')
        elif stoch_rsi_death and stoch_rsi_k > 20:
            short_score += self.SIGNAL_WEIGHTS['stoch_rsi']
            votes_short.append('StochRSI死叉')

        # --- OBV背离 ---
        obv_bull_div = analysis_data.get('obv_bullish_div', False)
        obv_bear_div = analysis_data.get('obv_bearish_div', False)

        if obv_bull_div:
            long_score += self.SIGNAL_WEIGHTS['obv_div']
            votes_long.append('OBV牛背离')
        elif obv_bear_div:
            short_score += self.SIGNAL_WEIGHTS['obv_div']
            votes_short.append('OBV熊背离')

        # --- CCI ---
        cci = analysis_data.get('cci', 0)
        if cci > 100:
            long_score += self.SIGNAL_WEIGHTS['cci']
            votes_long.append(f'CCI>{cci:.0f}')
        elif cci < -100:
            short_score += self.SIGNAL_WEIGHTS['cci']
            votes_short.append(f'CCI<{cci:.0f}')

        # --- CMF资金流 ---
        cmf = analysis_data.get('cmf', 0)
        if cmf > 0.10:
            long_score += self.SIGNAL_WEIGHTS['cmf']
            votes_long.append(f'CMF+{cmf:.2f}')
        elif cmf < -0.10:
            short_score += self.SIGNAL_WEIGHTS['cmf']
            votes_short.append(f'CMF{cmf:.2f}')

        # --- Parabolic SAR ---
        psar_dir = analysis_data.get('psar_direction', 0)
        if psar_dir == 1:
            long_score += self.SIGNAL_WEIGHTS['psar']
            votes_long.append('SAR↑')
        elif psar_dir == -1:
            short_score += self.SIGNAL_WEIGHTS['psar']
            votes_short.append('SAR↓')

        # --- VWMA偏差 ---
        vwma_dev = analysis_data.get('vwma_deviation', 0)
        if vwma_dev > 0.05:
            long_score += self.SIGNAL_WEIGHTS['vwma']
            votes_long.append('VWMA>')
        elif vwma_dev < -0.05:
            short_score += self.SIGNAL_WEIGHTS['vwma']
            votes_short.append('VWMA<')

        # ================================================================
        # Layer 4: 共识决策
        # ================================================================
        # 根据ADX选择阈值
        threshold = self.CONFLUENCE_TREND_THRESHOLD if adx >= 25 else self.CONFLUENCE_CHOP_THRESHOLD

        # 强趋势时降低阈值
        if adx >= self.ADX_STRONG:
            threshold *= 0.8

        sig = 0
        if long_score >= threshold and long_score > short_score:
            sig = 1
            logger.info(
                f"✅ [共识多] score={long_score:.1f}/{threshold:.1f} | "
                f"ADX={adx:.1f} | 票: {','.join(votes_long)}"
            )
        elif short_score >= threshold and short_score > long_score:
            sig = -1
            logger.info(
                f"✅ [共识空] score={short_score:.1f}/{threshold:.1f} | "
                f"ADX={adx:.1f} | 票: {','.join(votes_short)}"
            )

        # ================================================================
        # Layer 5: 刻时模型过滤 (1h方向冲突)
        # ================================================================
        if sig != 0:
            long_conflict = supertrend_1h == -1
            short_conflict = supertrend_1h == 1

            if (sig == 1 and long_conflict) or (sig == -1 and short_conflict):
                logger.info(
                    f"⛔ [刻时模型] 1h方向冲突，放弃信号 | sig={sig}, ST1H={supertrend_1h}"
                )
                return 0, lev

            if supertrend_1h == 0 and adx < self.ADX_STRONG and abs(reversal_factor) < 0.35:
                logger.debug(
                    f"⛔ [刻时模型] 1h未确认且趋势不够强 | ADX={adx:.1f}, F={reversal_factor:.2f}"
                )
                return 0, lev

            # 15m+1h同向时，提升杠杆
            if (sig == 1 and supertrend_15m == 1 and supertrend_1h == 1) or (
                sig == -1 and supertrend_15m == -1 and supertrend_1h == -1
            ):
                lev = min(Config.MAX_LEVERAGE, lev * 1.15)

            # 强共识时额外提升杠杆
            strong_long = long_score >= threshold * 1.5
            strong_short = short_score >= threshold * 1.5
            if (sig == 1 and strong_long) or (sig == -1 and strong_short):
                lev = min(Config.MAX_LEVERAGE, lev * 1.1)

            self.bars_since_last_trade = 0

        return sig, lev
