"""
Web GUI 模块

提供基于 FastAPI 的 Web 界面，支持实时数据推送和控制。
"""

from .state import WebState
from .runner import WebRunner

__all__ = ['WebState', 'WebRunner']
