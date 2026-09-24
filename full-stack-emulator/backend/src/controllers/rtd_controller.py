from typing import Any, Dict, List

from src.services.rtd_service import rtd_service


class RTDController:
    def load_csv(self, header: List[str], rows: List[Dict[str, Any]], filename: str | None = None) -> Dict[str, Any]:
        return rtd_service.load_csv(header, rows, filename)

    def clear_csv(self) -> Dict[str, Any]:
        return rtd_service.clear_csv()

    def set_playback(self, playing: bool) -> Dict[str, Any]:
        return rtd_service.set_playback(playing)

    def set_board_bits(self, board_index: int, bits: List[int]) -> Dict[str, Any]:
        return rtd_service.set_board_bits(board_index, bits)


rtd_controller = RTDController()
