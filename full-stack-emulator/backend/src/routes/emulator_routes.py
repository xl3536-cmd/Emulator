from fastapi import APIRouter

from src.controllers.emulator_controller import emulator_controller


router = APIRouter(prefix="/api/runtime", tags=["Runtime"])


@router.get("")
def get_runtime_snapshot():
    return emulator_controller.get_snapshot()
