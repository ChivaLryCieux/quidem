"""
Rich TUI 显示管理器

使用 Rich 库实现现代化的终端界面，包括：
- 彩色输出和样式
- 面板和表格布局
- 实时状态栏
- 日志消息格式化
"""

import logging
import time
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.live import Live
from rich.rule import Rule
from rich.style import Style
from rich.box import ROUNDED, SIMPLE_HEAVY

from core.config.settings import Config

logger = logging.getLogger(__name__)

# 自定义样式
STYLES = {
    'title': Style(color='cyan', bold=True),
    'mode': Style(color='green', bold=True),
    'symbol': Style(color='yellow', bold=True),
    'info': Style(color='blue'),
    'success': Style(color='green'),
    'warning': Style(color='yellow'),
    'error': Style(color='red', bold=True),
    'dim': Style(dim=True),
    'price': Style(color='white', bold=True),
    'pnl_positive': Style(color='green', bold=True),
    'pnl_negative': Style(color='red', bold=True),
    'long': Style(color='green', bold=True),
    'short': Style(color='red', bold=True),
    'neutral': Style(color='white'),
    'header': Style(color='cyan', bold=True),
    'accent': Style(color='magenta'),
}


class DisplayManager:
    """Rich TUI 显示管理器"""

    def __init__(self):
        self.console = Console()
        self.last_status_len = 0
        self._live: Optional[Live] = None
        self._status_table: Optional[Table] = None

    def log_startup(self):
        """显示启动信息面板（项目名、启动日期、模式、WebUI 地址等）"""
        self.console.clear()

        from core.config.mode import TradingMode

        # 标题：◈ QUIDEM_CTA
        title_text = Text()
        title_text.append("◈ ", style='red bold')
        title_text.append("QUIDEM", style='white bold')
        title_text.append("_", style='red bold')
        title_text.append("CTA", style='white bold')

        # 启动日期与时间
        now = datetime.now()
        start_time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # WebUI 地址
        web_url = f"http://{Config.WEB_HOST}:{Config.WEB_PORT}"

        # 默认模式
        mode_label = TradingMode.DASHBOARD.label

        content = Text()
        content.append(f"\n  Symbol:    ", style='dim')
        content.append(f"{Config.SYMBOL}", style='cyan bold')
        content.append(f"\n  Mode:      ", style='dim')
        content.append(f"{mode_label} (看盘，不交易)", style='yellow bold')
        content.append(f"\n  Started:   ", style='dim')
        content.append(f"{start_time_str}", style='white')
        content.append(f"\n  WebUI:     ", style='dim')
        content.append(f"{web_url}", style='green')
        content.append(f"\n  Exchange:  ", style='dim')
        content.append(f"Binance Futures", style='white')

        content.append(f"\n\n  ", style='dim')
        content.append("━" * 40, style='dim')

        content.append(f"\n  ", style='dim')
        content.append("正在连接交易所并打开浏览器...", style='cyan')
        content.append(f"\n  ", style='dim')
        content.append("模式可在 WebUI 顶部切换 (Dashboard → Paper → Live)", style='dim italic')

        panel = Panel(
            content,
            title=title_text,
            border_style='red',
            box=ROUNDED,
            padding=(1, 2),
        )

        self.console.print(panel)
        self.console.print()

    def _get_timestamp(self) -> str:
        """获取格式化的时间戳"""
        return datetime.now().strftime("%H:%M:%S")

    def log_msg(self, msg: str, level: str = "info"):
        """输出日志消息"""
        timestamp = self._get_timestamp()

        # 根据级别选择样式
        level_config = {
            'error': ('✖', 'red bold', 'ERROR'),
            'success': ('✔', 'green bold', 'OK'),
            'warning': ('⚠', 'yellow bold', 'WARN'),
            'info': ('●', 'blue', 'INFO'),
        }

        icon, style, label = level_config.get(level, ('●', 'blue', 'INFO'))

        # 构建消息
        text = Text()
        text.append(f" {timestamp} ", style='dim')
        text.append(f"{icon} ", style=style)
        text.append(f"[{label}] ", style=style)
        text.append(msg, style='white')

        self.console.print(text)

    def log_entry(self, regime: str, color: str, side: int, leverage: float,
                  price: float, sl: float, tp: float, macd: float = 0.0,
                  bb_mid: float = 0.0, st_val: float = 0.0):
        """输出开仓日志"""
        timestamp = self._get_timestamp()
        dir_str = "LONG" if side == 1 else "SHORT"
        dir_style = 'long' if side == 1 else 'short'

        # 记录到日志文件
        log_str = f"{regime} | {'开多' if side == 1 else '开空'} | {leverage}x | MACD:{macd:.5f} | TP:{tp:.4f} | SL:{sl:.4f}"
        logger.info(log_str)

        # 构建显示
        text = Text()
        text.append(f" {timestamp} ", style='dim')
        text.append("▲ ENTRY ", style='magenta bold')
        text.append(f"{regime:<8}", style='cyan')
        text.append(" │ ", style='dim')
        text.append(f"{dir_str:<5}", style=dir_style)
        text.append(f" {leverage}x", style='white bold')
        text.append(" │ ", style='dim')
        text.append(f"Price: ", style='dim')
        text.append(f"{price:.4f}", style='white bold')
        text.append(" │ ", style='dim')
        text.append(f"TP: ", style='dim')
        text.append(f"{tp:.4f}", style='green')
        text.append(" │ ", style='dim')
        text.append(f"SL: ", style='dim')
        text.append(f"{sl:.4f}", style='red')

        # 创建面板
        panel = Panel(
            text,
            border_style='green' if side == 1 else 'red',
            box=SIMPLE_HEAVY,
            padding=(0, 1),
        )

        self.console.print(panel)

    def log_exit(self, reason: str, price: float, pnl: float, fee: float,
                 balance: float, extra: str = ""):
        """输出平仓日志"""
        timestamp = self._get_timestamp()
        pnl_style = 'pnl_positive' if pnl >= 0 else 'pnl_negative'
        pnl_sign = '+' if pnl >= 0 else ''

        # 记录到日志文件
        logger.info(f"{reason} | P:{price} | PnL:{pnl:+.2f} (Fee:-{fee:.2f}) | Bal:${balance:.2f} {extra}")

        # 构建显示
        text = Text()
        text.append(f" {timestamp} ", style='dim')
        text.append("▼ EXIT  ", style='magenta bold')
        text.append(f"{reason:<10}", style='yellow')
        text.append(" │ ", style='dim')
        text.append(f"Price: ", style='dim')
        text.append(f"{price:.4f}", style='white bold')
        text.append(" │ ", style='dim')
        text.append(f"PnL: ", style='dim')
        text.append(f"{pnl_sign}${pnl:.2f}", style=pnl_style)
        text.append(" │ ", style='dim')
        text.append(f"Fee: ", style='dim')
        text.append(f"-${fee:.2f}", style='dim')
        text.append(" │ ", style='dim')
        text.append(f"Bal: ", style='dim')
        text.append(f"${balance:.2f}", style='cyan bold')

        if extra:
            text.append(f" │ {extra}", style='yellow')

        # 创建面板
        panel = Panel(
            text,
            border_style='green' if pnl >= 0 else 'red',
            box=SIMPLE_HEAVY,
            padding=(0, 1),
        )

        self.console.print(panel)

    def update_status(self, pos: float, regime: str, color: str, pnl: float,
                      price: float, macd: float = 0.0, adx: float = 0.0,
                      reversal: float = 0.0):
        """实时刷新状态栏"""
        regime = regime if regime else "N/A"

        # 状态指示器
        if pos > 0:
            pos_icon = "▲"
            pos_style = 'long'
            pos_text = "LONG"
        elif pos < 0:
            pos_icon = "▼"
            pos_style = 'short'
            pos_text = "SHORT"
        else:
            pos_icon = "◇"
            pos_style = 'neutral'
            pos_text = "FLAT"

        pnl_style = 'pnl_positive' if pnl >= 0 else 'pnl_negative'
        pnl_sign = '+' if pnl >= 0 else ''
        macd_style = 'pnl_positive' if macd >= 0 else 'pnl_negative'

        # 构建状态行
        text = Text()
        text.append(f"\r", style='dim')

        # 持仓状态
        text.append(f" {pos_icon} {pos_text:<5}", style=pos_style)
        text.append(" │ ", style='dim')

        # 市场状态
        text.append(f"{regime:<8}", style='cyan')
        text.append(" │ ", style='dim')

        # MACD
        text.append(f"MACD:", style='dim')
        text.append(f"{macd:>+8.4f}", style=macd_style)
        text.append(" │ ", style='dim')

        # ADX
        text.append(f"ADX:", style='dim')
        text.append(f"{adx:>5.1f}", style='white' if adx < 25 else 'yellow' if adx < 35 else 'red bold')
        text.append(" │ ", style='dim')

        # Reversal
        text.append(f"REV:", style='dim')
        text.append(f"{reversal:>+5.2f}", style='white')
        text.append(" │ ", style='dim')

        # 价格
        text.append(f"Price:", style='dim')
        text.append(f"{price:<9.4f}", style='white bold')
        text.append(" │ ", style='dim')

        # 盈亏
        text.append(f"{pnl_sign}${pnl:>+8.2f}", style=pnl_style)

        # 输出（使用 \r 覆盖同一行）
        self.console.file.write(f"\r\033[K{text.plain}")
        self.console.file.flush()

    def print_separator(self):
        """打印分隔线"""
        self.console.print(Rule(style='dim'))

    def print_header(self, text: str):
        """打印标题"""
        self.console.print(f"\n[bold cyan]{text}[/bold cyan]")
        self.console.print(Rule(style='cyan'))

    def create_status_table(self, data: dict) -> Table:
        """创建状态表格"""
        table = Table(
            box=ROUNDED,
            show_header=True,
            header_style='header',
            border_style='dim',
            padding=(0, 1),
        )

        table.add_column("Key", style='dim')
        table.add_column("Value", style='white')

        for key, value in data.items():
            table.add_row(key, str(value))

        return table

    def print_panel(self, content: str, title: str = "", border_style: str = 'dim'):
        """打印面板"""
        panel = Panel(
            content,
            title=title,
            border_style=border_style,
            box=ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)

    def print_error(self, msg: str):
        """打印错误消息"""
        self.console.print(f"\n[bold red]✖ ERROR:[/bold red] {msg}\n")

    def print_success(self, msg: str):
        """打印成功消息"""
        self.console.print(f"[bold green]✔ SUCCESS:[/bold green] {msg}")

    def print_warning(self, msg: str):
        """打印警告消息"""
        self.console.print(f"[bold yellow]⚠ WARNING:[/bold yellow] {msg}")

    def print_info(self, msg: str):
        """打印信息消息"""
        self.console.print(f"[blue]● INFO:[/blue] {msg}")
