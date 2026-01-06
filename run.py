# 模拟盘与实盘的顶层入口文件
import sys
from core.main import QuantBot

if __name__ == "__main__":
    # 支持命令行参数选择模式
    mode = None
    if len(sys.argv) > 1:
        if sys.argv[1] in ['1', '2']:
            mode = sys.argv[1]
    
    bot = QuantBot(mode_override=mode)
    bot.run()
