from typing import Dict, List, Optional

from src.models.leak_sensor import LeakSensorConfig, LeakSensorState
from src.sensors.leak_sensor.sensor import LeakSensorHardwareAdapter


class LeakSensorManager:
    def __init__(self, config: LeakSensorConfig):
        self.hardware = LeakSensorHardwareAdapter()
        self.voltages: Dict[str, float] = {}
        self.last_errors: Dict[str, Optional[str]] = {}
        self.apply_config(config)

    def apply_config(self, config: LeakSensorConfig) -> None:
        self.config = config
        self.config_by_id = {sensor.id: sensor for sensor in config.sensors}
        self.hardware.apply_config(config.sensors)

        next_voltages: Dict[str, float] = {}
        next_errors: Dict[str, Optional[str]] = {}
        for sensor in config.sensors:
            current_voltage = self.voltages.get(sensor.id, sensor.voltage)
            next_voltages[sensor.id] = max(0.0, min(10.0, float(current_voltage)))
            next_errors[sensor.id] = self.last_errors.get(sensor.id)

        self.voltages = next_voltages
        self.last_errors = next_errors

    def set_voltage(self, sensor_id: str, voltage: float) -> Dict[str, object]:
        sensor = self.config_by_id[sensor_id]
        clamped = max(0.0, min(10.0, float(voltage)))
        self.voltages[sensor_id] = clamped
        hardware_written, error = self.hardware.write_output(sensor.output_channel.stack, sensor.output_channel.channel, clamped)
        self.last_errors[sensor_id] = error
        return {
            "sensor_id": sensor_id,
            "voltage": clamped,
            "hardware_written": hardware_written,
            "error": error,
        }

    def snapshot(self) -> List[LeakSensorState]:
        snapshots: List[LeakSensorState] = []
        for sensor in self.config.sensors:
            stack = sensor.output_channel.stack
            channel = sensor.output_channel.channel
            available = self.hardware.has_output(stack)
            error = self.last_errors.get(sensor.id) or self.hardware.get_output_error(stack)
            snapshots.append(
                LeakSensorState(
                    id=sensor.id,
                    name=sensor.name,
                    stack=stack,
                    channel=channel,
                    voltage=float(self.voltages.get(sensor.id, sensor.voltage)),
                    available=available,
                    error=error,
                )
            )
        return snapshots

    def cleanup(self) -> None:
        for sensor in self.config.sensors:
            self.hardware.write_output(sensor.output_channel.stack, sensor.output_channel.channel, 0.0)
