# Q-Bot 前后端分离架构

本项目为Q-Bot量化交易机器人添加了完整的Web监控和控制界面。

## 项目结构

```
q-bot/
├── api/                    # 后端API服务(FastAPI)
├── frontend/              # 前端应用(React)
├── core/                  # QuantBot核心(原有)
├── run_api.py            # API启动脚本
├── start_api.sh          # Linux API启动脚本
├── start_frontend.bat    # Windows前端启动脚本
└── requirements_api.txt  # API依赖
```

## 快速开始

### 后端部署(Linux服务器)

1. 安装依赖:
```bash
pip install -r requirements_api.txt
```

2. 配置环境变量(编辑 `.env`):
```bash
API_KEY=your-secret-api-key-change-this
```

3. 启动服务:
```bash
chmod +x start_api.sh
./start_api.sh
```

或直接运行:
```bash
python run_api.py
```

### 前端运行(Windows本地)

1. 配置服务器地址(编辑 `frontend/.env.local`):
```bash
VITE_API_BASE_URL=http://YOUR_SERVER_IP:8000
VITE_WS_URL=ws://YOUR_SERVER_IP:8000/ws/realtime
VITE_API_KEY=your-secret-api-key-change-this
```

2. 双击运行 `start_frontend.bat`

或手动运行:
```bash
cd frontend
npm install
npm run dev
```

## 功能特性

### 后端API
- ✅ RESTful API接口
- ✅ WebSocket实时推送
- ✅ Redis数据集成
- ✅ API密钥认证
- ✅ CORS跨域支持
- ✅ 自动生成API文档

### 前端界面
- ✅ 实时状态监控
- ✅ 交易控制(启动/暂停/停止/平仓)
- ✅ 收益统计和图表
- ✅ 交易历史记录
- ✅ 暗色主题界面
- ✅ 响应式布局

## 技术栈

**后端**:
- FastAPI
- Redis
- Pydantic
- Uvicorn

**前端**:
- React 18
- Ant Design
- Zustand
- ECharts
- Axios

## 文档

- [完整部署指南](./walkthrough.md) - 详细的部署和使用说明
- [后端API文档](./api/README.md) - API服务说明
- [前端应用文档](./frontend/README.md) - 前端应用说明
- [API交互文档](http://YOUR_IP:8000/docs) - Swagger UI

## 安全提示

> ⚠️ **重要**: 
> 1. 务必修改默认的API密钥
> 2. 建议配置防火墙限制访问
> 3. 生产环境使用HTTPS
> 4. 所有关键操作都需要二次确认

## 故障排查

常见问题请参考 [部署指南](./walkthrough.md) 中的"故障排查"章节。

## 许可证

与Q-Bot主项目保持一致
