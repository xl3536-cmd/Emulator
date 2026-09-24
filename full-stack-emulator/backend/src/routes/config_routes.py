from fastapi import APIRouter

from src.controllers.config_controller import config_controller
from src.models.config import EmulatorConfig


router = APIRouter(prefix="/api/config", tags=["Config"])


@router.get("", response_model=EmulatorConfig)
def get_config():
    return config_controller.get_config()


@router.put("", response_model=EmulatorConfig)
def update_config(config: EmulatorConfig):
    return config_controller.update_config(config)
