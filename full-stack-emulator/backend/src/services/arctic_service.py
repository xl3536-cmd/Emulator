from typing import Dict

from src.managers.emulator_manager import emulator_manager


class ArcticService:
    def start_server(self) -> Dict[str, object]:
        emulator_manager.arctic_hp_manager.start_server()
        runner = emulator_manager.arctic_hp_manager.server_runner
        return {
            "started": runner.running,
            "transport_available": runner.transport_available,
            "message": runner.last_error or ("Server starting" if runner.transport_available else "pymodbus unavailable"),
        }

    def stop_server(self) -> Dict[str, bool]:
        emulator_manager.arctic_hp_manager.stop_server()
        return {"stopped": True}

    def set_register(self, device_id: int, address: int, value: float) -> Dict[str, object]:
        success = emulator_manager.arctic_hp_manager.set_register(device_id, address, value)
        return {"success": success, "device_id": device_id, "address": address, "value": value}

    def reset_device(self, device_id: int) -> Dict[str, object]:
        success = emulator_manager.arctic_hp_manager.reset_device(device_id)
        return {"success": success, "device_id": device_id}


arctic_service = ArcticService()
