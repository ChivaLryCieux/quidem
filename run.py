# 模拟盘与实盘的顶层入口文件
from core.main import QuantBot

if __name__ == "__main__":
    bot = QuantBot()
    bot.run()
