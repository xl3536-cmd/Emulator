from typing import Any, Dict

from src.managers.emulator_manager import emulator_manager


class EmulatorService:
    def get_snapshot(self) -> Dict[str, Any]:
        return emulator_manager.get_snapshot()


emulator_service = EmulatorService()
