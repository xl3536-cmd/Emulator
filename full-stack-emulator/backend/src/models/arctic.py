from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ArcticPortConfig(BaseModel):
    serial_file: str = "/dev/ttyACM0"
    timeout: float = Field(default=1.5, gt=0.0)
    baudrate: int = Field(default=2400, ge=1)
    bytesize: int = Field(default=8, ge=5, le=8)
    parity: Literal["N", "E", "O"] = "E"
    stopbits: int = Field(default=1, ge=1, le=2)


class ArcticDeviceConfig(BaseModel):
    device_id: int = Field(ge=1)
    unit_id: int = Field(ge=1)
    name: str
    display_side: Literal["left", "right"] = "left"
    esp32_ip: str = ""


class ArcticHpConfig(BaseModel):
    port: ArcticPortConfig = Field(default_factory=ArcticPortConfig)
    devices: List[ArcticDeviceConfig]


class ArcticRegisterState(BaseModel):
    address: int
    name: str
    value: float
    raw: int
    unit: str
    note: str
    signed: bool
    scale: float
    access: Literal["read_only", "writable"]
    manual_editable: bool
    bitfield_text: Optional[str] = None


class ArcticDeviceState(BaseModel):
    device_id: int
    unit_id: int
    name: str
    display_side: str
    esp32_ip: str
    registers: List[ArcticRegisterState]


class ArcticServerState(BaseModel):
    running: bool
    transport_available: bool
    port: str
    baudrate: int
    message: str
