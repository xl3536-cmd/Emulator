from src.managers.emulator_manager import emulator_manager


class GrundfosService:
    def start_group(self, device_id):
        return emulator_manager.grundfos_manager.start_group(device_id)

    def stop_group(self, device_id):
        return emulator_manager.grundfos_manager.stop_group(device_id)

    def set_value(self, device_id, field, value):
        return emulator_manager.grundfos_manager.set_value(device_id, field, value)


grundfos_service = GrundfosService()
