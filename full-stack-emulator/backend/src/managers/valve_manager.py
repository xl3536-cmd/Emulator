import time
from typing import Dict, List, Optional

from src.models.config import CVBallValveConfig, OVBallValveConfig, ValveConfig
from src.models.state import DetectorState, ValveState
from src.sensors.ball_valve.cv.sensor import BallValveHardwareAdapter, update_cv_state
from src.sensors.ball_valve.ov.sensor import update_ov_state
from src.sensors.ball_valve.relay_hardware import BallValveRelayHardwareAdapter


class ValveManager:
    def __init__(self, config: ValveConfig, persisted_state: Optional[Dict] = None):
        self.analog_hardware = BallValveHardwareAdapter()
        self.relay_hardware = BallValveRelayHardwareAdapter(
            relay_detectors=config.relay_detectors,
            relay_output_i2c_bus=config.relay_output_i2c_bus,
        )
        self.input_overrides: Dict[str, float] = {}
        self.persisted_state = persisted_state or {}
        self._persisted_state_dirty = False
        self.apply_config(config)

    def apply_config(self, config: ValveConfig) -> None:
        self.config = config
        self.config_by_id = {valve.id: valve for valve in config.ball_valves}
        self.relay_hardware.apply_config(config.relay_detectors, config.relay_output_i2c_bus)

        existing = getattr(self, "states", {})
        self.states: Dict[str, Dict] = {}
        for valve in config.ball_valves:
            previous = existing.get(valve.id, {})
            if previous.get("_profile_type") != valve.profile_type:
                previous = {}
            if valve.profile_type == "cv":
                self.states[valve.id] = self._build_cv_state(previous, valve)
            else:
                self.states[valve.id] = self._build_ov_state(previous, valve)
            self.states[valve.id]["_profile_type"] = valve.profile_type
        self._persisted_state_dirty = True

    def _build_cv_state(self, previous: Dict, valve: CVBallValveConfig) -> Dict:
        persisted = (self.persisted_state.get("cv_valves", {}) or {}).get(valve.id, {})
        seed = {**persisted, **previous}
        return {
            "input_high": seed.get("input_high", False),
            "mode": seed.get("mode", "DETECTOR_OFF"),
            "current_vout": seed.get("current_vout", 0.0),
            "last_written_vout": seed.get("last_written_vout"),
            "ramp_start_time": seed.get("ramp_start_time", 0.0),
            "ramp_start_v": seed.get("ramp_start_v", valve.behavior.v_min),
            "ramp_target_v": seed.get("ramp_target_v", valve.behavior.v_min),
            "ramp_duration_s": seed.get("ramp_duration_s", 0.0),
            "target_vout": seed.get("target_vout", valve.behavior.v_min),
            "tracked_vout": seed.get("tracked_vout", valve.behavior.v_min),
            "last_vin": seed.get("last_vin", 0.0),
            "detector_active": seed.get("detector_active", False),
            "position": None,
            "pending_action": None,
            "detector_open_active": False,
            "detector_close_active": False,
            "feedback_open_active": False,
            "feedback_close_active": False,
        }

    def _build_ov_state(self, previous: Dict, valve: OVBallValveConfig) -> Dict:
        position = previous.get("position", valve.behavior.default_position)
        return {
            "input_high": previous.get("input_high", False),
            "mode": previous.get("mode", "OPEN" if position == "open" else "CLOSED"),
            "position": position,
            "pending_action": previous.get("pending_action"),
            "action_due_at": previous.get("action_due_at", 0.0),
            "open_feedback_until": previous.get("open_feedback_until", 0.0),
            "close_feedback_until": previous.get("close_feedback_until", 0.0),
            "open_detector_last": previous.get("open_detector_last", False),
            "close_detector_last": previous.get("close_detector_last", False),
            "detector_open_active": previous.get("detector_open_active", False),
            "detector_close_active": previous.get("detector_close_active", False),
            "feedback_open_active": previous.get("feedback_open_active", False),
            "feedback_close_active": previous.get("feedback_close_active", False),
            "last_open_feedback_written": None,
            "last_close_feedback_written": None,
            "open_feedback_output_on": previous.get("open_feedback_output_on", position == "open"),
            "close_feedback_output_on": previous.get("close_feedback_output_on", position == "closed"),
        }

    def set_input_override(self, valve_id: str, voltage: Optional[float]) -> None:
        valve = self.config_by_id.get(valve_id)
        if not isinstance(valve, CVBallValveConfig):
            self.input_overrides.pop(valve_id, None)
            return
        if voltage is None:
            self.input_overrides.pop(valve_id, None)
        else:
            self.input_overrides[valve_id] = max(0.0, min(10.0, float(voltage)))

    def _read_cv_vin(self, valve: CVBallValveConfig) -> float:
        if valve.input_channel.channel < 1:
            return 0.0
        if valve.id in self.input_overrides:
            return self.input_overrides[valve.id]
        value = self.analog_hardware.read_input(valve.input_channel.stack, valve.input_channel.channel)
        if value is None:
            return 0.0
        return max(0.0, min(10.0, float(value)))

    def tick(self) -> None:
        now = time.monotonic()
        for valve in self.config_by_id.values():
            state = self.states[valve.id]
            if valve.profile_type == "cv":
                self._tick_cv_valve(valve, state, now)
            else:
                self._tick_ov_valve(valve, state, now)

    def _tick_cv_valve(self, valve: CVBallValveConfig, state: Dict, now: float) -> None:
        persisted_before = self._build_cv_persisted_state(state)
        last_written_vout = state.get("last_written_vout")
        vin = self._read_cv_vin(valve)
        detector_signal = self.relay_hardware.read_detector_channel(valve.relay_detector.i2c_address, valve.relay_detector.channel)
        detector_on = bool(detector_signal)
        next_state = update_cv_state(state, valve.behavior, vin, detector_on, now)
        self.states[valve.id] = next_state
        target_vout = float(next_state["current_vout"])
        if valve.output_channel.channel > 0 and (last_written_vout is None or abs(target_vout - float(last_written_vout)) > 0.01):
            self.analog_hardware.write_output(
                valve.output_channel.stack,
                valve.output_channel.channel,
                target_vout,
            )
            next_state["last_written_vout"] = target_vout
        if self._build_cv_persisted_state(next_state) != persisted_before:
            self._persisted_state_dirty = True

    def _tick_ov_valve(self, valve: OVBallValveConfig, state: Dict, now: float) -> None:
        open_signal = self.relay_hardware.read_detector_channel(valve.open_detector.i2c_address, valve.open_detector.channel)
        close_signal = self.relay_hardware.read_detector_channel(valve.close_detector.i2c_address, valve.close_detector.channel)
        last_open_written = state.get("last_open_feedback_written")
        last_close_written = state.get("last_close_feedback_written")
        next_state = update_ov_state(state, valve.behavior, bool(open_signal), bool(close_signal), now)
        self.states[valve.id] = next_state

        desired_open = bool(next_state.get("feedback_open_active", False))
        if last_open_written is None or desired_open != bool(last_open_written):
            self.relay_hardware.write_feedback_relay(
                valve.open_feedback.stack,
                valve.open_feedback.channel,
                desired_open,
            )
            next_state["last_open_feedback_written"] = desired_open
        next_state["open_feedback_output_on"] = desired_open

        desired_close = bool(next_state.get("feedback_close_active", False))
        if last_close_written is None or desired_close != bool(last_close_written):
            self.relay_hardware.write_feedback_relay(
                valve.close_feedback.stack,
                valve.close_feedback.channel,
                desired_close,
            )
            next_state["last_close_feedback_written"] = desired_close
        next_state["close_feedback_output_on"] = desired_close

    def is_realtime_mode(self) -> bool:
        active_modes = {
            "RAMP_UP",
            "RAMP_DOWN",
            "WAIT_OPEN",
            "WAIT_CLOSE",
            "OPEN_FEEDBACK",
            "CLOSE_FEEDBACK",
        }
        return any(state.get("mode") in active_modes for state in self.states.values())

    def snapshot(self) -> List[ValveState]:
        results: List[ValveState] = []
        for valve_id, valve in self.config_by_id.items():
            state = self.states[valve_id]
            if valve.profile_type == "cv":
                results.append(self._snapshot_cv_valve(valve, state))
            else:
                results.append(self._snapshot_ov_valve(valve, state))
        return results

    def _snapshot_cv_valve(self, valve: CVBallValveConfig, state: Dict) -> ValveState:
        detector_configured = valve.relay_detector.i2c_address is not None
        detector_ok = self.relay_hardware.has_detector(valve.relay_detector.i2c_address) if detector_configured else False
        input_configured = valve.input_channel.channel > 0
        output_configured = valve.output_channel.channel > 0
        analog_in_ok = self.analog_hardware.has_vin(valve.input_channel.stack) if input_configured else False
        input_ok = analog_in_ok and (detector_ok if detector_configured else False)
        output_ok = self.analog_hardware.has_vout(valve.output_channel.stack) if output_configured else False
        hardware_missing = (input_configured and not analog_in_ok) or (output_configured and not output_ok) or (detector_configured and not detector_ok)
        error = None
        if not input_configured or not output_configured:
            error = "Analog channel not configured"
        elif valve.relay_detector.channel < 1:
            error = "Invalid relay detector channel"
        elif not analog_in_ok and not output_ok:
            error = "Missing analog VIN and VOUT boards"
        elif not analog_in_ok:
            error = "Missing analog VIN board"
        elif not output_ok:
            error = "Missing analog VOUT board"
        elif not detector_configured:
            error = "Relay detector address not configured"
        elif not detector_ok:
            error = self.relay_hardware.get_detector_error(valve.relay_detector.i2c_address) or "Relay detector unavailable"
        return ValveState(
            id=valve.id,
            name=valve.name,
            profile_type=valve.profile_type,
            enabled=valve.enabled,
            mode=state["mode"],
            error=error,
            missing_board=hardware_missing,
            connected_input=input_ok,
            connected_output=output_ok,
            override_active=valve.id in self.input_overrides,
            input_stack=valve.input_channel.stack,
            input_channel=valve.input_channel.channel,
            output_stack=valve.output_channel.stack,
            output_channel=valve.output_channel.channel,
            detector_address=valve.relay_detector.i2c_address,
            detector_channel=valve.relay_detector.channel,
            vin=float(state["last_vin"]),
            vout=float(state["current_vout"]),
            target_vout=float(state["target_vout"]),
            detector_active=bool(state.get("detector_active", False)),
        )

    def _snapshot_ov_valve(self, valve: OVBallValveConfig, state: Dict) -> ValveState:
        open_detector_configured = valve.open_detector.i2c_address is not None
        close_detector_configured = valve.close_detector.i2c_address is not None
        detector_open_ok = self.relay_hardware.has_detector(valve.open_detector.i2c_address) if open_detector_configured else False
        detector_close_ok = self.relay_hardware.has_detector(valve.close_detector.i2c_address) if close_detector_configured else False
        feedback_open_ok = self.relay_hardware.has_feedback_stack(valve.open_feedback.stack)
        feedback_close_ok = self.relay_hardware.has_feedback_stack(valve.close_feedback.stack)
        input_ok = detector_open_ok and detector_close_ok
        output_ok = feedback_open_ok and feedback_close_ok
        hardware_missing = (open_detector_configured and not detector_open_ok) or (close_detector_configured and not detector_close_ok) or not output_ok

        error = None
        if min(
            valve.open_detector.channel,
            valve.close_detector.channel,
            valve.open_feedback.channel,
            valve.close_feedback.channel,
        ) < 1:
            error = "Invalid relay channel assignment"
        elif not open_detector_configured or not close_detector_configured:
            error = "Relay detector address not configured"
        elif not input_ok:
            error = (
                self.relay_hardware.get_detector_error(valve.open_detector.i2c_address)
                or self.relay_hardware.get_detector_error(valve.close_detector.i2c_address)
                or "Relay detector unavailable"
            )
        elif not output_ok:
            error = (
                self.relay_hardware.get_feedback_stack_error(valve.open_feedback.stack)
                or self.relay_hardware.get_feedback_stack_error(valve.close_feedback.stack)
                or "Relay feedback stack unavailable"
            )

        return ValveState(
            id=valve.id,
            name=valve.name,
            profile_type=valve.profile_type,
            enabled=valve.enabled,
            mode=state["mode"],
            error=error,
            missing_board=hardware_missing,
            connected_input=input_ok,
            connected_output=output_ok,
            override_active=False,
            position=state.get("position"),
            pending_action=state.get("pending_action"),
            open_detector_address=valve.open_detector.i2c_address,
            open_detector_channel=valve.open_detector.channel,
            close_detector_address=valve.close_detector.i2c_address,
            close_detector_channel=valve.close_detector.channel,
            open_feedback_stack=valve.open_feedback.stack,
            open_feedback_channel=valve.open_feedback.channel,
            close_feedback_stack=valve.close_feedback.stack,
            close_feedback_channel=valve.close_feedback.channel,
            detector_open_active=bool(state.get("detector_open_active", False)),
            detector_close_active=bool(state.get("detector_close_active", False)),
            feedback_open_active=bool(state.get("feedback_open_active", False)),
            feedback_close_active=bool(state.get("feedback_close_active", False)),
            open_feedback_output_on=bool(state.get("open_feedback_output_on", False)),
            close_feedback_output_on=bool(state.get("close_feedback_output_on", False)),
        )

    def snapshot_detectors(self) -> List[DetectorState]:
        return self.relay_hardware.snapshot_detectors()

    def cleanup(self) -> None:
        for valve in self.config.ball_valves:
            if isinstance(valve, CVBallValveConfig):
                try:
                    if valve.output_channel.channel < 1:
                        continue
                    self.analog_hardware.write_output(
                        valve.output_channel.stack,
                        valve.output_channel.channel,
                        valve.behavior.v_min,
                    )
                except Exception:
                    pass
        self.relay_hardware.cleanup()

    def _build_cv_persisted_state(self, state: Dict) -> Dict:
        return {
            "mode": state.get("mode", "DETECTOR_OFF"),
            "current_vout": float(state.get("current_vout", 0.0)),
            "target_vout": float(state.get("target_vout", 0.0)),
            "tracked_vout": float(state.get("tracked_vout", 0.0)),
            "last_vin": float(state.get("last_vin", 0.0)),
            "detector_active": bool(state.get("detector_active", False)),
            "ramp_start_v": float(state.get("ramp_start_v", 0.0)),
            "ramp_target_v": float(state.get("ramp_target_v", 0.0)),
            "ramp_duration_s": float(state.get("ramp_duration_s", 0.0)),
        }

    def export_persisted_state(self) -> Dict:
        cv_state = {}
        for valve in self.config.ball_valves:
            if isinstance(valve, CVBallValveConfig):
                cv_state[valve.id] = self._build_cv_persisted_state(self.states.get(valve.id, {}))
        return {"cv_valves": cv_state}

    def consume_persisted_state_dirty(self) -> bool:
        dirty = self._persisted_state_dirty
        self._persisted_state_dirty = False
        return dirty

