import os
import sys
import threading
import queue
import time
from colorama import Fore, Style
from config import Config

# 跨平台按键检测依赖
if os.name == 'nt':
    import msvcrt
else:
    import select
    import tty
    import termios

# ==========================================
# 终端 UI 管理
# ==========================================
class DisplayManager:
    def log_startup(self, mode_name, strategy_desc=""):
        print(f"{Fore.CYAN}=========================================")
        print(f"   {Config.SYMBOL} 高频量化终端")
        print(f"========================================={Style.RESET_ALL}")
        print(f"{Fore.GREEN}>>> 模式: {mode_name}{Style.RESET_ALL}")
        if strategy_desc:
            print(f"{Fore.YELLOW}>>> 策略: {strategy_desc}{Style.RESET_ALL}")
            try:
                from strategy_config import StrategyConfig
                current_config = StrategyConfig.get_config('CONSERVATIVE')
                print(f"{Fore.CYAN}>>> AI置信度阈值: {current_config['AI_CONFIDENCE_THRESHOLD']}{Style.RESET_ALL}")
                print(f"{Fore.CYAN}>>> 严格过滤器: {'启用' if current_config['ENABLE_STRICT_FILTERS'] else '禁用'}{Style.RESET_ALL}")
            except:
                pass

    def log_entry(self, regime, color, side, leverage, obi, price, sl, tp):
        sys.stdout.write("\r" + " " * 100 + "\r")
        dir_str = "开多" if side == 1 else "开空"
        print(f"\n{color}>>> ⚡️ {regime} | {dir_str} | {leverage}x | OBI:{obi:.2f}{Style.RESET_ALL}")
        print(f"    🎯 TP: {tp:.4f} | 🛡️ SL: {sl:.4f}")

    def log_exit(self, reason, price, pnl, fee, balance, extra=""):
        sys.stdout.write("\r" + " " * 100 + "\r")
        pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
        print(
            f"\n{reason} | P:{price} | PnL:{pnl_color}{pnl:+.2f}{Style.RESET_ALL} (Fee:-{fee:.2f}) | Bal:${balance:.2f} {extra}")

    def update_status(self, pos, regime, color, obi, pnl, price, hf_pred_1m, hf_pred_diff, ai_conf, cluster_id=5):
        status = "🟢 LONG" if pos > 0 else "🔴 SHORT" if pos < 0 else "⚪ WAIT"
        pnl_c = Fore.GREEN if pnl >= 0 else Fore.RED
        cluster_display = f"C{cluster_id}" if cluster_id != 5 else "C5(初始)"
        bar = (f"\r{status} | {color}{regime}{Style.RESET_ALL} | OBI:{obi:+.2f} | "
               f"Price:{price:.4f} | HF1m:{hf_pred_1m:.4f} | Diff:{hf_pred_diff:+.4f} | AI:{ai_conf:.2f} | "
               f"Cluster:{cluster_display} | PnL:{pnl_c}${pnl:+.2f}{Style.RESET_ALL}")
        sys.stdout.write(f"{bar:<140}")
        sys.stdout.flush()

    def log_msg(self, msg, type="info"):
        color = Fore.RED if type == "error" else Fore.YELLOW if type == "warning" else Fore.CYAN
        print(f"\r{color}>>> {msg}{Style.RESET_ALL}")


class KeyListener:
    def __init__(self):
        self.os_name = os.name
        self.is_tty = sys.stdin.isatty()
        self.input_queue = queue.Queue()
        if not self.is_tty:
            t = threading.Thread(target=self._ide_input_listener)
            t.daemon = True;
            t.start()

    def _ide_input_listener(self):
        while True:
            try:
                line = sys.stdin.readline()
                if line: self.input_queue.put(line.strip())
            except:
                break

    def is_q_pressed(self):
        if not self.is_tty:
            while not self.input_queue.empty():
                if 'q' in self.input_queue.get_nowait().lower(): return True
            return False
        if self.os_name == 'nt':
            if msvcrt.kbhit():
                return msvcrt.getch().decode('utf-8').lower() == 'q'
        else:
            dr, _, _ = select.select([sys.stdin], [], [], 0)
            if dr: return sys.stdin.read(1).lower() == 'q'
        return False

    def safe_input(self, prompt=""):
        if self.is_tty: return input(prompt)
        print(prompt, end='', flush=True)
        try:
            return self.input_queue.get()
        except:
            return ""