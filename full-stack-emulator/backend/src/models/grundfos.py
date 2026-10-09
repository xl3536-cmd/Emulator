"""Saved pump settings use the original MS/TP engine's configuration format."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from grundfos_engine.group_config import validate_devices


class PumpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PumpIdentity(PumpModel):
    id: int = Field(default=1, ge=1, le=1000000)
    name: str = "Grundfos Pump 1"
    device_id: int = Field(default=227011, ge=0, le=4194302)
    mac: int = Field(default=11, ge=0, le=127)


class PumpInitial(PumpModel):
    bus_control: bool = False
    control_mode: Literal[1, 2, 3, 4, 5, 6, 9, 12] = 1
    operating_mode: Literal[1, 2, 3, 4] = 2
    setpoint: float = Field(default=50, ge=0, le=100)
    fault_code: int = Field(default=0, ge=0, le=65535)
    warning_code: int = Field(default=0, ge=0, le=65535)
    operating_hours: float = Field(default=0, ge=0, le=10000000)
    on_hours: float = Field(default=0, ge=0, le=10000000)


class PumpReadings(PumpModel):
    flow_gpm: float = Field(default=40, ge=0, le=1000000)
    pressure_psi: float = Field(default=15, ge=0, le=1000000)
    power_w: float = Field(default=150, ge=0, le=1000000)
    current_a: float = Field(default=1.2, ge=0, le=1000000)
    temperature_c: float = Field(default=23, ge=-273.15, le=1000)
    remote_temperature_c: float = Field(default=24, ge=-273.15, le=1000)
    electronics_temperature_c: float = Field(default=35, ge=-273.15, le=1000)


class GrundfosDeviceConfig(PumpModel):
    serial_port: str = Field(default="/dev/ttyUSB0", min_length=1)
    baud: Literal[9600, 19200, 38400, 76800] = 9600
    max_master: int = Field(default=127, ge=1, le=127)
    max_info_frames: int = Field(default=1, ge=1, le=255)
    router_mac: int = Field(default=10, ge=0, le=127)
    pump: PumpIdentity = Field(default_factory=PumpIdentity)
    initial: PumpInitial = Field(default_factory=PumpInitial)
    readings: PumpReadings = Field(default_factory=PumpReadings)


class GrundfosConfig(PumpModel):
    devices: list[GrundfosDeviceConfig] = Field(default_factory=lambda: [GrundfosDeviceConfig()])

    @model_validator(mode="after")
    def validate_groups(self):
        validate_devices([device.model_dump() for device in self.devices])
        return self
