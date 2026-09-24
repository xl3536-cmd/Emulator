from typing import Any, Dict

from src.services.leak_sensor_service import leak_sensor_service


class LeakSensorController:
    def set_voltage(self, sensor_id: str, voltage: float) -> Dict[str, Any]:
        return leak_sensor_service.set_voltage(sensor_id, voltage)


leak_sensor_controller = LeakSensorController()
