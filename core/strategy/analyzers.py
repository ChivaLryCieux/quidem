import numpy as np
import pandas as pd
import logging
from colorama import Fore, Style

from core.config.settings import Config

logger = logging.getLogger(__name__)


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
        decay = 0.9
        w_bid_vol = sum(o[1] * (TARGET_DEPTH - i) / TARGET_DEPTH for i, o in enumerate(bids))
        w_ask_vol = sum(o[1] * (TARGET_DEPTH - i) / TARGET_DEPTH for i, o in enumerate(asks))
        total_vol = w_bid_vol + w_ask_vol + 1e-9
        obi = (w_bid_vol - w_ask_vol) / total_vol
        mid_price = (bids[0][0] + asks[0][0]) / 2
        spread_pct = (asks[0][0] - bids[0][0]) / mid_price
        return obi, spread_pct


# ==========================================
# 2. 状态机
# ==========================================
class StateMachine:
    def __init__(self):
        self.state, self.color = "INIT", Fore.WHITE
        self.ob_analyzer = OrderBookAnalyzer()
        self.last_cluster = 99  # 入口簇改为99


    def get_entry_signal(self, analysis_data, current_price):
        if not analysis_data: return 0, Config.MIN_LEVERAGE

        if 'obi' in analysis_data and 'spread_pct' in analysis_data:
            obi = analysis_data['obi']
            spread_pct = analysis_data['spread_pct']
        else:
            obi, spread_pct = self.ob_analyzer.analyze(analysis_data.get('orderbook', {}))

        cluster_data = analysis_data.get('cluster', (99, 0.0))
        state_id = cluster_data[0]

        sig, lev = 0, Config.MIN_LEVERAGE

        # Spread 过滤
        if (not getattr(Config, "BACKTEST_MODE", False)) and spread_pct > Config.MAX_SPREAD_PCT:
            print(f"⛔ Spread过大: {spread_pct:.5f}")
            return 0, lev

        if state_id == 99:  # 初始化状态
            return 0, lev

        if state_id != self.last_cluster:
            state_names = {0: "大跌", 1: "弱跌", 2: "震荡", 3: "弱涨", 4: "大涨", 99: "初始"}
            print(f"🔄 状态变更: {self.last_cluster}({state_names.get(self.last_cluster, '?')}) -> {state_id}({state_names.get(state_id, '?')})")
            self.last_cluster = state_id

        # ===  5 状态 HMM 策略逻辑 (移除AI信心判断，直接根据状态开仓) ===
        is_signal = False
        match_reason = ""
        
        if state_id == 0:
            # State 0: 极度恐慌/大跌 - 做空
            sig, lev, is_signal = -1, 5, True
            match_reason = "State 0 大跌+做空"
        
        elif state_id == 1:
            # State 1: 阴跌/弱势 - 做空
            sig, lev, is_signal = -1, 5, True
            match_reason = "State 1 弱跌+做空"
        
        elif state_id == 2:
            # State 2: 震荡/噪音 - 空仓观望，不开仓
            sig, lev, is_signal = 0, Config.MIN_LEVERAGE, False
            match_reason = "State 2 震荡+空仓观望"
        
        elif state_id == 3:
            # State 3: 反弹/弱势上涨 - 做多
            sig, lev, is_signal = 1, 5, True
            match_reason = "State 3 弱涨+做多"
        
        elif state_id == 4:
            # State 4: 主升浪/大涨 - 做多
            sig, lev, is_signal = 1, 5, True
            match_reason = "State 4 大涨+做多"
        
        else:
            # 未知状态，不开仓
            sig, lev, is_signal = 0, Config.MIN_LEVERAGE, False
            match_reason = f"未知状态{state_id}+不开仓"

        if is_signal:
            logger.info(f"✅ 信号生成: {match_reason}")
        elif state_id == 2:
            # State 2 特殊处理：即使没有信号也要记录
            logger.info(f"⚠️ {match_reason}")

        return sig, lev
