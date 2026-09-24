#!/usr/bin/env python3
"""
Read the MS/TP emulator through a real BASrouter.
"""

import argparse
import asyncio
import socket
from typing import List, Tuple

from bacpypes3.local.device import DeviceObject
from bacpypes3.apdu import Error as BACnetError
from bacpypes3.ipv4.app import NormalApplication
from bacpypes3.netservice import RouterEntryStatus
from bacpypes3.pdu import Address, IPv4Address


DEFAULT_ROUTER_IP = "192.168.68.7"
DEFAULT_MSTP_NETWORK = 4004
DEFAULT_PUMP_MAC = 15

READ_ALL_POINTS: List[Tuple[str, str]] = [
    ("multiStateInput,1", "Operating Mode"),
    ("multiStateInput,0", "Control Mode"),
    ("multiStateInput,3", "CIM Status"),
    ("binaryOutput,0", "Bus Control"),
    ("binaryInput,0", "Pump Ready"),
    ("binaryInput,1", "Run Status"),
    ("analogInput,3", "Capacity"),
    ("analogInput,4", "Pressure"),
    ("analogInput,5", "Flow"),
    ("analogInput,7", "Speed"),
    ("analogInput,13", "Power"),
    ("analogInput,27", "Runtime"),
    ("analogInput,30", "Energy"),
    ("analogInput,131", "Min Frequency"),
    ("analogInput,132", "Max Frequency"),
]


def get_primary_ip(target_ip: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((target_ip, 47808))
        return sock.getsockname()[0]


async def read_safe(app, dest, obj_string: str, timeout: float = 6.0):
    attempts = 3
    retry_delay = 0.3
    last_error = None

    for attempt in range(attempts):
        try:
            value = await asyncio.wait_for(
                app.read_property(dest, obj_string, "presentValue"),
                timeout=timeout,
            )
            await asyncio.sleep(0.1)
            return value, None
        except asyncio.TimeoutError:
            last_error = f"Timeout reading {obj_string}"
        except BACnetError as exc:
            last_error = str(exc)
            if "unknown-route" not in last_error.lower():
                return None, last_error
        except BaseException as exc:
            last_error = str(exc)
            return None, last_error

        if attempt < (attempts - 1):
            await asyncio.sleep(retry_delay)

    return None, last_error


async def prime_route(app, router_ip: str, mstp_network: int):
    router_address = Address(router_ip)

    try:
        await app.who_is(address=router_address, timeout=3)
    except Exception:
        pass

    try:
        await asyncio.wait_for(
            app.nse.who_is_router_to_network(
                destination=router_address,
                network=mstp_network,
            ),
            timeout=3.0,
        )
    except Exception:
        pass

    try:
        await app.nsap.update_router_references(
            snet=None,
            address=router_address,
            dnets=[mstp_network],
        )
    except Exception:
        pass

    try:
        await app.nsap.router_info_cache.set_path_info(
            None,
            mstp_network,
            router_address,
            RouterEntryStatus.available,
        )
    except Exception:
        pass

    await asyncio.sleep(0.3)


async def run(args) -> int:
    local_ip = get_primary_ip(args.router_ip)
    local_bind = f"{local_ip}/{args.mask}:{args.local_port}"
    dest = Address(f"{args.mstp_network}:{args.pump_mac}@{args.router_ip}")

    device = DeviceObject(
        objectName="MSTPEmulatorReader",
        objectIdentifier=999915,
        maxApduLengthAccepted=1024,
        segmentationSupported="segmentedBoth",
        vendorIdentifier=227,
    )
    app = NormalApplication(device, IPv4Address(local_bind))
    await asyncio.sleep(0.5)

    try:
        print("=" * 70)
        print("MS/TP Emulator Reader via BASrouter")
        print("=" * 70)
        print(f"Local bind:     {local_bind}")
        print(f"Router IP:      {args.router_ip}")
        print(f"MS/TP network:  {args.mstp_network}")
        print(f"Pump MAC:       {args.pump_mac}")
        print(f"Pump address:   {args.mstp_network}:{args.pump_mac}@{args.router_ip}")
        print("=" * 70)

        await prime_route(app, args.router_ip, args.mstp_network)

        passed = 0
        for obj_string, label in READ_ALL_POINTS:
            value, err = await read_safe(app, dest, obj_string)
            if err:
                print(f"FAIL  {label:<18} {obj_string:<18} {err}")
                continue

            print(f"OK    {label:<18} {obj_string:<18} {value}")
            passed += 1

        print("-" * 70)
        print(f"Summary: {passed}/{len(READ_ALL_POINTS)} reads succeeded")
        return 0 if passed else 1
    finally:
        app.close()
        await asyncio.sleep(0.1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read the BASrouter-exposed MS/TP pump emulator"
    )
    parser.add_argument("--router-ip", default=DEFAULT_ROUTER_IP)
    parser.add_argument("--mstp-network", type=int, default=DEFAULT_MSTP_NETWORK)
    parser.add_argument("--pump-mac", type=int, default=DEFAULT_PUMP_MAC)
    parser.add_argument("--mask", type=int, default=22)
    parser.add_argument("--local-port", type=int, default=47809)
    args = parser.parse_args()

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
