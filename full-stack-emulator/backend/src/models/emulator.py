from typing import Any, Dict

from pydantic import BaseModel, Field

from src.models.arctic import ArcticHpConfig
from src.models.leak_sensor import LeakSensorConfig, LeakSensorRuntimeState
from src.models.rtd import RTDConfig, RTDState
from src.models.valves import ValveConfig, ValveRuntimeState


class EmulatorConfig(BaseModel):
    rtd: RTDConfig
    valves: ValveConfig
    leak_sensors: LeakSensorConfig
    arctic_hp: ArcticHpConfig
    ui: Dict[str, str] = Field(default_factory=dict)


class RuntimeSnapshot(BaseModel):
    rtd: RTDState
    valves: ValveRuntimeState
    leak_sensors: LeakSensorRuntimeState
    arctic_hp: Dict[str, Any]
