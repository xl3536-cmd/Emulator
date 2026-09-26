"""Configuration checks without hardware."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from group_config import validate_devices


class GroupConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.first = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())
        self.first["router_mac"] = 40
        self.first["pump"].update(id=1, mac=11, device_id=227011)
        self.first["max_master"] = 127
        self.first["baud"] = 9600
        self.first["serial_port"] = "/dev/ttyUSB0"
        self.second = copy.deepcopy(self.first)
        self.second["pump"].update(id=2, mac=12, device_id=227012)

    def test_shared_adapter(self):
        groups = validate_devices([self.first, self.second])
        self.assertEqual(len(groups), 1)
        self.assertEqual([c["pump"]["mac"] for c in next(iter(groups.values()))], [11, 12])

    def test_integral_json_numbers_normalized(self):
        self.first["baud"] = 9600.0
        self.first["pump"]["id"] = 1.0
        self.first["pump"]["mac"] = 11.0
        group = next(iter(validate_devices([self.first]).values()))
        self.assertIs(type(group[0]["baud"]), int)
        self.assertIs(type(group[0]["pump"]["id"]), int)
        self.assertIs(type(group[0]["pump"]["mac"]), int)

    def test_separate_adapters(self):
        self.second["serial_port"] = "/dev/ttyUSB1"
        self.second["pump"]["mac"] = 11
        self.assertEqual(len(validate_devices([self.first, self.second])), 2)

    def test_duplicate_mac(self):
        self.second["pump"]["mac"] = 11
        with self.assertRaisesRegex(ValueError, "Duplicate pump MAC"):
            validate_devices([self.first, self.second])

    def test_router_collision(self):
        self.second["pump"]["mac"] = 40
        with self.assertRaisesRegex(ValueError, "BASrouter MAC"):
            validate_devices([self.first, self.second])

    def test_baud_conflict(self):
        self.second["baud"] = 38400
        with self.assertRaisesRegex(ValueError, "same baud"):
            validate_devices([self.first, self.second])

    def test_device_ids_unique_across_adapters(self):
        self.second["serial_port"] = "/dev/ttyUSB1"
        self.second["pump"]["device_id"] = self.first["pump"]["device_id"]
        with self.assertRaisesRegex(ValueError, "unique across all adapters"):
            validate_devices([self.first, self.second])

    def test_max_master_includes_router(self):
        self.first["max_master"] = 12
        with self.assertRaisesRegex(ValueError, "include the BASrouter"):
            validate_devices([self.first])


if __name__ == "__main__":
    unittest.main()
