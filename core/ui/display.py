import os
import sys
import logging
import time
from colorama import Fore, Style
from core.config.settings import Config

logger = logging.getLogger(__name__)


class DisplayManager:
    def __init__(self):
        self.last_status_len = 0

    def log_startup(self, mode_name, strategy_desc=""):
        os.system('cls' if os.name == 'nt' else 'clear')  # 启动时清屏
        print()
        print(f"{Fore.CYAN}=========================================")
        print(f"   {Config.SYMBOL} 高频量化终端")
        print(f"========================================={Style.RESET_ALL}")
        print(f"{Fore.GREEN}>>> 模式: {mode_name}{Style.RESET_ALL}")
        if strategy_desc:
            print(f"{Fore.YELLOW}>>> 策略: {strategy_desc}{Style.RESET_ALL}")
        print("-" * 41)

    def _clear_line(self):
        """清除当前行，准备打印日志"""
        # \r 回到行首, \033[K 清除光标后所有字符
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def log_msg(self, msg, level="info"):
        self._clear_line()

        timestamp = time.strftime("%H:%M:%S", time.localtime())
        prefix = f"{Style.DIM}[{timestamp}]{Style.RESET_ALL}"

        if level == "error":
            print(f"{prefix} {Fore.RED}❌ [ERR] {msg}{Style.RESET_ALL}")
        elif level == "success":
            print(f"{prefix} {Fore.GREEN}✅ [OK]  {msg}{Style.RESET_ALL}")
        elif level == "warning":
            print(f"{prefix} {Fore.YELLOW}⚠️ [WARN] {msg}{Style.RESET_ALL}")
        else:
            print(f"{prefix} {Fore.CYAN}ℹ️ [INFO] {msg}{Style.RESET_ALL}")

    def log_entry(self, regime, color, side, leverage, obi, price, sl, tp):
        self._clear_line()

        dir_str = "开多 (LONG)" if side == 1 else "开空 (SHORT)"
        dir_color = Fore.GREEN if side == 1 else Fore.RED

        # 构建日志字符串 (用于文件)
        log_str = f"{regime} | {dir_str} | {leverage}x | OBI:{obi:.2f} | TP:{tp:.4f} | SL:{sl:.4f}"
        logger.info(log_str)

        # 构建显示字符串 (用于屏幕，更美观)
        display_str = (
            f"{Fore.MAGENTA}[ENTRY] {Style.RESET_ALL}"
            f"{color}{regime:<8}{Style.RESET_ALL} | "
            f"{dir_color}{dir_str}{Style.RESET_ALL} | "
            f"Lev:{leverage}x | "
            f"Price:{price:.4f} | "
            f"TP:{tp:.4f}"
        )
        print(display_str)

    def log_exit(self, reason, price, pnl, fee, balance, extra=""):
        self._clear_line()

        # 记录到日志文件
        logger.info(f"{reason} | P:{price} | PnL:{pnl:+.2f} (Fee:-{fee:.2f}) | Bal:${balance:.2f} {extra}")

        # 屏幕显示
        pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
        display_str = (
            f"{Fore.MAGENTA}[EXIT ] {Style.RESET_ALL}"
            f"{Fore.YELLOW}{reason:<10}{Style.RESET_ALL} | "
            f"Price:{price:.4f} | "
            f"PnL:{pnl_color}{pnl:+.2f}{Style.RESET_ALL} | "
            f"Bal:{Fore.CYAN}${balance:.2f}{Style.RESET_ALL}"
        )
        print(display_str)

    def update_status(self, pos, regime, color, obi, pnl, price, cluster_id=5):
        """
        实时刷新状态栏
        注意：尽量使用定宽格式化 (e.g. :<10, :.4f) 防止字符串长度抖动
        """
        # 安全处理空值
        regime = regime if regime else "N/A"
        color = color if color else ""

        status_icon = "🟢" if pos > 0 else "🔴" if pos < 0 else "⚪"
        pnl_c = Fore.GREEN if pnl >= 0 else Fore.RED
        
        # HMM 状态名称映射
        state_names = {0: "跌", 1: "弱跌", 2: "震荡", 3: "弱涨", 4: "涨", 99: "初始"}
        state_name = state_names.get(cluster_id, "?")

        # 状态栏格式化
        # \033[K 确保清除上一帧残留的字符
        info_str = (
            f"\r\033[K"
            f"{status_icon} "
            f"{color}{regime:<8}{Style.RESET_ALL} | "
            f"OBI:{obi:>+5.2f} | "  # 强制显示符号，宽度5
            f"P:{price:<8.4f} | "  # 左对齐，保留4位小数
            f"S{cluster_id}({state_name}) | "  # 状态ID + 名称
            f"{pnl_c}${pnl:>+7.2f}{Style.RESET_ALL}"  # PnL 右对齐
        )

        sys.stdout.write(info_str)
        sys.stdout.flush()