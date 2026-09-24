from typing import Any, Dict, Optional

from src.managers.emulator_manager import emulator_manager


class ValveService:
    def set_input_override(self, valve_id: str, voltage: Optional[float]) -> Dict[str, Any]:
        emulator_manager.valve_manager.set_input_override(valve_id, voltage)
        return {"valve_id": valve_id, "override_voltage": voltage}


valve_service = ValveService()
