from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StrictFloat

from src.controllers.grundfos_controller import grundfos_controller
from src.sensors.grundfos.emulator import PumpTransportError


class PumpValuePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: StrictFloat | None


router = APIRouter(prefix="/api/runtime/grundfos", tags=["Grundfos Pump"])


def call(action, *args):
    try:
        return action(*args)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except PumpTransportError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{device_id}/start")
def start_group(device_id: int):
    return call(grundfos_controller.start_group, device_id)


@router.post("/{device_id}/stop")
def stop_group(device_id: int):
    return call(grundfos_controller.stop_group, device_id)


@router.post("/{device_id}/values/{field}")
def set_value(device_id: int, field: str, payload: PumpValuePayload):
    return call(grundfos_controller.set_value, device_id, field, payload.value)
