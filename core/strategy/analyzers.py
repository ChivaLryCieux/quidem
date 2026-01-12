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

    def determine_regime(self, range_pct, vol_expl):
        if range_pct < 0.0015:
            self.state, self.color = "💤 NOISE", Fore.WHITE
        elif vol_expl > 1.5:
            self.state, self.color = "💥 BREAKOUT", Fore.MAGENTA
        else:
            if vol_expl > 1.05:
                self.state, self.color = "💥 BREAKOUT", Fore.MAGENTA
            else:
                self.state, self.color = "🦀 RANGE", Fore.YELLOW
        return self.state, self.color

    def get_entry_signal(self, analysis_data, current_price):
        if not analysis_data: return 0, Config.MIN_LEVERAGE

        if 'obi' in analysis_data and 'spread_pct' in analysis_data:
            obi = analysis_data['obi']
            spread_pct = analysis_data['spread_pct']
        else:
            obi, spread_pct = self.ob_analyzer.analyze(analysis_data.get('orderbook', {}))

        features = analysis_data['features']
        # 这里 ai_conf 已经是 双核平均值
        ai_dir, ai_conf = analysis_data['ai_prediction']
        cluster_data = analysis_data.get('cluster', (99, 0.0))
        cluster_id = cluster_data[0]

        sig, lev = 0, Config.MIN_LEVERAGE

        # Spread 过滤
        if (not getattr(Config, "BACKTEST_MODE", False)) and spread_pct > Config.MAX_SPREAD_PCT:
            print(f"⛔ Spread过大: {spread_pct:.5f}")
            return 0, lev

        if cluster_id == 99:  # 入口簇改为99
            return 0, lev

        if cluster_id != self.last_cluster:
            print(f" 🔄 簇变更: {self.last_cluster} -> {cluster_id}")
            self.last_cluster = cluster_id

        # 恢复默认阈值 0.4 (或更高，随你设定)
        # Modified to 0.15 based on optimization plan (Tiered Threshold)
        target_conf = 0.15
        is_signal = False
        match_reason = ""

        # === 新状态机规则 ===
        if cluster_id == 0:
            # 簇0波动，多空看AI
            if ai_dir != 0 and ai_conf > target_conf:
                sig, lev, is_signal = ai_dir, 5, True
                match_reason = f"簇0波动+AI信心{ai_conf:.2f}"

        elif cluster_id == 1:
            # 簇1波动，多空看AI
            if ai_dir != 0 and ai_conf > target_conf:
                sig, lev, is_signal = ai_dir, 5, True
                match_reason = f"簇1波动+AI信心{ai_conf:.2f}"

        elif cluster_id == 2:
            # 簇2大跌，只做空
            if ai_dir == -1 and ai_conf > target_conf:
                sig, lev, is_signal = -1, 5, True
                match_reason = f"簇2大跌+AI看跌{ai_conf:.2f}"

        elif cluster_id == 3:
            # 簇3危险，不开仓
            sig, lev, is_signal = 0, Config.MIN_LEVERAGE, False
            match_reason = f"簇3危险+不开仓"

        elif cluster_id == 4:
            # 簇4涨，只做多
            if ai_dir == 1 and ai_conf > target_conf:
                sig, lev, is_signal = 1, 5, True
                match_reason = f"簇4涨+AI看涨{ai_conf:.2f}"

        elif cluster_id == 5:
            # 簇5大涨，只做多
            if ai_dir == 1 and ai_conf > target_conf:
                sig, lev, is_signal = 1, 5, True
                match_reason = f"簇5大涨+AI看涨{ai_conf:.2f}"

        elif cluster_id == 6:
            # 簇6跌，只做空，无论多空都要配合AI方向和信心
            if ai_dir == -1 and ai_conf > target_conf:
                sig, lev, is_signal = -1, 5, True
                match_reason = f"簇6跌+AI看跌{ai_conf:.2f}"

        else:
            # 其他未知簇，默认不开仓
            sig, lev, is_signal = 0, Config.MIN_LEVERAGE, False
            match_reason = f"未知簇{cluster_id}+不开仓"

        if is_signal:
            logger.info(f"信号生成: {match_reason}")

        return sig, lev