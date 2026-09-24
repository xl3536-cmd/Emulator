from typing import Dict

from src.services.arctic_service import arctic_service


class ArcticController:
    def start_server(self) -> Dict[str, bool]:
        return arctic_service.start_server()

    def stop_server(self) -> Dict[str, bool]:
        return arctic_service.stop_server()

    def set_register(self, device_id: int, address: int, value: float) -> Dict[str, object]:
        return arctic_service.set_register(device_id, address, value)

    def reset_device(self, device_id: int) -> Dict[str, object]:
        return arctic_service.reset_device(device_id)


arctic_controller = ArcticController()
