from typing import Dict

from src.models.config import ArcticHpConfig
from src.sensors.arctic_hp.emulator import ArcticServerRunner, DeviceEmulator


class ArcticHPManager:
    def __init__(self, config: ArcticHpConfig):
        self.server_runner = ArcticServerRunner()
        self.devices: Dict[int, DeviceEmulator] = {}
        self.apply_config(config)

    def apply_config(self, config: ArcticHpConfig) -> None:
        was_running = getattr(self.server_runner, "running", False)
        if was_running:
            self.server_runner.stop()
        self.config = config
        existing_devices = self.devices
        next_devices: Dict[int, DeviceEmulator] = {}
        for device in config.devices:
            emulator = existing_devices.get(device.device_id)
            if emulator is None:
                emulator = DeviceEmulator(
                    device_id=device.device_id,
                    unit_id=device.unit_id,
                    name=device.name,
                    display_side=device.display_side,
                    esp32_ip=device.esp32_ip,
                )
            else:
                emulator.apply_metadata(
                    unit_id=device.unit_id,
                    name=device.name,
                    display_side=device.display_side,
                    esp32_ip=device.esp32_ip,
                )
            next_devices[device.device_id] = emulator
        self.devices = next_devices
        if was_running:
            self.server_runner.start(list(self.devices.values()), self.config.port)

    def start_server(self) -> None:
        self.server_runner.start(list(self.devices.values()), self.config.port)

    def stop_server(self) -> None:
        self.server_runner.stop()

    def set_register(self, device_id: int, address: int, value: float) -> bool:
        device = self.devices.get(device_id)
        if not device:
            return False
        return device.set_manual_value(address, value)

    def reset_device(self, device_id: int) -> bool:
        device = self.devices.get(device_id)
        if not device:
            return False
        device.reset_defaults()
        return True

    def snapshot(self) -> Dict[str, object]:
        return {
            "server": self.server_runner.snapshot(self.config.port).model_dump(),
            "devices": [device.snapshot().model_dump() for _, device in sorted(self.devices.items())],
        }
