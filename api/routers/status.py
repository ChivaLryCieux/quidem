"""
状态查询路由
"""
from fastapi import APIRouter, Depends, HTTPException
from ..auth import verify_api_key
from ..services import BotService
from ..models.schemas import BotStatus, APIResponse

router = APIRouter(prefix="/status", tags=["状态监控"])

# 依赖注入
def get_bot_service():
    from ..main import bot_service
    return bot_service

@router.get("/current", response_model=BotStatus, summary="获取当前状态")
async def get_current_status(
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """
    获取机器人当前状态
    
    返回:
    - timestamp: 时间戳(毫秒)
    - balance: 账户余额
    - position_size: 持仓数量
    - price: 当前价格
    - regime: 市场状态
    - ai_conf: AI预测置信度
    - cluster: 聚类状态
    - hf_signal: 高频信号
    """
    status = service.get_current_status()
    if not status:
        raise HTTPException(status_code=404, detail="无法获取机器人状态,请检查Redis连接")
    
    return status

@router.get("/heartbeat", response_model=APIResponse, summary="心跳检测")
async def heartbeat(
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """
    检查机器人是否在线
    """
    status = service.get_current_status()
    
    if status:
        import time
        current_time = int(time.time() * 1000)
        time_diff = current_time - status.timestamp
        
        # 如果心跳超过10秒未更新,认为离线
        is_online = time_diff < 10000
        
        return APIResponse(
            success=True,
            message="在线" if is_online else "离线",
            data={
                "online": is_online,
                "last_update": status.timestamp,
                "time_diff_ms": time_diff
            }
        )
    else:
        return APIResponse(
            success=False,
            message="无法连接到机器人",
            data={"online": False}
        )
