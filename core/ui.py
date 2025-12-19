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
    def log_startup(self, mode_name):
        print(f"{Fore.CYAN}=========================================")
        print(f"   {Config.SYMBOL} 高频量化终端 (WebSocket) ")
        print(f"========================================={Style.RESET_ALL}")
        print(f"{Fore.GREEN}>>> 模式: {mode_name}{Style.RESET_ALL}")

    def log_entry(self, regime, color, side, leverage, obi, price, sl, tp, fr):
        sys.stdout.write("\r" + " " * 100 + "\r")
        dir_str = "开多" if side == 1 else "开空"
        fr_str = f"FR:{fr * 100:.4f}%"
        print(f"\n{color}>>> ⚡️ {regime} | {dir_str} | {leverage}x | OBI:{obi:.2f} | {fr_str}{Style.RESET_ALL}")
        print(f"    🎯 TP: {tp:.4f} | 🛡️ SL: {sl:.4f}")

    def log_exit(self, reason, price, pnl, fee, balance, extra=""):
        sys.stdout.write("\r" + " " * 100 + "\r")
        pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
        print(
            f"\n{reason} | P:{price} | PnL:{pnl_color}{pnl:+.2f}{Style.RESET_ALL} (Fee:-{fee:.2f}) | Bal:${balance:.2f} {extra}")

    def update_status(self, pos, regime, color, obi, pnl, price, fr):
        status = "🟢 LONG" if pos > 0 else "🔴 SHORT" if pos < 0 else "⚪ WAIT"
        pnl_c = Fore.GREEN if pnl >= 0 else Fore.RED
        fr_c = Fore.RED if (pos > 0 and fr > 0) or (pos < 0 and fr < 0) else Fore.GREEN
        bar = (f"\r{status} | {color}{regime}{Style.RESET_ALL} | OBI:{obi:+.2f} | "
               f"Price:{price:.4f} | PnL:{pnl_c}${pnl:+.2f}{Style.RESET_ALL} | FR:{fr_c}{fr * 100:.4f}%{Style.RESET_ALL}")
        sys.stdout.write(f"{bar:<110}")
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