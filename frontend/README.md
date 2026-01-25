# Q-Bot 前端应用

基于React + Ant Design的量化交易机器人监控界面

## 快速开始

### 1. 安装依赖
```bash
npm install
```

### 2. 配置环境变量
复制 `.env.example` 为 `.env.local`,并修改:
```bash
VITE_API_BASE_URL=http://YOUR_SERVER_IP:8000
VITE_WS_URL=ws://YOUR_SERVER_IP:8000/ws/realtime
VITE_API_KEY=your-secret-api-key-change-this
```

### 3. 启动开发服务器
```bash
npm run dev
```

应用将在 `http://localhost:5173` 启动

## 功能特性

- ✅ 实时状态监控
- ✅ 交易控制(启动/暂停/停止/平仓)
- ✅ 收益统计和图表
- ✅ 交易历史记录
- ✅ WebSocket实时推送
- ✅ 暗色主题界面

## 技术栈

- React 18
- Ant Design
- Zustand (状态管理)
- ECharts (图表)
- Axios (HTTP客户端)
- React Router (路由)

## 构建生产版本

```bash
npm run build
npm run preview
```
