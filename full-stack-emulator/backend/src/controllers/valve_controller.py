from typing import Any, Dict, Optional

from src.services.valve_service import valve_service


class ValveController:
    def set_input_override(self, valve_id: str, voltage: Optional[float]) -> Dict[str, Any]:
        return valve_service.set_input_override(valve_id, voltage)


valve_controller = ValveController()
