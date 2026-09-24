from typing import List

from src.models.config import ArcticDeviceConfig, ArcticHpConfig, CVBallValveConfig, DetectorChannelConfig, EmulatorConfig, IOChannelConfig, LeakSensorConfig, LeakSensorItemConfig, RTDConfig, RTDSensorConfig, ValveConfig


def build_default_rtd_sensors() -> List[RTDSensorConfig]:
    sensors: List[RTDSensorConfig] = []
    for idx in range(24):
        sensors.append(
            RTDSensorConfig(
                sensor_name=f"T{idx + 1}",
                board_index=idx,
                position=idx + 1,
                bit_width=5,
                logical_stack=idx // 8,
                logical_channel=(idx % 8) + 1,
                min_res_ohms=95.0,
                max_res_ohms=150.0,
                temp_min_c=-10.0,
                temp_max_c=80.0,
                res_step_ohms=2.0,
                use_custom_equation=False,
                custom_equation_a=None,
                custom_equation_b=None,
                output_temp_c=None,
            )
        )
    return sensors


def build_default_ball_valves() -> List[CVBallValveConfig]:
    valves: List[CVBallValveConfig] = []
    valve_num = 1
    for stack, count in ((0, 16), (1, 16), (2, 4)):
        for channel in range(1, count + 1):
            output_stack = 1 if stack == 0 else 0
            valves.append(
                CVBallValveConfig(
                    id=f"CV{valve_num}",
                    name=f"CV Valve {valve_num}",
                    profile_type="cv",
                    relay_detector=DetectorChannelConfig(i2c_address=None, channel=1),
                    input_channel=IOChannelConfig(stack=stack, channel=channel),
                    output_channel=IOChannelConfig(stack=output_stack, channel=channel),
                )
            )
            valve_num += 1
    return valves


def build_default_leak_sensors() -> List[LeakSensorItemConfig]:
    return []


def build_default_config() -> EmulatorConfig:
    return EmulatorConfig(
        rtd=RTDConfig(
            board_count=24,
            invert_bits=False,
            reverse_byte_order=True,
            sensors=build_default_rtd_sensors(),
        ),
        valves=ValveConfig(
            ball_valves=build_default_ball_valves(),
            relay_detectors=[],
            relay_output_i2c_bus=1,
        ),
        leak_sensors=LeakSensorConfig(sensors=build_default_leak_sensors()),
        arctic_hp=ArcticHpConfig(
            devices=[
                ArcticDeviceConfig(
                    device_id=1,
                    unit_id=1,
                    name="Arctic Heat Pump 1",
                    display_side="left",
                    esp32_ip="192.168.68.79",
                ),
                ArcticDeviceConfig(
                    device_id=2,
                    unit_id=4,
                    name="Arctic Heat Pump 2",
                    display_side="right",
                    esp32_ip="192.168.68.67",
                ),
            ]
        ),
        ui={"theme": "light"},
    )
