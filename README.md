# Quidem - 个人量化交易CTA系统

Quidem 是一个面向个人使用的 Python 量化交易CTA系统。它不是发布到 PyPI 的包或通用库，而是把实盘/模拟盘执行、终端交互、Web GUI、Redis 状态通道、邮件报告、交易所接入、仓位风控、回测研究和运行日志组织在同一个仓库里，方便日常迭代和复盘。

框架当前围绕 Binance 永续合约工作，但核心结构并不绑定某一个具体策略。策略可以替换，执行引擎、TUI、Web GUI、交易所接入、风控、报告和回测日志体系可以继续复用。

**v0.2.0 核心升级**: 多信号共识策略引擎、8项高级技术指标、HMM市场状态检测、Kelly Criterion动态仓位管理、蒙特卡洛策略模拟、完整绩效分析系统。

---

## 技术栈

### 后端 (Python)

| 类别 | 库 | 用途 |
| --- | --- | --- |
| 交易所接入 | `ccxt` | 统一交易所 REST API（市场、余额、下单） |
| 实时数据 | `websocket-client` | Binance WebSocket 行情流（K线、盘口、资金费率） |
| Web 服务器 | `fastapi` | REST API + WebSocket 实时推送 |
| ASGI 服务器 | `uvicorn` | 运行 FastAPI 应用 |
| 数据验证 | `pydantic` | API 请求/响应模型定义与验证 |
| 数据处理 | `pandas`, `numpy` | K线数据处理、技术指标计算 |
| 可视化 | `matplotlib`, `seaborn` | 报告图表、权益曲线 |
| 统计建模 | `statsmodels`, `hmmlearn`, `scikit-learn` | HMM 状态识别、聚类分析 |
| 消息队列 | `redis` | 交易记录与心跳的异步通道 |
| 邮件发送 | `resend` | 交易报告和告警邮件 |
| 定时任务 | `schedule` | 邮件报告定时发送 |
| 配置管理 | `python-dotenv` | `.env` 环境变量加载 |
| 终端 UI | `rich`, `colorama` | TUI 彩色输出、面板、表格 |
| HTTP 客户端 | `requests`, `aiohttp` | API 调用、数据抓取 |

### 前端 (Web GUI)

| 类别 | 库 | 用途 |
| --- | --- | --- |
| 构建工具 | `Vite` | 快速开发服务器与生产构建 |
| UI 框架 | `React 18` | 组件化用户界面 |
| 类型系统 | `TypeScript` | 静态类型检查 |
| 状态管理 | `Zustand` | 轻量级全局状态管理 |
| 样式方案 | `Tailwind CSS` | 原子化 CSS 框架 |
| K线图表 | `TradingView Lightweight Charts` | 专业金融图表（计划中） |
| WebSocket | 原生 `WebSocket API` | 实时数据接收 |

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

终端界面位于 `core/ui/`，使用 `Rich` 库实现现代化的终端显示效果。Rich 提供了丰富的文本格式化能力，包括彩色输出、面板、表格、样式等，同时保持良好的跨平台兼容性。

- `core/ui/display.py`：基于 Rich 的显示管理器，提供：
  - 启动面板：圆角边框、符号 Logo、模式和策略信息
  - 日志消息：带时间戳和级别标识的格式化输出（`✔` 成功、`●` 信息、`⚠` 警告、`✖` 错误）
  - 开仓日志：带颜色标识的入场信息面板（绿色=做多，红色=做空）
  - 平仓日志：盈亏高亮的出场信息面板
  - 状态栏：实时刷新的持仓状态、市场状态、MACD/ADX/Reversal 指标
- `core/ui/input.py`：处理键盘输入，结合 `msvcrt`、`termios`、`tty` 等标准库能力支持运行中暂停、继续和退出。

TUI 是这个框架的一个实用入口：不需要额外部署服务，也能看到交易系统是否正常工作。

### 2.5 Web GUI 界面

Web GUI 位于 `core/web/`（后端）和 `web/`（前端），提供基于浏览器的可视化界面。它与 TUI 并行工作，启动后自动打开浏览器，无需手动部署。

**后端架构** (`core/web/`)：

- `state.py`：线程安全的共享状态管理器，使用 `threading.Lock` 保护数据，在主循环和 Web 服务器之间传递行情、策略、持仓、交易和告警数据。支持订阅者模式，WebSocket 连接自动接收数据更新。
- `server.py`：基于 FastAPI 的 Web 服务器，提供：
  - REST API：`/api/status`（完整快照）、`/api/market`（行情）、`/api/strategy`（策略）、`/api/position`（持仓）、`/api/trades`（交易历史）、`/api/alerts`（告警历史）
  - WebSocket：`/ws` 端点，实时推送数据变更，支持心跳检测和自动重连
  - 静态文件服务：自动提供前端构建产物
  - Swagger 文档：`/api/docs` 自动生成 API 文档
- `runner.py`：Web 线程管理器，在独立守护线程中启动 uvicorn 服务器，使用 `webbrowser` 库自动打开浏览器，支持优雅关闭。
- `models.py`：Pydantic 数据模型，定义 API 请求/响应结构，提供类型安全和自动验证。

**前端架构** (`web/`)：

- 技术栈：Vite + React 18 + TypeScript + Tailwind CSS
- 状态管理：Zustand，轻量级且支持 TypeScript 类型推断
- 组件结构：
  - `PriceHeader`：价格、余额、盈亏、资金费率概览
  - `StrategyStatus`：市场状态（强涨/震荡/强跌）、ADX/MACD/Reversal 指标、SuperTrend 多周期对比
  - `PositionPanel`：持仓方向、入场价、止损止盈、浮动盈亏
  - `OrderBookPanel`：盘口深度可视化，买卖挂单对比
  - `TradeHistory`：开仓/平仓记录表格
  - `AlertPanel`：BOCPD/KDJ/ADX/MACD 告警历史
- WebSocket Hook：自动连接、心跳保活、断线重连

**数据流**：

```text
Bot 主循环 ──> WebState (threading.Lock) ──> FastAPI WebSocket ──> 浏览器
     │                                              │
     └──> TUI (stdout)                         React 组件更新
```

**Web GUI 功能**：
- 实时价格和行情数据展示（2秒刷新）
- 策略状态和市场状态显示（趋势/震荡/方向）
- 持仓详情和浮动盈亏（入场价/止损/止盈）
- 盘口深度可视化（买卖挂单对比）
- 交易历史记录（开仓/平仓/盈亏）
- 告警历史查看（BOCPD 变点、KDJ 超买超卖、ADX 强趋势、MACD 交叉）
- WebSocket 自动重连（3秒间隔）
- 暗色主题，适合长时间监控

启动后会自动打开浏览器访问 `http://127.0.0.1:8000`，同时 TUI 终端界面继续工作。两者共享同一份数据，互不干扰。

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

### 8. v0.2.0 量化分析升级

v0.2.0 在策略信号、仓位管理和分析能力上做了全面升级，目标是提高盈利能力和策略鲁棒性。

**8.1 多信号共识引擎** (`core/strategy/analyzers.py`)

信号生成从"单一条件触发"升级为"多指标加权投票"系统:

- 11个独立信号源投票: ADX+VWAP方向、快/标准MACD、SuperTrend(5m/15m)、Ichimoku云、StochasticRSI、OBV背离、CCI、CMF资金流、Parabolic SAR、VWMA偏差
- 加权求和后与自适应阈值比较: 趋势行情阈值=3.0(积极)，震荡行情阈值=5.0(保守)
- 强趋势(ADX>30)自动降低阈值20%
- 强共识信号自动获得杠杆加成(+10%~15%)
- 日志显示每个投票指标和最终得分，方便复盘

**8.2 高级技术指标** (`core/analysis/indicators.py`)

新增8个指标(总计20+):

| 指标 | 类型 | 信号含义 |
| --- | --- | --- |
| Ichimoku Cloud | 趋势 | 云上/云下/TK交叉 |
| Stochastic RSI | 超买超卖 | K/D交叉 |
| OBV | 量价 | 量价背离、趋势斜率 |
| CCI | 周期 | 超买(>100)/超卖(<-100) |
| Williams %R | 超买超卖 | >-20超买/<-80超卖 |
| Parabolic SAR | 趋势 | 多/空方向 |
| VWMA | 量价 | VWMA与SMA偏差 |
| CMF | 资金流 | 买方/卖方主导 |

**8.3 Kelly Criterion动态仓位** (`core/risk/position_sizer.py`)

仓位大小不再是固定比例，而是根据历史表现动态调整:

- Kelly公式: `f* = W - (1-W)/R`，使用半Kelly降低波动
- 波动率自适应杠杆: `leverage = base * (target_vol / current_vol)`，ATR高时降杠杆
- 回撤缩仓: 5%回撤开始线性缩减，20%回撤时缩至20%仓位
- 信号强度加权: 强共识信号使用更大仓位

**8.4 HMM市场状态检测** (`core/analysis/regime.py`)

使用Hidden Markov Model自动识别4种市场状态:

- 状态0: 低波动震荡 → 均值回归策略，收紧止盈止损
- 状态1: 上升趋势 → 趋势跟随，放宽止盈，降低ADX门槛
- 状态2: 下降趋势 → 趋势跟随(做空)，同上
- 状态3: 高波动 → 防御模式，大幅减仓，收紧止盈

每50根K线自动重训练，输入特征: 对数收益率+波动率+成交量变化+趋势强度。

**8.5 绩效分析系统** (`core/analysis/performance.py`)

回测报告现在包含完整的机构级绩效指标:

- 风险调整: Sharpe Ratio, Sortino Ratio, Calmar Ratio
- 盈利质量: Profit Factor, Payoff Ratio, Expectancy
- 回撤分析: 最大回撤(绝对值+百分比), Recovery Factor
- 连续统计: 最大连胜/连亏, 破产风险估计
- 方向分析: 多/空分别的胜率和盈亏

**8.6 蒙特卡洛模拟** (`core/analysis/monte_carlo.py`)

回测后自动运行1000次蒙特卡洛模拟:

- Bootstrap重采样: 打乱交易顺序模拟不同市场路径
- 破产概率: 基于历史交易分布估算
- 置信区间: 5%-95%分位的收益和回撤范围
- 仓位优化: 测试5%-40%仓位的风险收益特征
- Sharpe分布: 策略夏普比率的置信区间

---

## 快速开始

### 0. 项目结构

```text
Quidem/
├── run.py                         # 主入口，支持交互选择模式或命令行指定模式
├── pyproject.toml                 # 项目元信息与依赖声明，支持 pip install -e .
├── requirements.txt               # Python 依赖（与 pyproject.toml 保持一致）
├── .gitignore                     # 忽略 __pycache__/.env/logs/研究资产等
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
│   │   ├── indicators.py          # 技术指标实现 (20+指标)
│   │   ├── feature_engineering.py # 特征工程 (20维特征向量)
│   │   ├── bocpd.py               # BOCPD变点检测
│   │   ├── regime.py              # HMM市场状态检测 (4状态)
│   │   ├── performance.py         # 绩效分析 (Sharpe/Sortino/Calmar)
│   │   └── monte_carlo.py         # 蒙特卡洛策略模拟
│   │
│   ├── risk/
│   │   ├── manager.py             # 风控管理
│   │   ├── position.py            # 仓位辅助
│   │   └── position_sizer.py      # Kelly Criterion动态仓位管理
│   │
│   ├── ui/
│   │   ├── display.py             # TUI 输出
│   │   └── input.py               # 键盘输入
│   │
│   ├── web/                       # Web GUI 后端
│   │   ├── __init__.py
│   │   ├── state.py               # 线程安全的共享状态管理
│   │   ├── server.py              # FastAPI 服务器 (REST + WebSocket)
│   │   ├── runner.py              # Web 线程管理器
│   │   ├── models.py              # Pydantic 数据模型
│   │   └── static/                # 前端构建产物 (自动生成)
│   │
│   └── utils/
│       ├── logging_config.py      # 日志配置
│       ├── mailer.py              # 邮件发送封装
│       └── reporting.py           # 报告生成、CSV 导出、日线快照
│
├── web/                           # Web GUI 前端 (Vite + React + TS)
│   ├── src/
│   │   ├── components/            # React 组件
│   │   ├── hooks/                 # 自定义 Hooks
│   │   ├── stores/                # Zustand 状态管理
│   │   └── types/                 # TypeScript 类型定义
│   ├── package.json
│   └── vite.config.ts
│
├── scripts/
│   ├── run_report.py              # Redis 交易报告消费者和定时邮件任务
│   ├── liquidation_alert.py       # 爆仓量预警脚本
│   └── pretrain.py                # 数据预热/研究辅助脚本
│
├── backtest/                      # 回测、诊断和模型实验（PNG/CSV/PKL 为研究产物）
└── tests/                         # 本地单元测试
```

> `__pycache__/`、日志、研究资产 PNG/CSV/PKL 都在 `.gitignore` 中被忽略，不会进入版本控制。

### 1. 安装依赖

推荐方式（一次性把 `core` 安装为可导入包，`scripts/` 脱离根目录也能 `from core.xxx import ...`）：

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .                   # 会读取 pyproject.toml 并安装所有依赖
```

传统方式仍保留：

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置 `.env`

在项目根目录创建 `.env` 文件。模拟盘可以不配置 API key。实盘必须配置：

```env
BINANCE_API_KEY=your_api_key
BINANCE_SECRET=your_secret_key
```

**完整环境变量参考**（写在 `.env` 中即生效，不写则使用 `core/config/settings.py` 里的默认值）：

| 分组 | 变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 代理 | `PROXY_ENABLED` | `True` | 是否启用代理访问交易所 |
| 代理 | `PROXY_HOST` | `127.0.0.1` | 代理主机 |
| 代理 | `PROXY_PORT` | `7890` | 代理端口 |
| 交易所 | `BINANCE_API_KEY` | — | 实盘必需 |
| 交易所 | `BINANCE_SECRET` | — | 实盘必需 |
| 交易标的 | `SYMBOL` | `SOL/USDT` | 交易对 |
| 交易标的 | `TIMEFRAME_SIGNAL` | `5m` | 主信号周期（kline） |
| 交易标的 | `TIMEFRAME_TREND` | `15m` | 趋势过滤周期 |
| 交易标的 | `TIMEFRAME_MACRO` | `1h` | 宏观趋势周期 |
| 资金管理 | `PAPER_BALANCE` | `100.0` | 模拟盘初始余额（USDT） |
| 资金管理 | `MIN_LEVERAGE` | `5.0` | 允许的最小杠杆 |
| 资金管理 | `MAX_LEVERAGE` | `10.0` | 允许的最大杠杆 |
| 资金管理 | `DEFAULT_LEVERAGE` | `10.0` | 默认杠杆 |
| 资金管理 | `POSITION_ALLOC_RATIO` | `0.20` | 单笔仓位占账户比例 |
| 资金管理 | `TAKER_FEE_RATE` | `0.0005` | taker 手续费率估算 |
| 策略 | `BAILOUT_ON_NTH_FLIP` | `99` | 盈利翻转多少次触发离场（默认禁用） |
| 策略 | `MIN_ATR_PCT` | `0.0020` | ATR 下限（用于保护入场） |
| 策略 | `MIN_TP_DISTANCE` | `0.012` | 最小止盈距离（相对价格） |
| 策略 | `MAX_SL_DISTANCE` | `0.004` | 最大止损距离（相对价格） |
| 微结构 | `OBI_THRESHOLD_TREND` | `-0.2` | 盘口失衡阈值（趋势侧） |
| 微结构 | `OBI_THRESHOLD_BREAKOUT` | `0.1` | 盘口失衡阈值（突破侧） |
| 微结构 | `MAX_SPREAD_PCT` | `0.001` | 最大允许买卖价差（相对） |
| 邮件报告 | `ENABLE_MAIL_REPORT` | `False` | 启用邮件报告（需 Redis 运行） |
| 邮件报告 | `MAIL_FROM` | — | 发件人，例如 `CTA q-bot <report@your-domain.com>` |
| 邮件报告 | `MAIL_TO` | — | 收件人，多个以英文逗号分隔 |
| 邮件报告 | `RESEND_API_KEY` | — | Resend API Key |
| 邮件报告 | `REDIS_HOST` | `localhost` | Redis 主机 |
| 邮件报告 | `REDIS_PORT` | `6379` | Redis 端口 |
| 邮件报告 | `REDIS_DB` | `0` | Redis DB 编号 |
| 邮件报告 | `REPORT_ARCHIVE_DIR` | `~/quant_archive` | 报告归档目录 |
| 爆仓预警 | `ENABLE_LIQUIDATION_ALERT` | `False` | 启用爆仓预警 |
| 爆仓预警 | `LIQUIDATION_ALERT_SYMBOL` | `SOLUSDT` | 监听的交易对 |
| 爆仓预警 | `LIQUIDATION_ALERT_WINDOW_SEC` | `300` | 汇总窗口（秒） |
| 爆仓预警 | `LIQUIDATION_ALERT_THRESHOLD_USD` | `1000000` | 触发阈值（USD） |
| 爆仓预警 | `LIQUIDATION_ALERT_POLL_INTERVAL_SEC` | `30` | 轮询间隔（秒） |
| 爆仓预警 | `LIQUIDATION_ALERT_COOLDOWN_SEC` | `900` | 触发后的冷却期（秒） |
| 日志 | `LOG_LEVEL` | `INFO` | 日志等级 |
| 日志 | `LOG_DIR` | `logs` | 日志目录 |
| 日志 | `LOG_FILE` | `quant_bot.log` | 日志文件名 |
| 日志 | `LOG_TO_CONSOLE` | `True` | 是否同时输出到控制台 |
| Web GUI | `WEB_ENABLED` | `True` | 启用 Web GUI 界面 |
| Web GUI | `WEB_HOST` | `127.0.0.1` | Web 服务器监听地址 |
| Web GUI | `WEB_PORT` | `8000` | Web 服务器端口 |
| Web GUI | `WEB_AUTO_OPEN` | `True` | 启动时自动打开浏览器 |

### 3. 启动交易框架

```bash
python run.py      # 交互式选择模式
python run.py 1    # 模拟盘（Paper）
python run.py 2    # 实盘（Live）
```

模式说明：

- `0`：退出
- `1`：模拟盘，适合调试执行链路
- `2`：实盘，会使用 Binance API 下单

启动后会同时运行 TUI 终端界面和 Web GUI（如果已构建前端并启用）。Web GUI 默认地址：`http://127.0.0.1:8000`

如果执行了 `pip install -e .`，也可以直接调用入口脚本：

```bash
quidem-bot        # 等效于 python run.py
```

### 4. 构建 Web GUI 前端（可选）

如果需要使用 Web GUI 界面，需要先构建前端：

```bash
cd web
npm install
npm run build
cd ..
```

构建产物会自动输出到 `core/web/static/`，FastAPI 服务器会自动提供静态文件服务。

开发模式（前端热重载）：

```bash
cd web
npm run dev
```

然后在另一个终端启动交易框架，前端开发服务器会自动代理 API 请求到后端。

### 5. 启动邮件报告服务

先确保 Redis 正在运行，并且 `.env` 中设置了 `ENABLE_MAIL_REPORT=true`。

```bash
python scripts/run_report.py
```

默认每天 11:00 和 23:00 发送报告。报告数据来自 Redis，而不是直接从交易主循环发送。

### 6. 启动爆仓预警

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
        +--> TUI 状态输出 (终端)
        +--> WebState --> FastAPI WebSocket --> Web GUI (浏览器)
        +--> Binance 实盘订单 / Paper 纸盘订单
        +--> Redis 心跳与交易记录
                         |
                         v
                 ReportService + Resend
```

**线程模型**：

```text
主线程 (Bot.run)
    ├── 交易所连接 & 数据预热
    ├── 主循环 (tick)
    │   ├── 行情数据更新
    │   ├── 策略分析
    │   ├── 交易执行
    │   ├── TUI 更新 (stdout)
    │   └── WebState 更新 (threading.Lock)
    └── 用户输入监听

WebSocket 线程 (MarketDataStreamer)
    └── Binance WebSocket 行情流

Web 服务器线程 (WebRunner, daemon)
    └── uvicorn (FastAPI)
        ├── REST API 处理
        └── WebSocket 推送
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

## 常见问题 FAQ

**Q1：启动时报 `WS Connection Timeout (30s)`，是什么原因？**

大概率是本地代理未启动或端口不对。检查以下三点：

- `PROXY_ENABLED=true` 时，代理必须在 `PROXY_HOST:PROXY_PORT`（默认 `127.0.0.1:7890`）可用。
- 测试：`curl -x http://127.0.0.1:7890 https://api.binance.com/api/v3/ping` 应返回 `{}`。
- 如果不使用代理，在 `.env` 中设置 `PROXY_ENABLED=false`。

**Q2：为什么邮件报告不发送？**

- 必须同时设置 `ENABLE_MAIL_REPORT=true`、`RESEND_API_KEY=...`、`MAIL_TO=...`。
- Redis 必须在运行，并且 `REDIS_HOST` / `REDIS_PORT` 正确。
- `scripts/run_report.py` 是独立进程，需要与 `run.py` 同时运行（它从 Redis 的 `trade_journal_pending` 列表消费）。

**Q3：Paper 模式与 Live 模式有什么区别？**

- Paper：不会调用真实下单接口，用模拟的 `paper_orders` 记录，便于本地调试验证执行链路。
- Live：会通过 `ccxt.binance` 调用 REST API 下单，请确认 API Key 有交易权限并绑定白名单 IP。

**Q4：为什么要 `pip install -e .` 而不是 `pip install -r requirements.txt`？**

- 两者都能安装依赖。但 `pip install -e .` 会额外把 `core/` 注册为包，使得 `python scripts/run_report.py` 无论在哪个工作目录下都能正确执行 `from core.xxx import ...`，避免 `ModuleNotFoundError`。

**Q5：研究资产（PNG / CSV / PKL）会提交到版本库吗？**

不会。`.gitignore` 已忽略 `*.png`、`*.csv`、`*.pkl` 以及 `__pycache__/`、`.env`、`logs/` 等。

**Q6：Web GUI 无法访问怎么办？**

检查以下几点：

- 确认已构建前端：`cd web && npm install && npm run build`
- 确认 `.env` 中 `WEB_ENABLED=true`（默认已启用）
- 确认端口未被占用：默认使用 `8000` 端口，可通过 `WEB_PORT` 修改
- 查看启动日志是否有 `Web GUI: http://127.0.0.1:8000` 输出
- 如果前端未构建，访问根路径会显示提示页面

**Q7：Web GUI 数据不更新怎么办？**

- 检查浏览器控制台是否有 WebSocket 连接错误
- WebSocket 连接会自动重连（3秒间隔），网络恢复后会自动同步
- 确认交易主循环正常运行（TUI 有数据输出）

**Q8：如何在开发模式下使用 Web GUI？**

```bash
# 终端 1：启动前端开发服务器（支持热重载）
cd web && npm run dev

# 终端 2：启动交易框架
python run.py 1
```

前端开发服务器会自动代理 `/api` 和 `/ws` 请求到后端 `http://127.0.0.1:8000`。

---

## 使用定位

这个项目适合继续作为个人量化交易工作台演进：

- 策略研究放在 `backtest/` 和 `core/strategy/`
- 实盘执行放在 `core/engine/`
- 运行观察放在 `core/ui/`（TUI）和 `core/web/` + `web/`（Web GUI）
- 报告和通知放在 `core/utils/` 与 `scripts/`
- 参数管理放在 `core/config/settings.py`，敏感信息通过 `.env` 注入

后续扩展可以优先考虑：多交易对支持、持仓状态持久化、统一事件总线、回测和实盘共享订单模型、K线图表集成、以及更完整的测试覆盖。
