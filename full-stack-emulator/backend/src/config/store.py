import json
from pathlib import Path
from typing import Optional

from src.config.defaults import build_default_config
from src.models.config import EmulatorConfig
from src.utils.logging import get_logger

logger = get_logger(__name__)
LEGACY_STACK3_OUTPUTS_KEY = "stack3_outputs"


class ConfigStore:
    def __init__(self, config_path: Optional[Path] = None):
        backend_root = Path(__file__).resolve().parents[2]
        self.config_path = config_path or backend_root / "emulator_config.json"

    def load(self) -> EmulatorConfig:
        if not self.config_path.exists():
            config = build_default_config()
            self.save(config)
            return config

        with self.config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        config = EmulatorConfig.model_validate(self._migrate_legacy_config(data))
        if config.model_dump(mode="json") != data:
            self.save(config)
        return config

    def _migrate_legacy_config(self, data: dict) -> dict:
        def legacy_manual_analog_outputs(source: dict) -> list:
            # `stack3_outputs` is the old name for the dedicated user-controlled
            # 0-10V analog output board. Keep reading it only for backward compatibility.
            return source.get("manual_analog_outputs", source.get(LEGACY_STACK3_OUTPUTS_KEY, []))

        def legacy_relay_detectors(source: dict) -> list:
            return source.get("relay_detectors", source.get("relay_detector_stacks", []))

        raw_valves = data.get("valves", {})
        detector_configs = legacy_relay_detectors(raw_valves) or legacy_relay_detectors(data)

        def detector_address_from_legacy_ref(ref: dict) -> Optional[int]:
            if "i2c_address" in ref:
                i2c_address = ref.get("i2c_address")
                if i2c_address in (None, ""):
                    return None
                return int(i2c_address)
            legacy_stack = int(ref.get("stack", 0))
            for detector in detector_configs:
                if int(detector.get("stack", -1)) == legacy_stack:
                    return int(detector.get("i2c_address", 0x20 + legacy_stack))
            return 0x20 + legacy_stack

        def migrate_detector_ref(ref: dict) -> dict:
            return {
                "i2c_address": detector_address_from_legacy_ref(ref),
                "channel": int(ref.get("channel", 1)),
            }

        def default_cv_detector(index: int) -> dict:
            return {
                "i2c_address": None,
                "channel": 1,
            }

        def migrate_detector_config(item: dict) -> dict:
            return {
                "i2c_address": int(item.get("i2c_address", 0x20 + int(item.get("stack", 0)))),
                "i2c_bus": int(item.get("i2c_bus", 1)),
                "active_low": bool(item.get("active_low", False)),
                "use_internal_pullups": bool(item.get("use_internal_pullups", False)),
                "enabled": bool(item.get("enabled", True)),
            }

        def migrate_leak_sensor(item: dict, index: int) -> dict:
            stack = item.get("stack", 3)
            channel = item.get("channel", index + 1)
            return {
                "id": item.get("id", f"LS{index + 1}"),
                "name": item.get("name", item.get("label", f"Leak Sensor {index + 1}")),
                "output_channel": {
                    "stack": int(stack if stack not in (None, "") else 3),
                    "channel": int(channel if channel not in (None, "") else index + 1),
                },
                "voltage": float(item.get("voltage", item.get("default_voltage", 0.0))),
            }

        def migrate_rtd_sensor(sensor: dict, index: int) -> dict:
            board_index = int(sensor.get("board_index", index))
            return {
                "sensor_name": sensor.get("sensor_name", f"T{index + 1}"),
                "board_index": board_index,
                "position": int(sensor.get("position", board_index + 1)),
                "bit_width": 8 if int(sensor.get("bit_width", 5)) == 8 else 5,
                "logical_stack": sensor.get("logical_stack", board_index // 8),
                "logical_channel": sensor.get("logical_channel", (board_index % 8) + 1),
                "min_res_ohms": float(sensor.get("min_res_ohms", sensor.get("min_res", 95.0))),
                "max_res_ohms": float(sensor.get("max_res_ohms", sensor.get("max_res", 150.0))),
                "temp_min_c": float(sensor.get("temp_min_c", sensor.get("temp_range_min_c", -10.0))),
                "temp_max_c": float(sensor.get("temp_max_c", sensor.get("temp_range_max_c", 80.0))),
                "res_step_ohms": float(sensor.get("res_step_ohms", sensor.get("step_ohms", 2.0))),
                "use_custom_equation": bool(sensor.get("use_custom_equation", False)),
                "custom_equation_a": sensor.get("custom_equation_a", sensor.get("equation_a")),
                "custom_equation_b": sensor.get("custom_equation_b", sensor.get("equation_b")),
                "output_temp_c": sensor.get("output_temp_c"),
            }

        if "valves" not in data:
            data = {
                **data,
                "valves": {
                    "ball_valves": data.get("ball_valves", []),
                    "relay_detectors": [migrate_detector_config(item) for item in legacy_relay_detectors(data)],
                    "relay_output_i2c_bus": data.get("relay_output_i2c_bus", 1),
                },
            }

        migrated_valves = []
        for index, valve in enumerate(data.get("valves", {}).get("ball_valves", [])):
            profile_type = valve.get("profile_type", "cv")
            if profile_type == "ov" and "open_detector" not in valve:
                input_channel = valve.get("input_channel") or {"stack": 0, "channel": 1}
                output_channel = valve.get("output_channel") or {"stack": 0, "channel": 1}
                behavior = valve.get("behavior") or {}
                migrated_valves.append(
                    {
                        "id": valve.get("id", f"OV{index + 1}"),
                        "name": valve.get("name", valve.get("id", f"OV Valve {index + 1}")),
                        "enabled": valve.get("enabled", True),
                        "profile_type": "ov",
                        "open_detector": {"i2c_address": None, "channel": int(input_channel.get("channel", 1))},
                        "close_detector": {"i2c_address": None, "channel": int(input_channel.get("channel", 1))},
                        "open_feedback": output_channel,
                        "close_feedback": output_channel,
                        "behavior": {
                            "detector_delay_seconds": behavior.get("ramp_seconds", 3.0),
                            "feedback_hold_seconds": 1.0,
                            "default_position": "open",
                        },
                    }
                )
            elif profile_type == "ov":
                migrated_valves.append(
                    {
                        **valve,
                        "id": valve.get("id", f"OV{index + 1}"),
                        "name": valve.get("name", valve.get("id", f"OV Valve {index + 1}")),
                        "open_detector": migrate_detector_ref(valve.get("open_detector")) if valve.get("open_detector") else {"i2c_address": None, "channel": 1},
                        "close_detector": migrate_detector_ref(valve.get("close_detector")) if valve.get("close_detector") else {"i2c_address": None, "channel": 2},
                    }
                )
            else:
                input_channel = valve.get("input_channel") or {"stack": 0, "channel": 1}
                output_channel = valve.get("output_channel") or input_channel
                behavior = dict(valve.get("behavior") or {})
                behavior.pop("idle_threshold", None)
                behavior.pop("open_threshold", None)
                behavior.pop("close_trigger_low", None)
                behavior.pop("close_trigger_high", None)
                migrated_valves.append(
                    {
                        **valve,
                        "id": valve.get("id", f"CV{index + 1}"),
                        "name": valve.get("name", valve.get("id", f"CV Valve {index + 1}")),
                        "input_channel": input_channel,
                        "output_channel": output_channel,
                        "behavior": behavior,
                        "relay_detector": migrate_detector_ref(valve.get("relay_detector") or default_cv_detector(index)),
                    }
                )

        raw_rtd = data.get("rtd", {})
        migrated_rtd_sensors = [migrate_rtd_sensor(sensor, index) for index, sensor in enumerate(raw_rtd.get("sensors", []))]

        return {
            **data,
            "rtd": {
                **raw_rtd,
                "invert_bits": bool(raw_rtd.get("invert_bits", False)),
                "reverse_byte_order": bool(raw_rtd.get("reverse_byte_order", True)),
                "playback": raw_rtd.get("playback", {}),
                "sensors": migrated_rtd_sensors,
            },
            "valves": {
                **data.get("valves", {}),
                "ball_valves": migrated_valves,
                "relay_detectors": [migrate_detector_config(item) for item in (legacy_relay_detectors(data.get("valves", {})) or legacy_relay_detectors(data))],
                "relay_output_i2c_bus": data.get("valves", {}).get("relay_output_i2c_bus", data.get("relay_output_i2c_bus", 1)),
            },
            "leak_sensors": {
                "sensors": [
                    migrate_leak_sensor(item, index)
                    for index, item in enumerate(
                        data.get("leak_sensors", {}).get("sensors")
                        or legacy_manual_analog_outputs(data.get("valves", {}))
                        or legacy_manual_analog_outputs(data)
                    )
                ],
            },
        }

    def save(self, config: EmulatorConfig) -> EmulatorConfig:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            json.dump(config.model_dump(mode="json"), handle, indent=2)
        logger.info("Saved emulator config to %s", self.config_path)
        return config


config_store = ConfigStore()
