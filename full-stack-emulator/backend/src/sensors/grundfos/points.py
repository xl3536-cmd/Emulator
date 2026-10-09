"""Card metadata. BACnet values use native units, as in pump_objects.c."""
import math

CONTROL_MODES = {1: "Constant Curve", 2: "Constant Pressure", 3: "Proportional Pressure",
                 4: "Auto Adapt", 5: "Constant Flow", 6: "Constant Temperature",
                 9: "Flow Adapt", 12: "Differential Temperature"}
OPERATING_MODES = {1: "Start", 2: "Stop", 3: "Minimum", 4: "Maximum"}


def point(kind, instance, name, unit="", field=None, minimum=0, maximum=1000000, choices=None):
    return dict(object=f"{kind},{instance}", name=name, unit=unit, field=field,
                minimum=minimum, maximum=maximum, choices=choices,
                writable=kind.endswith("Output"))


POINTS = [
    point("analogInput", 0, "FaultCodes", field="fault_code", maximum=65535),
    point("analogInput", 1, "WarningCodes", field="warning_code", maximum=65535),
    point("analogInput", 3, "Capacity", "%", "ai_3", maximum=100),
    point("analogInput", 4, "Pressure", "bar", "ai_4"),
    point("analogInput", 5, "Flow", "m³/h", "ai_5"),
    point("analogInput", 6, "RelPerformance", "%", "ai_6", maximum=100),
    point("analogInput", 9, "ActualSetPoint", "%"),
    point("analogInput", 10, "MotorCurrent", "A", "ai_10"),
    point("analogInput", 13, "Power", "W", "ai_13"),
    point("analogInput", 18, "PowerElectronicTemp", "°C", "electronics_temperature_c", -273.15, 1000),
    point("analogInput", 22, "Temperature", "°C", "temperature_c", -273.15, 1000),
    point("analogInput", 26, "SpecificEnergy", "kWh/m³", "ai_26"),
    point("analogInput", 27, "TotalOperatingTime", "h", "operating_hours", maximum=10000000),
    point("analogInput", 28, "TotalOnTime", "h", "on_hours", maximum=10000000),
    point("analogInput", 57, "RemoteTemperature2", "°C", "remote_temperature_c", -273.15, 1000),
    point("analogInput", 58, "UserSetPoint", "%"),
    point("multiStateInput", 0, "ActualControlMode", choices=CONTROL_MODES),
    point("multiStateInput", 1, "ActualOperatingMode", choices=OPERATING_MODES),
    point("multiStateInput", 3, "CIMStatus", field="cim_status", choices={1: "OK", 2: "EEPROM fault", 3: "Memory fault"}),
    point("binaryInput", 0, "ControlSourceStatus", choices={0: "Local", 1: "Bus"}),
    point("binaryInput", 31, "PowerLimit / src bus feedback", choices={0: "Local", 1: "Bus"}),
    point("binaryOutput", 0, "BusControl", field="command_bus_control", choices={0: "Local", 1: "Bus"}),
    point("multiStateOutput", 0, "ControlMode", field="command_control_mode", choices=CONTROL_MODES),
    point("multiStateOutput", 1, "OperatingMode", field="command_operating_mode", choices=OPERATING_MODES),
    point("analogOutput", 0, "Setpoint", "%", "command_setpoint", maximum=100),
    point("analogOutput", 5, "MaximumFlowLimit / src flow command", "GPM", "command_max_flow"),
]

SIMULATION_FIELDS = [
    dict(field="flow_gpm", name="Nominal flow (GPM)", minimum=0, maximum=1000000),
    dict(field="pressure_psi", name="Nominal pressure (PSI)", minimum=0, maximum=1000000),
    dict(field="power_w", name="Nominal power (W)", minimum=0, maximum=1000000),
    dict(field="current_a", name="Nominal current (A)", minimum=0, maximum=1000000),
    dict(field="local_control_mode", name="Local control mode", choices=CONTROL_MODES),
    dict(field="local_operating_mode", name="Local operating mode", choices=OPERATING_MODES),
    dict(field="local_setpoint", name="Local setpoint (%)", minimum=0, maximum=100),
]


def validate_edit(field, value):
    fields = {p["field"]: p for p in POINTS + SIMULATION_FIELDS if p.get("field")}
    if field not in fields:
        raise ValueError("Unknown pump field")
    item = fields[field]
    if value is None:
        if field.startswith(("command_", "ai_")):
            return ("release_" + field if field.startswith("command_") else "clear_" + field), 0
        raise ValueError("Only output commands and measurement overrides can be released")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Value must be a finite number")
    if item.get("choices"):
        if value not in item["choices"]:
            raise ValueError("Unsupported state")
    elif not item["minimum"] <= value <= item["maximum"]:
        raise ValueError(f"Value must be between {item['minimum']} and {item['maximum']}")
    if field in ("fault_code", "warning_code") and value != int(value):
        raise ValueError("Fault and warning codes must be integers")
    return field, value
