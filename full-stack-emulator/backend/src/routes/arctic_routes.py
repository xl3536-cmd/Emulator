from fastapi import APIRouter
from pydantic import BaseModel

from src.controllers.arctic_controller import arctic_controller


class ArcticRegisterPayload(BaseModel):
    value: float


router = APIRouter(prefix="/api/runtime/arctic-hp", tags=["Arctic HP"])


@router.post("/server/start")
def start_arctic_server():
    return arctic_controller.start_server()


@router.post("/server/stop")
def stop_arctic_server():
    return arctic_controller.stop_server()


@router.post("/{device_id}/registers/{address}")
def set_arctic_register(device_id: int, address: int, payload: ArcticRegisterPayload):
    return arctic_controller.set_register(device_id, address, payload.value)


@router.post("/{device_id}/reset")
def reset_arctic_device(device_id: int):
    return arctic_controller.reset_device(device_id)
