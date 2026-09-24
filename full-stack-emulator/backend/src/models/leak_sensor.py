from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class LeakSensorChannelConfig(BaseModel):
    stack: int = Field(default=3, ge=0)
    channel: int = Field(default=1, ge=1, le=16)


class LeakSensorItemConfig(BaseModel):
    id: str
    name: str
    output_channel: LeakSensorChannelConfig = Field(default_factory=LeakSensorChannelConfig)
    voltage: float = Field(default=0.0, ge=0.0, le=10.0)


class LeakSensorConfig(BaseModel):
    sensors: List[LeakSensorItemConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_assignments(self):
        used_ids = {}
        used_channels = {}

        for sensor in self.sensors:
            existing_id = used_ids.get(sensor.id)
            if existing_id is not None:
                raise ValueError(f"Leak sensor IDs must be unique. {existing_id} and {sensor.name} both use {sensor.id}.")
            used_ids[sensor.id] = sensor.name

            channel_key = (sensor.output_channel.stack, sensor.output_channel.channel)
            existing_channel = used_channels.get(channel_key)
            if existing_channel is not None:
                raise ValueError(
                    "Leak sensor output channels must be unique. "
                    f"{existing_channel} and {sensor.name} both use stack {sensor.output_channel.stack} "
                    f"channel {sensor.output_channel.channel}."
                )
            used_channels[channel_key] = sensor.name

        return self


class LeakSensorState(BaseModel):
    id: str
    name: str
    stack: int
    channel: int
    voltage: float
    available: bool
    error: Optional[str] = None


class LeakSensorRuntimeState(BaseModel):
    sensors: List[LeakSensorState] = Field(default_factory=list)
