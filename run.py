# 模拟盘与实盘的顶层入口文件
import sys

from core.engine.bot import QuantBot


def main():
    # 支持命令行参数选择模式：python run.py 1 (模拟盘) / 2 (实盘)
    mode = None
    if len(sys.argv) > 1:
        if sys.argv[1] in ['1', '2']:
            mode = sys.argv[1]

    bot = QuantBot(mode_override=mode)
    bot.run()


if __name__ == "__main__":
    main()
