from typing import Any, Dict, List, Optional

from src.models.config import RTDConfig
from src.models.state import CsvPlaybackState
from src.sensors.rtd.sensor import RTDEmulatorSensor


class RTDManager:
    def __init__(self, config: RTDConfig):
        self.sensor = RTDEmulatorSensor(config)

    def apply_config(self, config: RTDConfig) -> None:
        self.sensor.apply_config(config)

    def set_board_bits(self, board_index: int, bits: List[int]) -> None:
        self.sensor.set_board_bits(board_index, bits)

    def apply_schedule_row(self, header: List[str], row: Dict[str, object]) -> Dict[int, int]:
        return self.sensor.apply_csv_row(header, row)

    def restore_config_output(self) -> None:
        self.sensor.restore_config_output()

    def snapshot(
        self,
        playback_state: Optional[CsvPlaybackState] = None,
        current_rtd_codes: Optional[Dict[str, int]] = None,
        current_valve_states: Optional[Dict[str, Any]] = None,
    ):
        mode = playback_state.mode if playback_state is not None else "fast"
        return self.sensor.snapshot(
            mode=mode,
            playback_state=playback_state,
            current_rtd_codes=current_rtd_codes,
            current_valve_states=current_valve_states,
        )

    def close(self) -> None:
        self.sensor.close()
