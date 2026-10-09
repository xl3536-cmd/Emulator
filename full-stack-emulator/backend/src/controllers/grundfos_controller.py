from src.services.grundfos_service import grundfos_service


class GrundfosController:
    def start_group(self, device_id):
        return grundfos_service.start_group(device_id)

    def stop_group(self, device_id):
        return grundfos_service.stop_group(device_id)

    def set_value(self, device_id, field, value):
        return grundfos_service.set_value(device_id, field, value)


grundfos_controller = GrundfosController()
