"""Hardware-free checks for the user to run; does not import the app singleton."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError
from src.managers.grundfos_manager import GrundfosConfigConflict, GrundfosManager
from src.models.grundfos import GrundfosConfig, GrundfosDeviceConfig
from src.sensors.grundfos.emulator import AdapterGroup, OBJECT_KEYS, SIMULATION_KEYS
from src.sensors.grundfos.points import validate_edit


class GrundfosConfigTests(unittest.TestCase):
    def setUp(self):
        self.first = GrundfosDeviceConfig().model_dump()
        self.second = copy.deepcopy(self.first)
        self.second["pump"].update(id=2, mac=12, device_id=227012)

    def test_shared_adapter_and_roundtrip(self):
        config = GrundfosConfig(devices=[self.first, self.second])
        self.assertEqual(GrundfosConfig.model_validate_json(config.model_dump_json()), config)
        self.assertEqual(config.devices[0].router_mac, 10)

    def test_conflicting_mac_and_baud(self):
        for field, value in (("mac", 11), ("mac", 10), ("baud", 38400)):
            with self.subTest(field=field, value=value):
                second = copy.deepcopy(self.second)
                (second["pump"] if field == "mac" else second)[field] = value
                with self.assertRaises(ValidationError):
                    GrundfosConfig(devices=[self.first, second])

    def test_invalid_modes_hours_and_nonfinite_values(self):
        for field, value in (("control_mode", 7), ("operating_hours", 1), ("setpoint", float("nan"))):
            with self.subTest(field=field):
                device = copy.deepcopy(self.first)
                device["initial"][field] = value
                with self.assertRaises(ValidationError):
                    GrundfosConfig(devices=[device])

    def test_live_group_config_cannot_change(self):
        config = GrundfosConfig(devices=[self.first])
        manager = GrundfosManager(config)
        port, configs = next(iter(manager._configs().items()))
        group = Mock(configs=configs)
        group.alive.return_value = True
        manager.groups[port] = group
        with manager.configuration_update(config.model_copy(deep=True)):
            pass  # Saving another module does not restart or stop the pump.
        group.stop.assert_not_called()
        changed = config.model_copy(deep=True)
        changed.devices[0].pump.mac = 12
        with self.assertRaises(GrundfosConfigConflict):
            with manager.configuration_update(changed):
                self.fail("Config persistence must not be reached")
        self.assertEqual(manager.config.devices[0].pump.mac, 11)

    def test_stopped_reconfiguration_discards_old_group(self):
        manager = GrundfosManager(GrundfosConfig(devices=[self.first]))
        port, configs = next(iter(manager._configs().items()))
        group = Mock(configs=configs)
        group.alive.return_value = False
        manager.groups[port] = group
        with manager.configuration_update(GrundfosConfig(devices=[])):
            pass
        group.stop.assert_called_once()
        self.assertEqual(manager.groups, {})


class LiveValueTests(unittest.TestCase):
    def test_ranges_and_releases(self):
        self.assertEqual(validate_edit("command_setpoint", 52.5), ("command_setpoint", 52.5))
        self.assertEqual(validate_edit("command_setpoint", None), ("release_command_setpoint", 0))
        self.assertEqual(validate_edit("ai_5", None), ("clear_ai_5", 0))
        for field, value in (("ai_9", 1), ("command_control_mode", 7), ("command_bus_control", 0.5),
                             ("command_setpoint", 101), ("temperature_c", float("inf")),
                             ("fault_code", 1.5), ("temperature_c", None), ("ai_5", True)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_edit(field, value)

    def test_engine_snapshot_and_acknowledgement(self):
        group = AdapterGroup("/dev/ttyUSB0", [GrundfosDeviceConfig().model_dump()])
        group.process = Mock()
        group.process.poll.return_value = None
        group._handle_line("BUS BUS_READY /dev/ttyUSB0")
        group.pending = {"pid": 1, "field": "command_setpoint"}
        group._handle_line("DEVICE 1 APPLIED command_setpoint 60")
        self.assertFalse(group.pending.get("done", False))
        objects = dict.fromkeys(OBJECT_KEYS, 0)
        objects["analogOutput,0"] = 60
        group._handle_line("DEVICE 1 OBJECTS " + json.dumps(objects))
        group._handle_line("DEVICE 1 SIMULATION " + json.dumps(dict.fromkeys(SIMULATION_KEYS, 0)))
        group._handle_line('DEVICE 1 OVERRIDES ["ai_5"]')
        self.assertTrue(group.pending["done"])
        state = group.snapshot()["devices"][1]
        self.assertTrue(state["live"])
        self.assertEqual(state["values"]["analogOutput,0"], 60)
        self.assertEqual(state["overrides"], ["ai_5"])
        group.updated[1] -= 6
        self.assertFalse(group.snapshot()["devices"][1]["live"])

    def test_partial_snapshot_is_rejected(self):
        group = AdapterGroup("/dev/ttyUSB0", [GrundfosDeviceConfig().model_dump()])
        group._handle_line('DEVICE 1 OBJECTS {"analogInput,5": 4}')
        self.assertIsNotNone(group.error)
        self.assertFalse(group.objects)


if __name__ == "__main__":
    unittest.main()
