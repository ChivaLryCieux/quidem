import os
import sys
import threading
import queue
import time

# 针对 Unix 系统的特定导入
if os.name != 'nt':
    import select
    import tty
    import termios


class KeyListener:
    def __init__(self):
        self.os_name = os.name
        self.is_tty = sys.stdin.isatty()
        self.input_queue = queue.Queue()

        # 如果不是标准终端（例如 IDE console），启动后台线程监听输入
        if not self.is_tty:
            self._start_ide_listener()

    def _start_ide_listener(self):
        t = threading.Thread(target=self._ide_input_worker)
        t.daemon = True
        t.start()

    def _ide_input_worker(self):
        """后台线程：用于处理 IDE 环境下的输入（通常需要回车）"""
        while True:
            try:
                line = sys.stdin.readline()
                if line:
                    self.input_queue.put(line.strip())
            except (EOFError, ValueError):
                break

    def is_q_pressed(self):
        """非阻塞检测是否按下了 'q' 键"""

        # 1. 处理 IDE / 非 TTY 环境
        if not self.is_tty:
            while not self.input_queue.empty():
                try:
                    cmd = self.input_queue.get_nowait()
                    if 'q' in cmd.lower(): return True
                except queue.Empty:
                    pass
            return False

        # 2. 处理 Windows TTY (即按即响应)
        if self.os_name == 'nt':
            return self._windows_is_q_pressed()

        # 3. 处理 Unix/Linux TTY (即按即响应)
        return self._unix_is_q_pressed()

    def _windows_is_q_pressed(self):
        import msvcrt
        if msvcrt.kbhit():
            try:
                # getch 返回的是 bytes，需要解码
                # 注意：功能键可能会导致 decode 失败，需要捕获异常
                char = msvcrt.getch().decode('utf-8').lower()
                return char == 'q'
            except UnicodeDecodeError:
                return False
        return False

    def _unix_is_q_pressed(self):
        """
        Unix 下实现类似 Windows kbhit 的功能
        必须暂时将终端切换到 cbreak 模式才能捕获单个字符而不等待回车
        """
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            # 设置为 cbreak 模式 (读取字符不需要回车)
            tty.setcbreak(fd)

            # 非阻塞检查是否有输入
            dr, _, _ = select.select([sys.stdin], [], [], 0)
            if dr:
                ch = sys.stdin.read(1).lower()
                return ch == 'q'
        except Exception:
            pass
        finally:
            # 务必恢复终端设置，否则退出后终端会乱掉
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return False

    def safe_input(self, prompt=""):
        """线程安全的 input 封装"""
        # 如果是 IDE 队列模式，优先从队列取
        if not self.is_tty:
            print(prompt, end='', flush=True)
            try:
                # 阻塞等待用户输入，模拟 input() 行为
                # 这里设置一个较长的超时，避免死锁
                return self.input_queue.get(timeout=300)
            except queue.Empty:
                return ""

        # 标准终端模式
        try:
            return input(prompt)
        except EOFError:
            return ""