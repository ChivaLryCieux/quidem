"""
交易控制路由
"""
from fastapi import APIRouter, Depends, HTTPException
from ..auth import verify_api_key
from ..services import BotService
from ..models.schemas import ControlCommand, APIResponse

router = APIRouter(prefix="/control", tags=["交易控制"])

def get_bot_service():
    from ..main import bot_service
    return bot_service

@router.post("/command", response_model=APIResponse, summary="发送控制命令")
async def send_command(
    command: ControlCommand,
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """
    发送控制命令到机器人
    
    支持的命令:
    - start: 启动交易
    - stop: 停止交易
    - pause: 暂停交易
    - close_position: 强制平仓
    """
    success = service.send_control_command(command.action, command.params)
    
    if success:
        return APIResponse(
            success=True,
            message=f"命令 '{command.action}' 已发送",
            data={"action": command.action}
        )
    else:
        raise HTTPException(status_code=500, detail="发送命令失败,请检查Redis连接")

@router.post("/start", response_model=APIResponse, summary="启动交易")
async def start_trading(
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """启动交易机器人"""
    success = service.send_control_command("start")
    return APIResponse(
        success=success,
        message="启动命令已发送" if success else "发送失败"
    )

@router.post("/stop", response_model=APIResponse, summary="停止交易")
async def stop_trading(
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """停止交易机器人"""
    success = service.send_control_command("stop")
    return APIResponse(
        success=success,
        message="停止命令已发送" if success else "发送失败"
    )

@router.post("/pause", response_model=APIResponse, summary="暂停交易")
async def pause_trading(
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """暂停交易(不平仓)"""
    success = service.send_control_command("pause")
    return APIResponse(
        success=success,
        message="暂停命令已发送" if success else "发送失败"
    )

@router.post("/close-position", response_model=APIResponse, summary="强制平仓")
async def close_position(
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """强制平仓"""
    success = service.send_control_command("close_position")
    return APIResponse(
        success=success,
        message="平仓命令已发送" if success else "发送失败"
    )
