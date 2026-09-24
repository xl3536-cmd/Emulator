from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class IOChannelConfig(BaseModel):
    stack: int = Field(ge=0)
    channel: int = Field(ge=0)


class DetectorChannelConfig(BaseModel):
    i2c_address: Optional[int] = Field(default=None, ge=0x03, le=0x77)
    channel: int = Field(ge=1, le=16)


class RelayChannelConfig(BaseModel):
    stack: int = Field(ge=0)
    channel: int = Field(ge=1, le=16)


class RelayDetectorConfig(BaseModel):
    i2c_address: int = Field(default=0x20, ge=0x03, le=0x77)
    i2c_bus: int = Field(default=1, ge=0)
    active_low: bool = False
    use_internal_pullups: bool = False
    enabled: bool = True


class CVValveBehaviorConfig(BaseModel):
    ramp_seconds: float = Field(default=90.0, gt=0.0)
    v_min: float = Field(default=2.0, ge=0.0, le=10.0)
    v_max: float = Field(default=10.0, ge=0.0, le=10.0)
    cmd_threshold: float = Field(default=1.9, ge=0.0, le=10.0)
    target_deadband: float = Field(default=0.05, ge=0.0, le=5.0)

    @field_validator("v_max")
    @classmethod
    def validate_vmax(cls, value: float, info):
        v_min = info.data.get("v_min", 0.0)
        if value <= v_min:
            raise ValueError("v_max must be greater than v_min")
        return value


class OVValveBehaviorConfig(BaseModel):
    detector_delay_seconds: float = Field(default=3.0, ge=0.0)
    feedback_hold_seconds: float = Field(default=1.0, gt=0.0)
    default_position: Literal["open", "closed"] = "open"


class BaseBallValveConfig(BaseModel):
    id: str
    name: str
    enabled: bool = True
    profile_type: Literal["cv", "ov"]


class CVBallValveConfig(BaseBallValveConfig):
    profile_type: Literal["cv"] = "cv"
    relay_detector: DetectorChannelConfig = Field(default_factory=DetectorChannelConfig)
    input_channel: IOChannelConfig
    output_channel: IOChannelConfig
    behavior: CVValveBehaviorConfig = Field(default_factory=CVValveBehaviorConfig)


class OVBallValveConfig(BaseBallValveConfig):
    profile_type: Literal["ov"] = "ov"
    open_detector: DetectorChannelConfig
    close_detector: DetectorChannelConfig
    open_feedback: RelayChannelConfig
    close_feedback: RelayChannelConfig
    behavior: OVValveBehaviorConfig = Field(default_factory=OVValveBehaviorConfig)


BallValveConfig = Annotated[Union[CVBallValveConfig, OVBallValveConfig], Field(discriminator="profile_type")]


class ValveConfig(BaseModel):
    ball_valves: List[BallValveConfig]
    relay_detectors: List[RelayDetectorConfig] = Field(default_factory=list)
    relay_output_i2c_bus: int = Field(default=1, ge=0)

    def validate_runtime_constraints(self) -> None:
        detector_usage = {}
        errors = []

        for valve in self.ball_valves:
            detector_refs = []

            if valve.profile_type == "cv":
                detector_refs.append(("relay detector", valve.relay_detector))
            else:
                if (
                    valve.open_feedback.channel > 0
                    and valve.close_feedback.channel > 0
                    and valve.open_feedback.stack == valve.close_feedback.stack
                    and valve.open_feedback.channel == valve.close_feedback.channel
                ):
                    errors.append(
                        f"{valve.id}: open and close feedback relays cannot use the same stack/channel"
                    )
                detector_refs.extend(
                    [
                        ("open detector", valve.open_detector),
                        ("close detector", valve.close_detector),
                    ]
                )

            for label, detector in detector_refs:
                if detector.i2c_address is None:
                    continue
                key = (detector.i2c_address, detector.channel)
                previous = detector_usage.get(key)
                if previous is not None:
                    errors.append(
                        f"{valve.id}: {label} duplicates {previous} on detector addr 0x{detector.i2c_address:X} channel {detector.channel}"
                    )
                else:
                    detector_usage[key] = f"{valve.id} {label}"

        if errors:
            raise ValueError("; ".join(errors))


class ValveState(BaseModel):
    id: str
    name: str
    profile_type: Literal["cv", "ov"]
    enabled: bool
    mode: str
    error: Optional[str] = None
    missing_board: bool = False
    connected_input: bool = False
    connected_output: bool = False
    override_active: bool = False
    position: Optional[Literal["open", "closed"]] = None
    pending_action: Optional[Literal["open", "close"]] = None
    input_stack: Optional[int] = None
    input_channel: Optional[int] = None
    output_stack: Optional[int] = None
    output_channel: Optional[int] = None
    open_detector_address: Optional[int] = None
    open_detector_channel: Optional[int] = None
    close_detector_address: Optional[int] = None
    close_detector_channel: Optional[int] = None
    detector_address: Optional[int] = None
    detector_channel: Optional[int] = None
    open_feedback_stack: Optional[int] = None
    open_feedback_channel: Optional[int] = None
    close_feedback_stack: Optional[int] = None
    close_feedback_channel: Optional[int] = None
    vin: Optional[float] = None
    vout: Optional[float] = None
    target_vout: Optional[float] = None
    detector_active: bool = False
    detector_open_active: bool = False
    detector_close_active: bool = False
    feedback_open_active: bool = False
    feedback_close_active: bool = False
    open_feedback_output_on: bool = False
    close_feedback_output_on: bool = False


class DetectorState(BaseModel):
    i2c_address: int
    i2c_bus: int
    active_low: bool
    use_internal_pullups: bool
    enabled: bool
    available: bool
    last_word: Optional[int] = None
    error: Optional[str] = None


class ValveRuntimeState(BaseModel):
    ball_valves: List[ValveState]
    relay_detectors: List[DetectorState] = Field(default_factory=list)


RelayDetectorStackConfig = RelayDetectorConfig
DetectorStackState = DetectorState
