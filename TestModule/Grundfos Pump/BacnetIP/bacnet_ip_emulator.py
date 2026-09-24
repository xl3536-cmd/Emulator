#!/usr/bin/env python3
"""
Date: 2026-03-13
Author: Xiaxin Liu
Direct BACnet/IP grundfos pump emulator.

This version is intentionally simpler than the routed C attempt:
- one BACnet/IP device
- direct IP addressing
- writable outputs that drive derived input values

Default device:
- BACnet device id: 227015
- UDP port: 47808
"""

import argparse
import asyncio
import socket
from dataclasses import dataclass

import BAC0
from BAC0.core.devices.local.factory import (
    analog_input,
    binary_input,
    binary_output,
    multistate_input,
    multistate_output,
    make_state_text,
)


CONTROL_MODE_STATES = make_state_text(
    [
        "Constant speed",
        "Constant pressure",
        "Proportional pressure",
        "AUTOADAPT",
        "Constant flow",
        "Constant temperature",
        "Constant level",
        "Constant percentage",
        "FLOWADAPT",
        "Closed-loop sensor control",
        "Constant diff. pressure",
        "Constant diff. temperature",
    ]
)

OPERATING_MODE_STATES = make_state_text(
    ["Start (normal)", "Stop (default)", "Minimum", "Maximum"]
)

CIM_STATUS_STATES = make_state_text(["Idle", "Running", "Alarm"])


@dataclass
class PumpState:
    control_mode_actual: int = 1
    operating_mode_actual: int = 2
    pump_ready: bool = True
    run_status: bool = False
    power_limit: bool = False
    fault_codes: float = 0.0
    warning_codes: float = 0.0
    capacity: float = 0.0
    pressure: float = 1.05
    flow: float = 0.0
    rel_performance: float = 68.0
    actual_setpoint: float = 0.0
    motor_current: float = 0.1
    power: float = 0.0
    power_electronics_temp: float = 28.0
    temperature: float = 24.0
    specific_energy: float = 0.3
    total_operating_time: float = 148.0
    total_on_time: float = 92.0
    remote_temperature_2: float = 21.0
    user_setpoint: float = 35.0
    cim_status: int = 1


POINT_NAMES = {
    "bo_bus_control": "BO_BusControl",
    "mso_control_cmd": "MSO_ControlModeCmd",
    "mso_operating_cmd": "MSO_OperatingModeCmd",
    "msi_control_actual": "MSI_ControlModeActual",
    "msi_operating_actual": "MSI_OperatingModeActual",
    "msi_cim_status": "MSI_CIMStatus",
    "bi_pump_ready": "BI_PumpReady",
    "bi_run_status": "BI_RunStatus",
    "bi_power_limit": "BI_PowerLimit",
    "ai_fault_codes": "AI_FaultCodes",
    "ai_warning_codes": "AI_WarningCodes",
    "ai_capacity": "AI_Capacity",
    "ai_pressure": "AI_Pressure",
    "ai_flow": "AI_Flow",
    "ai_rel_performance": "AI_RelPerformance",
    "ai_actual_setpoint": "AI_ActualSetPoint",
    "ai_motor_current": "AI_MotorCurrent",
    "ai_power": "AI_Power",
    "ai_power_elec_temp": "AI_PowerElectronicTemp",
    "ai_temperature": "AI_Temperature",
    "ai_specific_energy": "AI_SpecificEnergy",
    "ai_total_operating_time": "AI_TotalOperatingTime",
    "ai_total_on_time": "AI_TotalOnTime",
    "ai_remote_temp_2": "AI_RemoteTemperature2",
    "ai_user_setpoint": "AI_UserSetPoint",
}


def get_primary_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def control_mode_blocks_manual(value: int) -> bool:
    return value in (4, 9)


def declare_objects() -> None:
    objects = []

    objects.append(binary_output(
        name=POINT_NAMES["bo_bus_control"],
        description="Bus control: False=LOCAL, True=BUS",
        properties={"inactiveText": "LOCAL", "activeText": "BUS"},
    ))

    objects.append(multistate_output(
        name=POINT_NAMES["mso_control_cmd"],
        description="Control mode command",
        presentValue=1,
        properties={"stateText": CONTROL_MODE_STATES},
    ))
    objects.append(multistate_output(
        name=POINT_NAMES["mso_operating_cmd"],
        description="Operating mode command",
        presentValue=2,
        properties={"stateText": OPERATING_MODE_STATES},
    ))

    objects.append(multistate_input(
        name=POINT_NAMES["msi_control_actual"],
        description="Actual control mode",
        presentValue=1,
        properties={"stateText": CONTROL_MODE_STATES},
    ))
    objects.append(multistate_input(
        name=POINT_NAMES["msi_operating_actual"],
        description="Actual operating mode",
        presentValue=2,
        properties={"stateText": OPERATING_MODE_STATES},
    ))
    objects.append(multistate_input(
        name=POINT_NAMES["msi_cim_status"],
        description="CIM status",
        presentValue=1,
        properties={"stateText": CIM_STATUS_STATES},
    ))

    objects.append(binary_input(name=POINT_NAMES["bi_pump_ready"], description="Pump ready"))
    objects.append(binary_input(name=POINT_NAMES["bi_run_status"], description="Run status"))
    objects.append(binary_input(name=POINT_NAMES["bi_power_limit"], description="Power limit"))

    objects.append(analog_input(name=POINT_NAMES["ai_fault_codes"], description="Fault codes", properties={"units": "noUnits"}))
    objects.append(analog_input(name=POINT_NAMES["ai_warning_codes"], description="Warning codes", properties={"units": "noUnits"}))
    objects.append(analog_input(name=POINT_NAMES["ai_capacity"], description="Capacity", properties={"units": "percent"}))
    objects.append(analog_input(name=POINT_NAMES["ai_pressure"], description="Pressure", properties={"units": "bars"}))
    objects.append(analog_input(name=POINT_NAMES["ai_flow"], description="Flow", properties={"units": "litersPerSecond"}))
    objects.append(analog_input(name=POINT_NAMES["ai_rel_performance"], description="Relative performance", properties={"units": "percent"}))
    objects.append(analog_input(name=POINT_NAMES["ai_actual_setpoint"], description="Actual setpoint", properties={"units": "percent"}))
    objects.append(analog_input(name=POINT_NAMES["ai_motor_current"], description="Motor current", properties={"units": "amperes"}))
    objects.append(analog_input(name=POINT_NAMES["ai_power"], description="Power", properties={"units": "watts"}))
    objects.append(analog_input(name=POINT_NAMES["ai_power_elec_temp"], description="Power electronics temp", properties={"units": "degreesCelsius"}))
    objects.append(analog_input(name=POINT_NAMES["ai_temperature"], description="Temperature", properties={"units": "degreesCelsius"}))
    objects.append(analog_input(name=POINT_NAMES["ai_specific_energy"], description="Specific energy", properties={"units": "kilowattHours"}))
    objects.append(analog_input(name=POINT_NAMES["ai_total_operating_time"], description="Total operating time", properties={"units": "hours"}))
    objects.append(analog_input(name=POINT_NAMES["ai_total_on_time"], description="Total on time", properties={"units": "hours"}))
    objects.append(analog_input(name=POINT_NAMES["ai_remote_temp_2"], description="Remote temperature 2", properties={"units": "degreesCelsius"}))
    objects.append(analog_input(name=POINT_NAMES["ai_user_setpoint"], description="User setpoint", properties={"units": "degreesCelsius"}))

    return objects


def update_objects(dev, state: PumpState) -> None:
    dev[POINT_NAMES["msi_control_actual"]].presentValue = state.control_mode_actual
    dev[POINT_NAMES["msi_operating_actual"]].presentValue = state.operating_mode_actual
    dev[POINT_NAMES["msi_cim_status"]].presentValue = state.cim_status

    dev[POINT_NAMES["bi_pump_ready"]].presentValue = state.pump_ready
    dev[POINT_NAMES["bi_run_status"]].presentValue = state.run_status
    dev[POINT_NAMES["bi_power_limit"]].presentValue = state.power_limit

    dev[POINT_NAMES["ai_fault_codes"]].presentValue = state.fault_codes
    dev[POINT_NAMES["ai_warning_codes"]].presentValue = state.warning_codes
    dev[POINT_NAMES["ai_capacity"]].presentValue = state.capacity
    dev[POINT_NAMES["ai_pressure"]].presentValue = state.pressure
    dev[POINT_NAMES["ai_flow"]].presentValue = state.flow
    dev[POINT_NAMES["ai_rel_performance"]].presentValue = state.rel_performance
    dev[POINT_NAMES["ai_actual_setpoint"]].presentValue = state.actual_setpoint
    dev[POINT_NAMES["ai_motor_current"]].presentValue = state.motor_current
    dev[POINT_NAMES["ai_power"]].presentValue = state.power
    dev[POINT_NAMES["ai_power_elec_temp"]].presentValue = state.power_electronics_temp
    dev[POINT_NAMES["ai_temperature"]].presentValue = state.temperature
    dev[POINT_NAMES["ai_specific_energy"]].presentValue = state.specific_energy
    dev[POINT_NAMES["ai_total_operating_time"]].presentValue = state.total_operating_time
    dev[POINT_NAMES["ai_total_on_time"]].presentValue = state.total_on_time
    dev[POINT_NAMES["ai_remote_temp_2"]].presentValue = state.remote_temperature_2
    dev[POINT_NAMES["ai_user_setpoint"]].presentValue = state.user_setpoint


def derive_state(dev, state: PumpState) -> None:
    bus_control = bool(dev[POINT_NAMES["bo_bus_control"]].presentValue)
    control_mode_cmd = int(dev[POINT_NAMES["mso_control_cmd"]].presentValue)
    operating_mode_cmd = int(dev[POINT_NAMES["mso_operating_cmd"]].presentValue)

    state.control_mode_actual = control_mode_cmd
    if bus_control and not control_mode_blocks_manual(control_mode_cmd):
        state.operating_mode_actual = operating_mode_cmd

    if state.operating_mode_actual == 1:
        load = 0.72
    elif state.operating_mode_actual == 3:
        load = 0.42
    elif state.operating_mode_actual == 4:
        load = 1.0
    else:
        load = 0.0

    state.run_status = load > 0.0
    state.capacity = load * 100.0
    state.pressure = 1.15 + (load * 1.75)
    state.flow = load * 3.25
    state.rel_performance = 68.0 + (load * 22.0)
    state.actual_setpoint = 0.0 if load == 0.0 else 38.0 + (load * 6.0)
    state.motor_current = 0.10 + (load * 4.20)
    state.power = load * 720.0
    state.power_electronics_temp = 28.0 + (load * 18.0)
    state.temperature = 24.0 + (load * 6.5)
    state.specific_energy = 0.30 + (load * 0.85)
    state.remote_temperature_2 = 21.0 + (load * 5.0)
    state.user_setpoint = 35.0 if load == 0.0 else 40.0 + (load * 3.0)
    state.warning_codes = 9.0 if control_mode_blocks_manual(control_mode_cmd) else 0.0
    state.cim_status = 2 if load > 0.0 else 1


async def run_emulator(args) -> None:
    local_ip = args.ip or get_primary_ip()

    objects = declare_objects()
    state = PumpState()

    print("=" * 70)
    print("BACnet/IP Python Pump Emulator")
    print("=" * 70)
    print(f"Bind IP:      {local_ip}")
    print(f"Mask bits:    {args.mask}")
    print(f"UDP port:     {args.port}")
    print(f"Device ID:    {args.device_id}")
    print(f"Device name:  {args.name}")
    print("=" * 70)

    async with BAC0.lite(
        ip=local_ip,
        mask=args.mask,
        port=args.port,
        deviceId=args.device_id,
        localObjName=args.name,
    ) as dev:
        if objects:
            objects[0].add_objects_to_application(dev.this_application.app)


        dev[POINT_NAMES["bo_bus_control"]].presentValue = True
        dev[POINT_NAMES["mso_control_cmd"]].presentValue = 1
        dev[POINT_NAMES["mso_operating_cmd"]].presentValue = 2
        update_objects(dev, state)

        while True:
            derive_state(dev, state)
            state.total_operating_time += args.update_seconds / 3600.0
            if state.run_status:
                state.total_on_time += args.update_seconds / 3600.0
            update_objects(dev, state)
            await asyncio.sleep(args.update_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct BACnet/IP pump emulator")
    parser.add_argument("--ip", default=None, help="Local IP to bind. Default: auto-detect")
    parser.add_argument("--mask", type=int, default=24, help="Subnet mask bits, default 24")
    parser.add_argument("--port", type=int, default=47808, help="BACnet UDP port, default 47808")
    parser.add_argument("--device-id", type=int, default=227015, help="BACnet device id")
    parser.add_argument("--name", default="Python Pump Emulator", help="BACnet device name")
    parser.add_argument("--update-seconds", type=float, default=1.0, help="State update interval")
    args = parser.parse_args()

    try:
        asyncio.run(run_emulator(args))
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
