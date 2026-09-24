from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from src.controllers.valve_controller import valve_controller


class VoltagePayload(BaseModel):
    voltage: Optional[float] = None


router = APIRouter(prefix="/api/runtime/valves", tags=["Valves"])


@router.post("/{valve_id}/input-override")
def set_valve_input_override(valve_id: str, payload: VoltagePayload):
    return valve_controller.set_input_override(valve_id, payload.voltage)
