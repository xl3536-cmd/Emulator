#!/usr/bin/env python3
"""Run one MS/TP pump on one USB-RS485 adapter."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
MODES = {1, 2, 3, 4, 5, 6, 9, 12}


def number(value, label, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if value < low or value > high or (integer and value != int(value)):
        raise ValueError(f"{label} must be {'an integer ' if integer else ''}in {low}..{high}")
    return int(value) if integer else value


def prepare(config, profile=None, serial_port=None):
    pump = dict(profile or config["pump"])
    initial = dict(config["initial"])
    readings = dict(config["readings"])
    device = number(pump["device_id"], "device_id", 0, 4194302, True)
    mac = number(pump["mac"], "mac", 0, 127, True)
    maximum = number(config["max_master"], "max_master", 1, 127, True)
    if maximum < mac:
        raise ValueError("max_master must include the pump MAC and BASrouter MAC")
    frames = number(config["max_info_frames"], "max_info_frames", 1, 255, True)
    baud = number(config["baud"], "baud", 9600, 76800, True)
    if baud not in {9600, 19200, 38400, 76800}:
        raise ValueError("baud must be 9600, 19200, 38400 or 76800")
    name = pump["name"]
    if not isinstance(name, str) or not name or not name.isascii() or len(name) > 32 or any(ord(c) < 32 for c in name):
        raise ValueError("pump name must be 1..32 printable ASCII characters")
    port = serial_port or config["serial_port"]
    if not isinstance(port, str) or not port:
        raise ValueError("serial_port is required")
    values = {
        "BACNET_IFACE": port, "BACNET_MSTP_BAUD": str(baud), "BACNET_MSTP_MAC": str(mac),
        "BACNET_MAX_MASTER": str(maximum), "BACNET_MAX_INFO_FRAMES": str(frames),
        "BACNET_APDU_TIMEOUT": "3000", "BACNET_APDU_RETRIES": "3",
        "PUMP_DEVICE_ID": str(device), "PUMP_NAME": name,
    }
    ranges = {
        "control_mode": (1, 12, True), "operating_mode": (1, 4, True),
        "setpoint": (0, 100, False), "fault_code": (0, 65535, True),
        "warning_code": (0, 65535, True), "operating_hours": (0, 10000000, False),
        "on_hours": (0, 10000000, False),
    }
    if set(initial) != set(ranges) | {"bus_control"}:
        raise ValueError("initial settings do not match config.json fields")
    if type(initial["bus_control"]) is not bool:
        raise ValueError("bus_control must be true or false")
    values["PUMP_BUS_CONTROL"] = str(int(initial["bus_control"]))
    for key, bounds in ranges.items():
        values["PUMP_" + key.upper()] = str(number(initial[key], key, *bounds))
    if initial["control_mode"] not in MODES:
        raise ValueError(f"Supported control modes: {sorted(MODES)}")
    if initial["on_hours"] < initial["operating_hours"]:
        raise ValueError("on_hours must be at least operating_hours")
    expected = {"flow_gpm", "pressure_psi", "power_w", "current_a", "temperature_c",
                "remote_temperature_c", "electronics_temperature_c"}
    if set(readings) != expected:
        raise ValueError("readings do not match config.json fields")
    for key, value in readings.items():
        bounds = (-273.15, 1000) if "temperature" in key else (0, 1000000)
        values["PUMP_" + key.upper()] = str(number(value, key, *bounds))
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--pump", type=int, help="select one of the eight source pump profiles")
    parser.add_argument("--serial-port", help="override serial_port, preferably /dev/serial/by-id/...")
    parser.add_argument("--check", action="store_true", help="validate and display settings without opening hardware")
    parser.add_argument("--interactive", action="store_true", help="enable GUI pipe controls and JSON state output")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    profile = None
    if args.pump is not None:
        profiles = json.loads((ROOT / "pump_profiles.json").read_text(encoding="utf-8"))
        profile = next((p for p in profiles if p["id"] == args.pump), None)
        if profile is None:
            parser.error("--pump must be 1..8")
    values = prepare(config, profile, args.serial_port)
    print(json.dumps(values, indent=2), flush=True)
    if args.check:
        return 0
    if sys.platform != "linux":
        parser.error("Run the MS/TP emulator on Raspberry Pi OS/Linux. --check works on any OS.")
    binary = ROOT / "build" / "pump_emulator"
    if not binary.is_file():
        parser.error("Build first with python3 build.py")
    transport = subprocess.check_output([str(binary), "--transport"], text=True).strip()
    if transport != "mstp":
        parser.error("This executable is not an MS/TP build. Run python3 build.py")
    port = Path(values["BACNET_IFACE"]).resolve(strict=True)
    if not stat.S_ISCHR(port.stat().st_mode) or not os.access(port, os.R_OK | os.W_OK):
        parser.error(f"Cannot access serial device {port}; check the dialout group and serial_port")
    # Keep an advisory lock across exec so two launches cannot share one adapter.
    import fcntl
    key = hashlib.sha256(str(port).encode()).hexdigest()[:16]
    lock = open(Path(tempfile.gettempdir()) / f"grundfos-mstp-{key}.lock", "a")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error(f"Another emulator is using {port}")
    os.set_inheritable(lock.fileno(), True)
    environment = os.environ.copy()
    # Do not inherit transport settings from unrelated BACnet applications.
    for key in list(environment):
        if key.startswith(("BACNET_", "PUMP_")):
            del environment[key]
    environment.update(values)
    if args.interactive:
        environment["PUMP_GUI_CONTROL"] = "1"
    os.execve(str(binary), [str(binary)], environment)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Cannot start emulator: {exc}")
