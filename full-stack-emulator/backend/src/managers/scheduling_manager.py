import time
from typing import Any, Dict, List, Optional

from src.managers.rtd_manager import RTDManager
from src.models.config import ValveConfig
from src.models.state import CsvPlaybackState


def _normalize_header_name(value: object) -> str:
    return str(value or "").strip().lower()


def _parse_csv_flag(value: object) -> bool:
    text = str(value or "").strip().strip("'").replace('"', "").lower()
    return text in {"1", "true", "t", "yes", "y", "on"}


def _parse_csv_float(value: object) -> float:
    text = str(value or "").strip().strip("'").replace('"', "")
    if not text:
        return 0.0
    try:
        return float(text)
    except Exception:
        return 0.0


def _format_marker_value(value: Any, profile_type: str) -> str:
    if profile_type == "cv":
        numeric = _parse_csv_float(value)
        return f"{numeric:.2f}".rstrip("0").rstrip(".") if abs(numeric) >= 1e-9 else "0"
    return "1" if _parse_csv_flag(value) else "0"


class SchedulingManager:
    def __init__(self, rtd_manager: RTDManager, valve_config: ValveConfig):
        self.rtd_manager = rtd_manager
        self.valve_config = valve_config
        self.last_step_monotonic = time.monotonic()
        self.csv_header: List[str] = []
        self.csv_rows: List[Dict[str, Any]] = []
        self.loaded_filename: Optional[str] = None
        self.playing = False
        self.current_row_index = -1
        self.next_row_index = 0
        self.last_timestamp: Optional[str] = None
        self.current_rtd_codes: Dict[str, int] = {}
        self.current_valve_states: Dict[str, Any] = {}
        self.matched_rtd_columns: Dict[str, str] = {}
        self.matched_valve_columns: Dict[str, str] = {}
        self._refresh_column_matches()

    def apply_config(self, valve_config: ValveConfig) -> None:
        self.valve_config = valve_config
        self._refresh_column_matches()
        if self.playing and self.csv_rows and self.current_row_index >= 0:
            self._apply_row(self.current_row_index)
        elif not self.playing:
            self.rtd_manager.restore_config_output()

    def load_csv(self, header: List[str], rows: List[Dict[str, Any]], filename: Optional[str] = None) -> None:
        self.csv_header = header
        self.csv_rows = rows
        self.loaded_filename = filename or None
        self.playing = False
        self.current_row_index = -1
        self.next_row_index = 0
        self.last_timestamp = None
        self.current_rtd_codes = {}
        self.current_valve_states = {}
        self.last_step_monotonic = time.monotonic()
        self._refresh_column_matches()
        self.rtd_manager.restore_config_output()

    def clear_csv(self) -> None:
        self.csv_header = []
        self.csv_rows = []
        self.loaded_filename = None
        self.playing = False
        self.current_row_index = -1
        self.next_row_index = 0
        self.last_timestamp = None
        self.current_rtd_codes = {}
        self.current_valve_states = {}
        self.last_step_monotonic = time.monotonic()
        self._refresh_column_matches()
        self.rtd_manager.restore_config_output()

    def set_playing(self, playing: bool) -> None:
        should_play = playing and bool(self.csv_rows)
        self.playing = should_play
        self.last_step_monotonic = time.monotonic()
        if not should_play:
            self.rtd_manager.restore_config_output()
            return
        if self.current_row_index < 0:
            self._apply_row(0)
            self.next_row_index = self._resolve_next_row_index(0)

    def stop_for_manual_rtd(self) -> None:
        self.playing = False
        self.last_step_monotonic = time.monotonic()

    def tick(self, realtime_mode: bool) -> None:
        if not self.playing:
            self.last_step_monotonic = time.monotonic()
            return

        interval_seconds = (
            self.rtd_manager.sensor.config.playback.slow_interval_seconds
            if (realtime_mode or self._upcoming_row_has_valve_change())
            else self.rtd_manager.sensor.config.playback.fast_interval_seconds
        )
        now = time.monotonic()
        if now - self.last_step_monotonic < interval_seconds:
            return

        next_row_index = self._get_next_row_index()
        if next_row_index is None:
            self.playing = False
            self.last_step_monotonic = now
            return

        self._apply_row(next_row_index)
        self.next_row_index = self._resolve_next_row_index(next_row_index)
        self.last_step_monotonic = now

    def playback_state(self, realtime_mode: bool) -> CsvPlaybackState:
        transition_map = self._upcoming_valve_transition_map() if self.playing else {}
        is_csv_slow = bool(transition_map)
        mode = "slow" if (realtime_mode or is_csv_slow) else "fast"
        return CsvPlaybackState(
            loaded=bool(self.csv_rows),
            loaded_filename=self.loaded_filename,
            playing=self.playing,
            row_index=self.current_row_index,
            row_count=len(self.csv_rows),
            mode=mode,
            last_timestamp=self.last_timestamp,
            header=self.csv_header,
            matched_rtd_columns=self.matched_rtd_columns,
            matched_valve_columns=self.matched_valve_columns,
            slow_reason=("runtime" if realtime_mode else "csv_valve_change" if is_csv_slow else None),
            valve_transitions=transition_map if is_csv_slow else {},
        )

    def _refresh_column_matches(self) -> None:
        header_lookup = {_normalize_header_name(name): name for name in self.csv_header}
        self.matched_rtd_columns = {}
        for sensor in self.rtd_manager.sensor.config.sensors:
            candidates = [
                sensor.sensor_name,
                f"T{sensor.board_index + 1}",
            ]
            for candidate in candidates:
                column_name = header_lookup.get(_normalize_header_name(candidate))
                if column_name is not None:
                    self.matched_rtd_columns[sensor.sensor_name] = column_name
                    break

        self.matched_valve_columns = {}
        for valve in self.valve_config.ball_valves:
            column_name = header_lookup.get(_normalize_header_name(valve.id))
            if column_name is not None:
                self.matched_valve_columns[valve.id] = column_name

    def _apply_row(self, row_index: int) -> None:
        if not (0 <= row_index < len(self.csv_rows)):
            return

        row = self.csv_rows[row_index]
        code_map = self.rtd_manager.apply_schedule_row(self.csv_header, row)
        self.current_row_index = row_index
        self.current_rtd_codes = {
            sensor.sensor_name: int(code_map.get(sensor.board_index, 0))
            for sensor in self.rtd_manager.sensor.config.sensors
        }
        self.current_valve_states = self._parse_valve_states(row)
        self.last_timestamp = row.get("Timestamp")

    def _parse_valve_states(self, row: Dict[str, Any]) -> Dict[str, Any]:
        states: Dict[str, Any] = {}
        for valve in self.valve_config.ball_valves:
            column_name = self.matched_valve_columns.get(valve.id)
            if column_name is None:
                continue
            raw_value = row.get(column_name, 0)
            if valve.profile_type == "cv":
                states[valve.id] = _parse_csv_float(raw_value)
            else:
                states[valve.id] = _parse_csv_flag(raw_value)
        return states

    def _upcoming_row_has_valve_change(self) -> bool:
        return bool(self._upcoming_valve_transition_map())

    def _upcoming_valve_transition_map(self) -> Dict[str, str]:
        next_row_index = self._get_next_row_index()
        if next_row_index is None or self.current_row_index < 0:
            return {}
        next_valve_states = self._parse_valve_states(self.csv_rows[next_row_index])
        transitions: Dict[str, str] = {}
        for valve in self.valve_config.ball_valves:
            if valve.id not in self.matched_valve_columns:
                continue
            previous = self.current_valve_states.get(valve.id, 0.0 if valve.profile_type == "cv" else False)
            current = next_valve_states.get(valve.id, 0.0 if valve.profile_type == "cv" else False)
            if valve.profile_type == "cv":
                if abs(float(current) - float(previous)) >= 0.01:
                    transitions[valve.id] = f"{_format_marker_value(previous, 'cv')} -> {_format_marker_value(current, 'cv')}"
            elif bool(current) != bool(previous):
                transitions[valve.id] = f"{_format_marker_value(previous, 'ov')} -> {_format_marker_value(current, 'ov')}"
        return transitions

    def _get_next_row_index(self) -> Optional[int]:
        if not self.csv_rows:
            return None
        if self.current_row_index < 0:
            return 0
        if self.next_row_index < len(self.csv_rows):
            return self.next_row_index
        if self.rtd_manager.sensor.config.playback.loop:
            return 0
        return None

    def _resolve_next_row_index(self, current_row_index: int) -> int:
        next_row_index = current_row_index + 1
        if next_row_index < len(self.csv_rows):
            return next_row_index
        if self.rtd_manager.sensor.config.playback.loop:
            return 0
        return len(self.csv_rows)
