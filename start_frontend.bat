@echo off
chcp 65001 >nul
echo ========================================
echo Q-Bot 前端应用启动脚本
echo ========================================
echo.

cd /d "%~dp0frontend"

echo [1/3] 检查依赖...
if not exist "node_modules" (
    echo 首次运行,正在安装依赖...
    call npm install
    if errorlevel 1 (
        echo 依赖安装失败!
        pause
        exit /b 1
    )
)

echo [2/3] 检查环境配置...
if not exist ".env.local" (
    echo 警告: 未找到 .env.local 文件
    echo 请复制 .env.example 为 .env.local 并配置服务器地址
    pause
    exit /b 1
)

echo [3/3] 启动开发服务器...
echo.
echo 前端应用将在 http://localhost:5173 启动
echo 按 Ctrl+C 停止服务
echo.

call npm run dev

pause
