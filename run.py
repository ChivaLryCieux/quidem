# 量化交易系统顶层入口
#
# 启动行为：
# 1. Rich 打印项目名称、启动日期等信息
# 2. 默认进入 DASHBOARD（看盘）模式，不交易
# 3. 自动打开浏览器加载 WebUI
# 4. 用户可在 WebUI 顶部切换到 PAPER（模拟）/ LIVE（实盘）模式
#
# 交易模式由 WebUI 运行时控制，不再通过命令行参数选择。

from core.engine.bot import QuantBot


def main():
    bot = QuantBot()
    bot.run()


if __name__ == "__main__":
    main()
