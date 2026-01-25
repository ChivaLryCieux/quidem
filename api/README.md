# Q-Bot API服务部署指南

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements_api.txt
```

### 2. 配置环境变量
编辑 `.env` 文件,添加:
```
API_KEY=your-secret-api-key-change-this
```

### 3. 启动服务
```bash
python run_api.py
```

服务将在 `http://0.0.0.0:8000` 启动

## API文档
- Swagger UI: http://YOUR_IP:8000/docs
- ReDoc: http://YOUR_IP:8000/redoc

## 生产部署

使用systemd管理服务,参考 `walkthrough.md` 中的详细说明。
