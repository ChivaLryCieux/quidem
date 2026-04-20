# Quidem - 个人量化交易CTA系统

Quidem 是一个面向个人使用的 Python 量化交易CTA系统。它不是发布到 PyPI 的包或通用库，而是把实盘/模拟盘执行、终端交互、Redis 状态通道、邮件报告、交易所接入、仓位风控、回测研究和运行日志组织在同一个仓库里，方便日常迭代和复盘。

框架当前围绕 Binance 永续合约工作，但核心结构并不绑定某一个具体策略。策略可以替换，执行引擎、TUI、交易所接入、风控、报告和回测日志体系可以继续复用。

---

## 框架要点

### 1. 量化策略执行核心

交易执行核心位于 `core/engine/`，负责把行情数据、策略信号、风控判断和订单执行串起来。它使用普通 Python 类组织职责边界，通过 `ccxt`、`websocket-client`、`pandas`、`numpy` 等库把实时行情、特征计算和交易执行连接起来。

- `core/engine/bot.py`：主循环入口，负责连接交易所、预热历史数据、驱动实时 tick、刷新界面、发送心跳。
- `core/engine/trader.py`：交易执行器，负责开仓、平仓、持仓状态、纸盘成交、手续费估算、交易记录推送。
- `core/strategy/`：策略决策层，负责把 `DataFrame`、盘口和指标上下文转换为交易信号。
- `core/analysis/`：特征和指标层，基于 `pandas.Series`、`pandas.DataFrame` 和 `numpy` 数组做数据计算。

这部分的设计目标是让策略只关心“是否交易”，而执行层统一处理“如何交易、何时退出、如何记录”。

### 2. TUI 终端界面

终端界面位于 `core/ui/`，用于在本地直接观察机器人运行状态，不依赖 Web 后台。TUI 主要基于标准输出、ANSI 控制序列和 `colorama` 实现，兼容常见终端和 IDE 控制台。

- `core/ui/display.py`：输出启动信息、运行状态栏、开仓日志、平仓日志和错误提示。
- `core/ui/input.py`：处理键盘输入，结合 `msvcrt`、`termios`、`tty` 等标准库能力支持运行中暂停、继续和退出。
- 状态栏展示持仓方向、市场状态、关键指标、当前价格和浮动盈亏。
- 开平仓事件会用更醒目的终端输出，便于长期挂着运行时快速定位交易行为。

TUI 是这个框架的一个实用入口：不需要额外部署服务，也能看到交易系统是否正常工作。

### 3. 基于 Redis 的邮件系统

邮件系统由交易进程、Redis 队列和报告脚本组成，避免交易主循环直接承担邮件发送压力。这里使用 `redis` 作为轻量消息通道，`resend` 作为邮件发送 SDK，`schedule` 负责定时任务，`matplotlib` 负责生成权益曲线和交易内曲线图。

- 交易主进程把心跳写入 Redis：`bot_status_heartbeat`。
- 平仓后把交易记录写入 Redis：`trade_journal_pending`。
- `scripts/run_report.py` 定时消费 Redis 中的交易记录，生成 HTML 报告和 CSV 附件。
- `core/utils/reporting.py` 负责报告 HTML、权益曲线、交易明细和归档文件，内部使用 `pandas` 汇总交易、用 `matplotlib.figure.Figure` 绘图。
- `core/utils/mailer.py` 封装 Resend 邮件发送，可被报告或预警脚本复用。

这种结构的好处是交易进程和通知进程解耦：Redis 或邮件服务异常时，不会直接阻塞核心交易循环。

### 4. 交易所接入层

交易所接入层位于 `core/config/exchange.py`，封装 Binance Futures 的 REST API 和 WebSocket 数据流。REST 侧使用 `ccxt` 统一市场、余额、精度和下单接口；WebSocket 侧使用 `websocket-client` 订阅 K 线、深度和资金费率。

- REST API：通过 `ccxt.binance` 调用 `load_markets()`、`fetch_balance()`、`fetch_ohlcv()`、`create_market_order()`。
- WebSocket：通过 `websocket.WebSocketApp` 接收实时 K 线、盘口深度、mark price 和 funding rate。
- 代理支持：通过 `HTTP_PROXY`、`HTTPS_PROXY` 和 WebSocket proxy options 适配本地网络环境。
- 线程模型：`MarketDataStreamer` 继承 `threading.Thread`，用 `threading.Lock` 保护实时行情缓存。
- 模拟盘隔离：非实盘模式不会调用真实下单接口，而是记录 paper order，便于本地验证执行链路。

这层的目标是把外部交易所的不稳定性隔离起来，给策略和交易执行器提供稳定的数据和订单接口。

### 5. 仓位管理与风控体系

仓位管理与风控体系分布在 `core/engine/trader.py`、`core/risk/manager.py` 和 `core/risk/position.py`。它把订单数量、持仓状态、手续费、止盈止损、冷却期和熔断统一放在执行链路里处理。

- 仓位状态：使用字典或仓位辅助类维护 `size`、`entry_price`、`sl`、`tp`、`entry_time`、`leverage`。
- 下单数量：根据账户权益、仓位比例、杠杆和 taker fee 估算订单数量，再通过 `ccxt` 精度规则校正。
- 风控检查：`RiskManager` 负责资金费率风险、止盈止损、时间防御、冷却期和分级熔断。
- 动态保护：交易执行器维护最大浮盈，支持保本止损和追踪止损。
- 线程安全辅助：`core/risk/position.py` 使用 `threading.Lock` 保护仓位读写，适合后续扩展多线程监控。

这一层是框架长期运行的安全边界。策略可以变化，但仓位和风控规则应该稳定、可测试、可复盘。

### 6. 回测与日志系统

回测与日志系统用于离线验证和线上排查。回测代码放在 `backtest/`，日志配置放在 `core/utils/logging_config.py`。

- 回测引擎：`backtest/backtester.py` 复用 `core/` 中的策略、指标和风控模块，避免回测和实盘逻辑完全分叉。
- 数据处理：回测和分析脚本大量使用 `pandas`、`numpy`、`matplotlib`、`seaborn` 和 `statsmodels`。
- 模型实验：`hmmlearn`、`scikit-learn`、`joblib` 等库用于 HMM、聚类和模型持久化实验。
- 日志系统：使用 Python 标准库 `logging` 和 `logging.handlers.RotatingFileHandler`，同时支持终端彩色日志和滚动文件日志。
- 诊断脚本：`backtest/replay_5m_diagnostics.py` 可按历史窗口重放信号，并输出 CSV 和图表辅助复盘。

这部分让框架不只是能跑，还能在亏损、异常、网络问题或策略变更后定位原因。

### 7. 其他

其他辅助能力让这个仓库更接近完整的个人量化工作台。

- 配置加载：`core/config/settings.py` 使用 `python-dotenv` 读取 `.env`，并做基础运行前校验。
- 爆仓预警：`scripts/liquidation_alert.py` 使用 `requests` 轮询 Binance 强平订单 API，并通过邮件系统发送告警。
- 异步和网络实验：依赖中保留 `aiohttp`，适合后续扩展异步数据抓取或外部服务调用。
- 技术指标库：`core/analysis/indicators.py` 自维护常用指标实现，便于实盘和回测共享。
- 基础测试：`tests/` 使用 Python 标准库 `unittest` 覆盖风控、盘口分析、纸盘开平仓等核心行为。
- 研究资产：`backtest/` 中保留 PNG、CSV 和实验脚本，方便把策略研究和实盘框架放在同一个工作目录中。

---

## 项目结构

```text
Quidem/
├── run.py                         # 主入口，支持交互选择模式或命令行指定模式
├── requirements.txt               # Python 依赖
├── README.md
│
├── core/
│   ├── config/
│   │   ├── settings.py            # 默认配置、.env 加载、运行前校验
│   │   └── exchange.py            # Binance REST + WebSocket 接入
│   │
│   ├── engine/
│   │   ├── bot.py                 # 主循环，连接数据、策略、风控、交易和心跳
│   │   ├── trader.py              # 交易执行器，管理开仓/平仓/持仓/报告记录
│   │   └── alert_manager.py       # 运行中的告警辅助
│   │
│   ├── strategy/
│   │   ├── brain.py               # 策略大脑，维护历史数据并输出分析上下文
│   │   └── analyzers.py           # 信号生成和盘口分析
│   │
│   ├── analysis/
│   │   ├── indicators.py          # 技术指标实现
│   │   ├── feature_engineering.py # 特征工程
│   │   └── bocpd.py               # 研究型分析模块
│   │
│   ├── risk/
│   │   ├── manager.py             # 风控管理
│   │   └── position.py            # 仓位辅助
│   │
│   ├── ui/
│   │   ├── display.py             # TUI 输出
│   │   └── input.py               # 键盘输入
│   │
│   └── utils/
│       ├── logging_config.py      # 日志配置
│       ├── mailer.py              # 邮件发送封装
│       └── reporting.py           # 报告生成、CSV 导出、日线快照
│
├── scripts/
│   ├── run_report.py              # Redis 交易报告消费者和定时邮件任务
│   ├── liquidation_alert.py       # 爆仓量预警脚本
│   └── pretrain.py                # 数据预热/研究辅助脚本
│
├── backtest/                      # 回测、诊断和模型实验
└── tests/                         # 本地单元测试
```

---

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置 `.env`

模拟盘可以不配置 API key。实盘必须配置：

```env
BINANCE_API_KEY=your_api_key
BINANCE_SECRET=your_secret_key
```

如果需要邮件报告，再配置：

```env
ENABLE_MAIL_REPORT=true
RESEND_API_KEY=your_resend_api_key
MAIL_TO=foo@example.com,bar@example.com
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

### 3. 启动交易框架

```bash
python run.py      # 交互式选择模式
python run.py 1    # 模拟盘
python run.py 2    # 实盘
```

模式说明：

- `0`：退出
- `1`：模拟盘，适合调试执行链路
- `2`：实盘，会使用 Binance API 下单

### 4. 启动邮件报告服务

先确保 Redis 正在运行，并且 `.env` 中设置了 `ENABLE_MAIL_REPORT=true`。

```bash
python scripts/run_report.py
```

默认每天 11:00 和 23:00 发送报告。报告数据来自 Redis，而不是直接从交易主循环发送。

### 5. 启动爆仓预警

```env
ENABLE_LIQUIDATION_ALERT=true
ENABLE_MAIL_REPORT=true
RESEND_API_KEY=your_resend_api_key
MAIL_TO=foo@example.com

LIQUIDATION_ALERT_SYMBOL=SOLUSDT
LIQUIDATION_ALERT_WINDOW_SEC=300
LIQUIDATION_ALERT_THRESHOLD_USD=1000000
LIQUIDATION_ALERT_POLL_INTERVAL_SEC=30
LIQUIDATION_ALERT_COOLDOWN_SEC=900
```

```bash
python scripts/liquidation_alert.py
```

---

## 运行流程

```text
Binance WebSocket/REST
        |
        v
ExchangeService
        |
        v
StrategyBrain + Feature Engineering
        |
        v
SignalEngine
        |
        v
RiskManager
        |
        v
TradeExecutor
        |
        +--> TUI 状态输出
        +--> Binance 实盘订单 / Paper 纸盘订单
        +--> Redis 心跳与交易记录
                         |
                         v
                 ReportService + Resend
```

---

## 测试

运行本地单元测试：

```bash
python -m unittest discover -s tests
```

当前测试重点覆盖：

- 资金费率风控
- 熔断冷却
- 订单簿失衡与价差分析
- 模拟盘开仓、平仓、余额变化和订单记录

---

## 使用定位

这个项目适合继续作为个人量化交易工作台演进：

- 策略研究放在 `backtest/` 和 `core/strategy/`
- 实盘执行放在 `core/engine/`
- 运行观察放在 `core/ui/`
- 报告和通知放在 `core/utils/` 与 `scripts/`
- 参数管理放在 `core/config/settings.py`，敏感信息通过 `.env` 注入

后续扩展可以优先考虑：多交易对支持、持仓状态持久化、统一事件总线、回测和实盘共享订单模型、以及更完整的测试覆盖。
