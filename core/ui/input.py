import os
import sys
import threading
import queue
import time

class KeyListener:
    def __init__(self):
        self.os_name = os.name
        self.is_tty = sys.stdin.isatty()
        self.input_queue = queue.Queue()
        if not self.is_tty:
            t = threading.Thread(target=self._ide_input_listener)
            t.daemon = True
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
            import msvcrt
            if msvcrt.kbhit():
                return msvcrt.getch().decode('utf-8').lower() == 'q'
        else:
            import select
            import tty
            import termios
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