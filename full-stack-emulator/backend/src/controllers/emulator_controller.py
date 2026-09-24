from typing import Any, Dict

from src.services.emulator_service import emulator_service


class EmulatorController:
    def get_snapshot(self) -> Dict[str, Any]:
        return emulator_service.get_snapshot()


emulator_controller = EmulatorController()
