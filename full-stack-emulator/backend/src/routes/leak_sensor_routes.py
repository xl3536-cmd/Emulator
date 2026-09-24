from fastapi import APIRouter
from pydantic import BaseModel

from src.controllers.leak_sensor_controller import leak_sensor_controller


class VoltagePayload(BaseModel):
    voltage: float


router = APIRouter(prefix="/api/runtime/leak-sensors", tags=["Leak Sensors"])


@router.post("/{sensor_id}/voltage")
def set_leak_sensor_voltage(sensor_id: str, payload: VoltagePayload):
    return leak_sensor_controller.set_voltage(sensor_id, payload.voltage)
