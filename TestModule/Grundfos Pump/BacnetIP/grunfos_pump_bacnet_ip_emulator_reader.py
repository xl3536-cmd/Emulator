#!/usr/bin/env python3
"""
Date: 2026-03-13
Author: Xiaxin
Compatibility-style reader for the Python BACnet emulator.

This intentionally follows the NYSERDA pumptesting style:
- bacpypes3 DeviceObject + NormalApplication
- explicit local bind address
- read_property(..., "presentValue")
- async timeout wrappers
- operating/control mode labels similar to the pump testing scripts

It does not use BAC0 discovery and it does not target routed addresses.
It is for the direct-IP Python emulator only.
"""

import argparse
import asyncio
import socket

from bacpypes3.local.device import DeviceObject
from bacpypes3.ipv4.app import NormalApplication
from bacpypes3.pdu import Address, IPv4Address


OPERATING_MODE = {
    1: "Start (normal)",
    2: "Stop (default)",
    3: "Minimum",
    4: "Maximum",
}

CONTROL_MODE = {
    1: "Constant speed",
    2: "Constant pressure",
    3: "Proportional pressure",
    4: "AUTOADAPT",
    5: "Constant flow",
    6: "Constant temperature",
    7: "Constant level",
    8: "Constant percentage",
    9: "FLOWADAPT",
    10: "Closed-loop sensor control",
    11: "Constant diff. pressure",
    12: "Constant diff. temperature",
}

READ_POINTS = [
    ("multiStateInput,0", "Actual Control Mode"),
    ("multiStateInput,1", "Actual Operating Mode"),
    ("multiStateInput,2", "CIM Status"),
    ("multiStateOutput,0", "Control Mode Command"),
    ("multiStateOutput,1", "Operating Mode Command"),
    ("binaryOutput,0", "Bus Control"),
    ("binaryInput,0", "Pump Ready"),
    ("binaryInput,1", "Run Status"),
    ("analogInput,0", "Fault Codes"),
    ("analogInput,1", "Warning Codes"),
    ("analogInput,2", "Capacity"),
    ("analogInput,3", "Pressure"),
    ("analogInput,4", "Flow"),
    ("analogInput,7", "Power"),
    ("analogInput,9", "Temperature"),
]


def get_primary_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


async def read_safe(app, target, obj_string: str, timeout: float = 6.0):
    try:
        value = await asyncio.wait_for(
            app.read_property(target, obj_string, "presentValue"),
            timeout=timeout,
        )
        await asyncio.sleep(0.1)
        return value, None
    except asyncio.TimeoutError:
        return None, f"Timeout reading {obj_string}"
    except Exception as exc:
        return None, f"Error reading {obj_string}: {str(exc)[:100]}"


def format_value(obj_string: str, value) -> str:
    if obj_string in ("multiStateInput,0", "multiStateOutput,0"):
        mode = int(value)
        return f"{mode} - {CONTROL_MODE.get(mode, mode)}"
    if obj_string in ("multiStateInput,1", "multiStateOutput,1"):
        mode = int(value)
        label = OPERATING_MODE.get(mode, mode)
        status = "RUNNING" if mode != 2 else "STOPPED"
        return f"{mode} - {label} ({status})"
    if obj_string.startswith("binary"):
        return "active" if bool(value) else "inactive"
    return str(value)


async def run_reader(args) -> bool:
    local_ip = args.local_ip or get_primary_ip()
    target = Address(args.target_ip)

    print(f"\nDiscovering emulator at IP {args.target_ip} via direct BACnet/IP...")

    device = DeviceObject(
        objectName=f"CompatRead-{args.device_id}",
        objectIdentifier=args.local_device_id,
        maxApduLengthAccepted=1024,
        segmentationSupported="segmentedBoth",
        vendorIdentifier=227,
    )
    app = NormalApplication(
        device,
        IPv4Address(f"{local_ip}/{args.mask}:{args.local_port}"),
    )
    await asyncio.sleep(0.5)

    try:
        print(f"\n{'=' * 70}")
        print("Compatibility Reader")
        print(f"{'=' * 70}")
        print(f"Target IP: {args.target_ip}")
        print(f"Target Device ID: {args.device_id}")
        print(f"Local IP: {local_ip}")
        print(f"Local bind: {local_ip}/{args.mask}:{args.local_port}")
        print(f"{'=' * 70}\n")

        total_passed = 0
        total_failed = 0

        for obj_string, label in READ_POINTS:
            value, err = await read_safe(app, target, obj_string)
            if err:
                print(f"FAIL  {label:<24} ({obj_string:<18}): {err}")
                total_failed += 1
            else:
                print(f"OK    {label:<24} ({obj_string:<18}): {format_value(obj_string, value)}")
                total_passed += 1

        print(f"\n{'=' * 70}")
        print("SUMMARY")
        print(f"{'=' * 70}")
        print(f"Total reads: {total_passed + total_failed}")
        print(f"Passed: {total_passed}")
        print(f"Failed: {total_failed}")
        if total_passed + total_failed:
            success_rate = total_passed / (total_passed + total_failed) * 100.0
            print(f"Success rate: {success_rate:.1f}%")
        print(f"{'=' * 70}\n")

        return total_failed == 0
    finally:
        app.close()
        await asyncio.sleep(0.1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compatibility-style reader for the Python BACnet emulator"
    )
    parser.add_argument("--target-ip", required=True, help="Emulator IP")
    parser.add_argument("--device-id", type=int, default=227015, help="Target device id")
    parser.add_argument("--local-ip", default=None, help="Explicit local IP bind address")
    parser.add_argument("--mask", type=int, default=22, help="Local subnet mask bits")
    parser.add_argument("--local-port", type=int, default=47809, help="Local UDP source port")
    parser.add_argument("--local-device-id", type=int, default=999915, help="Local BACnet device id")
    args = parser.parse_args()

    try:
        success = asyncio.run(run_reader(args))
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
