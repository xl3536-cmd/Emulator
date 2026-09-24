from typing import Dict

from src.models.config import CVValveBehaviorConfig
from src.utils.logging import get_logger

logger = get_logger(__name__)

try:
    import lib16univin  # type: ignore
    import SM16uout  # type: ignore
except Exception:  # pragma: no cover
    lib16univin = None
    SM16uout = None


class BallValveHardwareAdapter:
    def __init__(self, i2c_bus: int = 1):
        self.i2c_bus = i2c_bus
        self.vin_boards = {}
        self.vout_boards = {}
        self.available = lib16univin is not None and SM16uout is not None
        if not self.available:
            return
        for stack in (0, 1, 2):
            try:
                self.vin_boards[stack] = lib16univin.SM16univin(stack=stack, i2c=i2c_bus)
            except Exception as exc:
                logger.warning("VIN stack %s unavailable: %s", stack, exc)
            try:
                self.vout_boards[stack] = SM16uout.SM16uout(stack=stack, i2c=i2c_bus)
            except Exception as exc:
                logger.warning("VOUT stack %s unavailable: %s", stack, exc)

    def has_vin(self, stack: int) -> bool:
        return stack in self.vin_boards

    def has_vout(self, stack: int) -> bool:
        return stack in self.vout_boards

    def read_input(self, stack: int, channel: int):
        if stack not in self.vin_boards:
            return None
        try:
            return float(self.vin_boards[stack].get_u_in(channel))
        except Exception as exc:
            logger.warning("Failed to read VIN stack=%s channel=%s: %s", stack, channel, exc)
            return None

    def write_output(self, stack: int, channel: int, voltage: float) -> bool:
        if stack not in self.vout_boards:
            return False
        try:
            self.vout_boards[stack].set_u_out(channel, float(voltage))
            return True
        except Exception as exc:
            logger.warning("Failed to write VOUT stack=%s channel=%s: %s", stack, channel, exc)
            return False


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def update_cv_state(state: Dict, behavior: CVValveBehaviorConfig, vin: float, detector_on: bool, now: float) -> Dict:
    cmd_present = vin >= behavior.cmd_threshold
    state["input_high"] = bool(detector_on and cmd_present)
    state["detector_active"] = bool(detector_on)

    tracked_vout = float(state.get("tracked_vout", behavior.v_min))
    state["last_vin"] = vin

    if not detector_on:
        state["mode"] = "DETECTOR_OFF"
        state["current_vout"] = 0.0
        state["target_vout"] = tracked_vout
        return state

    if cmd_present:
        target_cmd = clamp(vin, behavior.v_min, behavior.v_max)
        if abs(target_cmd - float(state.get("target_vout", behavior.v_min))) > behavior.target_deadband:
            state["target_vout"] = float(target_cmd)
            state["ramp_start_time"] = now
            state["ramp_start_v"] = tracked_vout
            state["ramp_target_v"] = float(target_cmd)
            delta = abs(state["ramp_target_v"] - state["ramp_start_v"])
            full_span = max(0.000001, behavior.v_max - behavior.v_min)
            state["ramp_duration_s"] = behavior.ramp_seconds * (delta / full_span) if delta > 0 else 0.0
            if state["ramp_target_v"] > state["ramp_start_v"] + 0.01:
                state["mode"] = "RAMP_UP"
            elif state["ramp_target_v"] < state["ramp_start_v"] - 0.01:
                state["mode"] = "RAMP_DOWN"
            else:
                state["mode"] = "HOLD"
    if state["mode"] in ("RAMP_UP", "RAMP_DOWN"):
        elapsed = now - state["ramp_start_time"]
        duration = max(0.000001, float(state.get("ramp_duration_s", 0.0)))
        fraction = min(1.0, elapsed / duration)
        target = float(state.get("ramp_target_v", state.get("target_vout", tracked_vout)))
        new_v = state["ramp_start_v"] + (target - state["ramp_start_v"]) * fraction
        if fraction >= 1.0:
            state["mode"] = "HOLD"
            state["target_vout"] = target
    else:
        new_v = tracked_vout

    matched_vout = clamp(new_v, behavior.v_min, behavior.v_max)
    state["tracked_vout"] = matched_vout
    state["current_vout"] = matched_vout
    return state
