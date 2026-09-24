from typing import Any, Dict, List

from src.managers.emulator_manager import emulator_manager


class RTDService:
    def load_csv(self, header: List[str], rows: List[Dict[str, Any]], filename: str | None = None) -> Dict[str, Any]:
        emulator_manager.scheduling_manager.load_csv(header, rows, filename)
        return {"loaded": True, "row_count": len(rows), "header": header, "loaded_filename": filename}

    def clear_csv(self) -> Dict[str, Any]:
        emulator_manager.scheduling_manager.clear_csv()
        return {"cleared": True}

    def set_playback(self, playing: bool) -> Dict[str, Any]:
        emulator_manager.scheduling_manager.set_playing(playing)
        return {"playing": playing}

    def set_board_bits(self, board_index: int, bits: List[int]) -> Dict[str, Any]:
        emulator_manager.scheduling_manager.stop_for_manual_rtd()
        emulator_manager.rtd_manager.set_board_bits(board_index, bits)
        snapshot = emulator_manager.rtd_manager.snapshot(
            playback_state=emulator_manager.scheduling_manager.playback_state(realtime_mode=False),
            current_rtd_codes=emulator_manager.scheduling_manager.current_rtd_codes,
            current_valve_states=emulator_manager.scheduling_manager.current_valve_states,
        )
        return {
            "board_index": board_index,
            "bits": bits,
            "hardware_available": snapshot.hardware_available,
            "hardware_error": snapshot.hardware_error,
            "output_source": snapshot.output_source,
            "frame_bytes": snapshot.frame_bytes,
        }


rtd_service = RTDService()
