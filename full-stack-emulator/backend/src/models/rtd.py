from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class CsvPlaybackConfig(BaseModel):
    fast_interval_seconds: float = Field(default=1.0, ge=1.0)
    slow_interval_seconds: float = Field(default=60.0, ge=1.0)
    loop: bool = True

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_millisecond_fields(cls, data: Any):
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        if "fast_interval_seconds" not in migrated and "fast_interval_ms" in migrated:
            migrated["fast_interval_seconds"] = float(migrated["fast_interval_ms"]) / 1000.0
        if "slow_interval_seconds" not in migrated and "slow_interval_ms" in migrated:
            migrated["slow_interval_seconds"] = float(migrated["slow_interval_ms"]) / 1000.0
        return migrated


class RTDSensorConfig(BaseModel):
    sensor_name: str
    board_index: int = Field(ge=0)
    position: int = Field(default=1, ge=1)
    bit_width: Literal[5, 8] = 5
    logical_stack: Optional[int] = Field(default=None, ge=0)
    logical_channel: Optional[int] = Field(default=None, ge=1)
    min_res_ohms: float = 95.0
    max_res_ohms: float = 150.0
    temp_min_c: float = -10.0
    temp_max_c: float = 80.0
    res_step_ohms: float = Field(default=2.0, gt=0.0)
    use_custom_equation: bool = False
    custom_equation_a: Optional[float] = None
    custom_equation_b: Optional[float] = None
    output_temp_c: Optional[float] = None

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.max_res_ohms < self.min_res_ohms:
            raise ValueError(f"{self.sensor_name}: max_res_ohms must be greater than or equal to min_res_ohms")
        if self.temp_max_c == self.temp_min_c:
            raise ValueError(f"{self.sensor_name}: temp_max_c must differ from temp_min_c")
        return self


class RTDConfig(BaseModel):
    board_count: int = Field(default=24, ge=1, le=200)
    invert_bits: bool = False
    reverse_byte_order: bool = True
    playback: CsvPlaybackConfig = Field(default_factory=CsvPlaybackConfig)
    sensors: List[RTDSensorConfig]

    @model_validator(mode="after")
    def validate_sensor_layout(self):
        used_positions = {}
        used_board_indexes = {}

        for sensor in self.sensors:
            if sensor.position in used_positions:
                other = used_positions[sensor.position]
                raise ValueError(
                    f"RTD positions must be unique. {other} and {sensor.sensor_name} both use position {sensor.position}."
                )
            used_positions[sensor.position] = sensor.sensor_name

            if sensor.board_index in used_board_indexes:
                other = used_board_indexes[sensor.board_index]
                raise ValueError(
                    f"RTD board_index values must be unique. {other} and {sensor.sensor_name} both use board_index {sensor.board_index}."
                )
            used_board_indexes[sensor.board_index] = sensor.sensor_name

        highest_board_index = max((sensor.board_index for sensor in self.sensors), default=-1)
        highest_position = max((sensor.position for sensor in self.sensors), default=0)
        self.board_count = max(self.board_count, highest_board_index + 1, highest_position)
        return self


class CsvPlaybackState(BaseModel):
    loaded: bool = False
    loaded_filename: Optional[str] = None
    playing: bool = False
    row_index: int = -1
    row_count: int = 0
    mode: Literal["fast", "slow"] = "fast"
    last_timestamp: Optional[str] = None
    header: List[str] = Field(default_factory=list)
    matched_rtd_columns: Dict[str, str] = Field(default_factory=dict)
    matched_valve_columns: Dict[str, str] = Field(default_factory=dict)
    slow_reason: Optional[Literal["runtime", "csv_valve_change"]] = None
    valve_transitions: Dict[str, str] = Field(default_factory=dict)


class RTDState(BaseModel):
    board_count: int
    invert_bits: bool
    reverse_byte_order: bool
    hardware_available: bool
    hardware_error: Optional[str] = None
    output_source: Literal["manual", "csv", "override"] = "manual"
    board_bits: List[List[int]]
    frame_bytes: List[int]
    playback: CsvPlaybackState
    current_rtd_codes: Dict[str, int] = Field(default_factory=dict)
    current_valve_states: Dict[str, Any] = Field(default_factory=dict)
