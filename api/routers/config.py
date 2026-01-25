"""
配置管理路由
"""
from fastapi import APIRouter, Depends, HTTPException
from ..auth import verify_api_key
from ..services import BotService
from ..models.schemas import ConfigUpdate, APIResponse

router = APIRouter(prefix="/config", tags=["配置管理"])

def get_bot_service():
    from ..main import bot_service
    return bot_service

@router.get("/get", response_model=APIResponse, summary="获取配置")
async def get_config(
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """获取当前配置"""
    config = service.get_config()
    
    if config:
        return APIResponse(
            success=True,
            message="配置获取成功",
            data=config
        )
    else:
        # 返回默认配置
        from core.config.settings import Config
        default_config = {
            "leverage": Config.MAX_LEVERAGE,
            "risk_appetite": Config.RISK_APPETITE,
            "symbol": Config.SYMBOL,
            "timeframe": Config.TIMEFRAME
        }
        return APIResponse(
            success=True,
            message="返回默认配置",
            data=default_config
        )

@router.post("/update", response_model=APIResponse, summary="更新配置")
async def update_config(
    config: ConfigUpdate,
    service: BotService = Depends(get_bot_service),
    api_key: str = Depends(verify_api_key)
):
    """
    更新配置(需要重启机器人生效)
    
    可更新参数:
    - leverage: 杠杆倍数(1-20)
    - risk_appetite: 风险偏好(0.01-0.1)
    """
    # 只更新非None的字段
    update_data = config.dict(exclude_none=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="没有提供任何配置更新")
    
    success = service.update_config(update_data)
    
    if success:
        return APIResponse(
            success=True,
            message="配置已更新,重启机器人后生效",
            data=update_data
        )
    else:
        raise HTTPException(status_code=500, detail="配置更新失败")
