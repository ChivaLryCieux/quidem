#!/bin/bash

echo "========================================"
echo "Q-Bot API服务启动脚本"
echo "========================================"
echo ""

cd "$(dirname "$0")"

echo "[1/3] 检查Python依赖..."
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "正在安装依赖..."
    pip3 install -r requirements_api.txt
    if [ $? -ne 0 ]; then
        echo "依赖安装失败!"
        exit 1
    fi
fi

echo "[2/3] 检查Redis连接..."
if ! redis-cli ping > /dev/null 2>&1; then
    echo "警告: Redis未运行或无法连接"
    echo "请确保Redis服务已启动: sudo systemctl start redis"
    read -p "是否继续? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "[3/3] 启动API服务..."
echo ""
echo "API服务将在 http://0.0.0.0:8000 启动"
echo "API文档: http://YOUR_IP:8000/docs"
echo "按 Ctrl+C 停止服务"
echo ""

python3 run_api.py
