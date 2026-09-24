from typing import Any, Dict, List, Optional

from src.models.config import RTDConfig
from src.models.state import CsvPlaybackState, RTDState
from src.sensors.rtd.chain_driver import ChainDriver
from src.sensors.rtd.frame_utils import resolve_board_widths, sensor_code_map_from_csv_row, sensor_code_map_from_overrides


class RTDEmulatorSensor:
    def __init__(self, config: RTDConfig):
        self.driver = ChainDriver(
            n_boards=config.board_count,
            invert=config.invert_bits,
            reverse=config.reverse_byte_order,
        )
        self.output_source = "manual"
        self.apply_config(config)

    def apply_config(self, config: RTDConfig) -> None:
        self.config = config
        self.driver.configure(
            n_boards=config.board_count,
            invert=config.invert_bits,
            reverse=config.reverse_byte_order,
            board_widths=resolve_board_widths(config),
        )
        self.restore_config_output()

    def set_board_bits(self, board_index: int, bits: List[int]) -> None:
        self.output_source = "manual"
        self.driver.set_board_bits(board_index, bits)
        self._push_current_frame()

    def apply_csv_row(self, header: List[str], row: Dict[str, object]) -> Dict[int, int]:
        self.driver.clear_board_codes()
        code_map = sensor_code_map_from_csv_row(
            row=row,
            fieldnames=header,
            sensors=self.config.sensors,
        )
        for board_index, code in code_map.items():
            self.driver.set_board_code(board_index, code, apply_inversion=False)
        self.output_source = "csv"
        self._push_current_frame()
        return code_map

    def restore_config_output(self) -> None:
        override_codes = sensor_code_map_from_overrides(self.config)
        if override_codes:
            for board_index, code in override_codes.items():
                self.driver.set_board_code(board_index, code, apply_inversion=False)
            self.output_source = "override"
        else:
            self.output_source = "manual"
        self._push_current_frame()

    def _push_current_frame(self) -> None:
        frame = [0] * self.config.board_count
        for sensor in self.config.sensors:
            position_index = sensor.position - 1
            if not (0 <= sensor.board_index < len(self.driver.board_bits)):
                continue
            if not (0 <= position_index < len(frame)):
                continue
            frame[position_index] = self.driver.encode_board(sensor.board_index)
        self.driver.transmit_frame(frame)

    def snapshot(
        self,
        mode: str,
        playback_state: Optional[CsvPlaybackState] = None,
        current_rtd_codes: Optional[Dict[str, int]] = None,
        current_valve_states: Optional[Dict[str, Any]] = None,
    ) -> RTDState:
        return RTDState(
            board_count=self.config.board_count,
            invert_bits=self.config.invert_bits,
            reverse_byte_order=self.config.reverse_byte_order,
            hardware_available=self.driver.hardware_available,
            hardware_error=self.driver.hardware_error,
            output_source=self.output_source,
            board_bits=self.driver.board_bits,
            frame_bytes=self.driver.get_frame_bytes(),
            playback=(playback_state.model_copy(update={"mode": mode}) if playback_state is not None else CsvPlaybackState(mode=mode)),
            current_rtd_codes=current_rtd_codes or {},
            current_valve_states=current_valve_states or {},
        )

    def close(self) -> None:
        self.driver.close()
