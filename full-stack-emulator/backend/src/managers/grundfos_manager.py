from contextlib import contextmanager
import threading

from grundfos_engine.group_config import adapter_key, validate_devices
from src.models.grundfos import GrundfosConfig
from src.sensors.grundfos.emulator import AdapterGroup, PumpTransportError
from src.sensors.grundfos.points import POINTS, SIMULATION_FIELDS, validate_edit


class GrundfosConfigConflict(ValueError):
    pass


class GrundfosManager:
    def __init__(self, config: GrundfosConfig):
        self.config = config
        self.groups = {}
        self.lock = threading.RLock()

    def _configs(self, config=None):
        return validate_devices([d.model_dump() for d in (config or self.config).devices])

    @contextmanager
    def configuration_update(self, config):
        with self.lock:
            next_groups = self._configs(config)
            for port, group in self.groups.items():
                if group.alive() and next_groups.get(port) != group.configs:
                    raise GrundfosConfigConflict(f"Stop adapter group {port} before changing its devices or startup settings")
            yield
            self.config = config
            # Discard stale snapshots when stopped devices are edited or removed.
            for port, group in list(self.groups.items()):
                if not group.alive() and next_groups.get(port) != group.configs:
                    group.stop()
                    del self.groups[port]

    def _device(self, pid):
        for device in self.config.devices:
            if device.pump.id == pid:
                return device
        raise KeyError(f"Unknown pump ID {pid}")

    def start_group(self, pid):
        with self.lock:
            port = adapter_key(self._device(pid).model_dump())
            previous = self.groups.get(port)
            if previous and previous.alive():
                if previous.error:
                    raise PumpTransportError(previous.error)
                return {"started": True, "serial_port": port}
            if previous:
                previous.stop()
            group = AdapterGroup(port, self._configs()[port])
            self.groups[port] = group
            group.start()
            return {"started": True, "serial_port": port}

    def stop_group(self, pid):
        with self.lock:
            port = adapter_key(self._device(pid).model_dump())
            if port in self.groups:
                self.groups[port].stop()
            return {"stopped": True, "serial_port": port}

    def set_value(self, pid, field, value):
        field, value = validate_edit(field, value)
        with self.lock:
            port = adapter_key(self._device(pid).model_dump())
            group = self.groups.get(port)
            if not group:
                raise PumpTransportError("Start the adapter group before applying live values")
            return group.edit(pid, field, value)

    def stop_all(self):
        with self.lock:
            for group in self.groups.values():
                group.stop()

    def snapshot(self):
        with self.lock:
            available, message = AdapterGroup.availability()
            groups = {port: group.snapshot() for port, group in self.groups.items()}
            devices = []
            for device in self.config.devices:
                port = adapter_key(device.model_dump())
                group = groups.get(port, {})
                state = group.get("devices", {}).get(device.pump.id, {})
                devices.append(dict(id=device.pump.id, serial_port=port,
                                    active=group.get("active", False), running=group.get("running", False),
                                    live=state.get("live", False), error=group.get("error"),
                                    values=state.get("values", {}), simulation=state.get("simulation", {}),
                                    overrides=state.get("overrides", [])))
            return dict(transport_available=available, message=message, devices=devices,
                        groups=[{k: v for k, v in g.items() if k != "devices"} for g in groups.values()],
                        points=POINTS, simulation_fields=SIMULATION_FIELDS)
