from typing import Any, Dict

from src.managers.emulator_manager import emulator_manager


class LeakSensorService:
    def set_voltage(self, sensor_id: str, voltage: float) -> Dict[str, Any]:
        return emulator_manager.leak_sensor_manager.set_voltage(sensor_id, voltage)


leak_sensor_service = LeakSensorService()
