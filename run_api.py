"""
API服务启动脚本
"""
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import uvicorn
    from api.config import APIConfig
    
    print(f"正在启动Q-Bot API服务...")
    print(f"服务地址: http://{APIConfig.API_HOST}:{APIConfig.API_PORT}")
    print(f"API文档: http://{APIConfig.API_HOST}:{APIConfig.API_PORT}/docs")
    print(f"WebSocket: ws://{APIConfig.API_HOST}:{APIConfig.API_PORT}/ws/realtime")
    print(f"\n按 Ctrl+C 停止服务\n")
    
    uvicorn.run(
        "api.main:app",
        host=APIConfig.API_HOST,
        port=APIConfig.API_PORT,
        reload=False,
        log_level="info"
    )
