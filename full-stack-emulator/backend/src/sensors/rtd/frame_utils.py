from typing import Dict, List, Tuple

from src.models.rtd import RTDConfig, RTDSensorConfig


def normalize_bit_width(value: int) -> int:
    return 8 if int(value) == 8 else 5


def active_mask(bit_width: int) -> int:
    return 0xFF if normalize_bit_width(bit_width) == 8 else 0x1F


def resolve_board_widths(config: RTDConfig) -> List[int]:
    widths = [5] * config.board_count
    for sensor in config.sensors:
        if 0 <= sensor.board_index < len(widths):
            widths[sensor.board_index] = normalize_bit_width(sensor.bit_width)
    return widths


def default_equation(sensor: RTDSensorConfig) -> Tuple[float, float]:
    delta_resistance = float(sensor.max_res_ohms) - float(sensor.min_res_ohms)
    if abs(delta_resistance) < 1e-9:
        return 0.0, float(sensor.temp_min_c)

    a = (float(sensor.temp_max_c) - float(sensor.temp_min_c)) / delta_resistance
    b = float(sensor.temp_min_c) - (a * float(sensor.min_res_ohms))
    return a, b


def active_equation(sensor: RTDSensorConfig) -> Tuple[float, float]:
    if sensor.use_custom_equation and sensor.custom_equation_a is not None and sensor.custom_equation_b is not None:
        return float(sensor.custom_equation_a), float(sensor.custom_equation_b)
    return default_equation(sensor)


def temp_to_resistance(sensor: RTDSensorConfig, temperature_c: float) -> float:
    a, b = active_equation(sensor)
    if abs(a) < 1e-9:
        return float(sensor.max_res_ohms)
    return (float(temperature_c) - b) / a


def clamp_resistance_to_sensor_range(sensor: RTDSensorConfig, resistance_ohms: float) -> float:
    min_res = float(sensor.min_res_ohms)
    max_res = float(sensor.max_res_ohms)
    return max(min_res, min(max_res, float(resistance_ohms)))


def code_to_resistance(sensor: RTDSensorConfig, code: int) -> float:
    max_code = active_mask(sensor.bit_width)
    clamped_code = max(0, min(max_code, int(code)))
    return float(sensor.max_res_ohms) - (clamped_code * float(sensor.res_step_ohms))


def resistance_to_code(sensor: RTDSensorConfig, resistance_ohms: float) -> int:
    max_code = active_mask(sensor.bit_width)
    target_resistance = clamp_resistance_to_sensor_range(sensor, resistance_ohms)
    min_res = float(sensor.min_res_ohms)
    max_res = float(sensor.max_res_ohms)

    best_code = 0
    best_distance = float("inf")
    best_in_range = False

    for code in range(max_code + 1):
        candidate_resistance = code_to_resistance(sensor, code)
        candidate_in_range = min_res <= candidate_resistance <= max_res
        candidate_distance = abs(candidate_resistance - target_resistance)

        if candidate_distance < best_distance:
            best_code = code
            best_distance = candidate_distance
            best_in_range = candidate_in_range
            continue

        if abs(candidate_distance - best_distance) < 1e-9:
            if candidate_in_range and not best_in_range:
                best_code = code
                best_in_range = True
                continue
            if candidate_in_range == best_in_range and code < best_code:
                best_code = code

    return best_code


def temperature_to_code(sensor: RTDSensorConfig, temperature_c: float) -> int:
    return resistance_to_code(sensor, temp_to_resistance(sensor, temperature_c))


def parse_binary_code(raw_value: str, bit_width: int) -> int:
    cleaned = str(raw_value or "").strip().strip("'").replace('"', "")
    if not cleaned:
        return 0
    try:
        return int(cleaned, 2) & active_mask(bit_width)
    except Exception:
        return 0


def sensor_code_map_from_overrides(config: RTDConfig) -> Dict[int, int]:
    code_map: Dict[int, int] = {}
    for sensor in config.sensors:
        if sensor.output_temp_c is None:
            continue
        code_map[sensor.board_index] = temperature_to_code(sensor, sensor.output_temp_c)
    return code_map


def sensor_code_map_from_csv_row(row: dict, fieldnames: List[str], sensors: List[RTDSensorConfig]) -> Dict[int, int]:
    header_lookup = {str(name).strip().lower(): name for name in fieldnames}
    code_map: Dict[int, int] = {}

    for sensor in sensors:
        column_name = None
        candidates = [
            sensor.sensor_name,
            f"T{sensor.board_index + 1}",
        ]

        for candidate in candidates:
            if not candidate:
                continue
            column_name = header_lookup.get(str(candidate).strip().lower())
            if column_name is not None:
                break

        code_map[sensor.board_index] = parse_binary_code(row.get(column_name, ""), sensor.bit_width) if column_name else 0

    return code_map
