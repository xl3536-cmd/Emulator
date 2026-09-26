#!/usr/bin/env python3
"""Small BACnet/IP -> MS/TP controller for Grundfos MAGNA3 emulators/pumps."""

import argparse
import asyncio
import json
import math
from pathlib import Path

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.apdu import ErrorRejectAbortNack
from bacpypes3.primitivedata import Null

ROOT = Path(__file__).resolve().parent

CONTROL_MODES = {
    1: "constant-curve",
    2: "constant-pressure",
    3: "proportional-pressure",
    4: "auto-adapt",
    5: "constant-flow",
    6: "constant-temperature",
    9: "flow-adapt",
    12: "differential-temperature",
}
CONTROL_MODE_NAMES = {v: k for k, v in CONTROL_MODES.items()}
OPERATING = {1: "start", 2: "stop", 3: "minimum", 4: "maximum"}
OUTPUTS = {
    "binary-output,0": ("Bus control (0 local / 1 bus)", "binary-input,0"),
    "multi-state-output,0": ("Control mode", "multi-state-input,0"),
    "multi-state-output,1": ("Operating mode (1 start / 2 stop / 3 min / 4 max)", "multi-state-input,1"),
    "analog-output,0": ("Setpoint (%)", "analog-input,9"),
    "analog-output,5": ("Maximum flow (m3/h)", "analog-input,5"),
}


def output_value(obj, text):
    if obj not in OUTPUTS:
        raise ValueError("Only the five supported pump outputs can be written")
    if str(text).strip().lower() == "null":
        return Null(())
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("Value must be finite")
    if obj.startswith("analog"):
        upper = 100 if obj == "analog-output,0" else 1000000
        if not 0 <= value <= upper:
            raise ValueError(f"Value must be 0..{upper}")
        return value
    allowed = ({0, 1} if obj.startswith("binary") else
               set(CONTROL_MODES) if obj.endswith(",0") else set(OPERATING))
    if value not in allowed:
        raise ValueError(f"Value must be one of {sorted(allowed)}")
    return int(value)


async def write_point(app, dst, obj, text, priority):
    """Keep ACK, effective output, and actual pump state distinct."""
    value = output_value(obj, text)
    await write(app, dst, obj, value, priority)
    result = {"acknowledged": True, "object": obj, "priority": priority,
              "requested": str(text)}
    try:
        result["effective_output"] = num(await read(app, dst, obj))
        result["actual_object"] = OUTPUTS[obj][1]
        result["actual_value"] = num(await read(app, dst, OUTPUTS[obj][1]))
        result["bus_control"] = integer(await read(app, dst, "binary-input,0"))
        result["note"] = ("AI5 is measured flow, not the AO5 flow-limit command."
                          if obj == "analog-output,5" else
                          "Actual state may differ under local control or a higher-priority command.")
    except Exception as exc:
        result["readback_error"] = str(exc) or type(exc).__name__
    return result


def load_config(path: Path, pump_id=None):
    cfg = json.loads(path.read_text(encoding="utf-8"))
    pumps = [p for p in cfg.get("pumps", []) if p.get("enabled", True)]
    if pump_id is not None:
        pumps = [p for p in pumps if int(p["id"]) == pump_id]
    if len(pumps) != 1:
        raise ValueError("Select one enabled pump with --pump ID (required when several are configured)")
    return cfg, pumps[0]


def local_address(cfg):
    address = str(cfg["local_ip"])
    port = int(cfg.get("local_port", 47808))
    if port != 47808:
        address = f"{address}:{port}"
    return address


def destination(cfg, pump):
    network = int(pump.get("mstp_network", cfg["mstp_network"]))
    mac = int(pump["mac"])
    router_ip = str(pump.get("router_ip", cfg["router_ip"]))
    router_port = int(pump.get("router_port", cfg.get("router_port", 47808)))
    router = router_ip if router_port == 47808 else f"{router_ip}:{router_port}"
    return f"{network}:{mac}@{router}"


def make_app(cfg):
    # Let BACpypes3 build the local BACnet/IP stack. Route-aware addressing lets
    # us send directly through the configured BASrouter to the remote MS/TP MAC.
    argv = [
        "--name", "Simple-Pump-Controller",
        "--instance", str(int(cfg.get("device_id", 999990))),
        "--address", local_address(cfg),
        "--route-aware",
    ]
    args = SimpleArgumentParser().parse_args(argv)
    return Application.from_args(args)


async def read(app, dst, obj, prop="present-value", array_index=None):
    try:
        value = await app.read_property(dst, obj, prop, array_index=array_index)
    except ErrorRejectAbortNack as exc:
        raise RuntimeError(f"Read {obj} {prop} failed: {exc}") from exc
    if (isinstance(value, ErrorRejectAbortNack) or value is None or
            (isinstance(value, str) and value in ("-no object class-", "-no property type-"))):
        raise RuntimeError(f"Read {obj} {prop} failed: {value}")
    return value


async def write(app, dst, obj, value, priority):
    if priority not in range(1, 17) or priority == 6:
        raise ValueError("Write priority must be 1..16, except reserved priority 6")
    try:
        result = await app.write_property(dst, obj, "present-value", value, priority=priority)
    except ErrorRejectAbortNack as exc:
        raise RuntimeError(f"Write {obj} failed: {exc}") from exc
    if result is not None:
        raise RuntimeError(f"Write {obj} failed: {result}")


def num(value):
    try:
        return float(value)
    except Exception:
        return value


def integer(value):
    try:
        return int(value)
    except Exception:
        return value


async def status(app, dst):
    points = [
        ("bus_control", "binary-input,0", integer),
        ("control_mode", "multi-state-input,0", integer),
        ("operating_mode", "multi-state-input,1", integer),
        ("fault_code", "analog-input,0", integer),
        ("warning_code", "analog-input,1", integer),
        ("capacity_pct", "analog-input,3", num),
        ("pressure_bar", "analog-input,4", num),
        ("flow_m3h", "analog-input,5", num),
        ("setpoint_pct", "analog-input,9", num),
        ("motor_current_a", "analog-input,10", num),
        ("power_w", "analog-input,13", num),
        ("temperature_c", "analog-input,22", num),
    ]
    result = {}
    for label, obj, converter in points:
        result[label] = converter(await read(app, dst, obj))
    cm = result.get("control_mode")
    om = result.get("operating_mode")
    result["control_mode_name"] = CONTROL_MODES.get(cm, "unknown")
    result["operating_mode_name"] = OPERATING.get(om, "unknown")
    result["bus_control_name"] = "bus" if result.get("bus_control") == 1 else "local"
    return result


async def command(app, dst, args):
    p = args.priority
    cmd = args.command

    if cmd == "status":
        print(json.dumps(await status(app, dst), indent=2))
        return

    if cmd == "read":
        value = await read(app, dst, args.object, args.property, args.index)
        print(f"{args.object} {args.property}: {value}")
        return

    if cmd == "write":
        print(json.dumps(await write_point(app, dst, args.object, args.value, p), indent=2))
        return

    if cmd == "bus":
        expected = 1 if args.state == "on" else 0
        await write(app, dst, "binary-output,0", expected, p)
        actual = integer(await read(app, dst, "binary-input,0"))
        if actual != expected:
            raise RuntimeError(f"bus-control confirmation failed: expected BI0={expected}, got {actual}")
        print(f"bus control: {'ON' if actual else 'OFF'}")
        return

    if cmd in ("start", "stop"):
        expected = 1 if cmd == "start" else 2
        await write(app, dst, "multi-state-output,1", expected, p)
        actual = integer(await read(app, dst, "multi-state-input,1"))
        if actual != expected:
            raise RuntimeError(f"operating-mode confirmation failed: expected {expected}, got {actual}")
        print(f"operating mode: {OPERATING.get(actual, actual)}")
        return

    if cmd == "mode":
        expected = CONTROL_MODE_NAMES.get(args.mode, None)
        if expected is None:
            try:
                expected = int(args.mode)
            except ValueError as exc:
                raise ValueError(f"unknown mode {args.mode!r}") from exc
        if expected not in CONTROL_MODES:
            raise ValueError(f"mode must be one of {sorted(CONTROL_MODES)} or {sorted(CONTROL_MODE_NAMES)}")
        await write(app, dst, "multi-state-output,0", expected, p)
        actual = integer(await read(app, dst, "multi-state-input,0"))
        if actual != expected:
            raise RuntimeError(f"control-mode confirmation failed: expected {expected}, got {actual}")
        print(f"control mode: {CONTROL_MODES[actual]} ({actual})")
        return

    if cmd == "setpoint":
        value = float(args.value)
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("setpoint must be 0..100 percent")
        await write(app, dst, "analog-output,0", value, p)
        actual = num(await read(app, dst, "analog-input,9"))
        if isinstance(actual, float) and abs(actual - value) > args.tolerance:
            raise RuntimeError(f"setpoint confirmation failed: commanded {value}, read {actual}")
        print(f"setpoint: {actual:.2f}%")
        return

    if cmd == "max-flow":
        value = float(args.value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("maximum flow must be a non-negative m^3/h value")
        await write(app, dst, "analog-output,5", value, p)
        # AO5 is a limit command. Do NOT require AI5 measured flow to equal it.
        readback = num(await read(app, dst, "analog-output,5"))
        measured = num(await read(app, dst, "analog-input,5"))
        print(f"maximum flow limit command: {readback:.3f} m^3/h")
        print(f"current measured flow:       {measured:.3f} m^3/h")
        return

    raise ValueError(f"unsupported command: {cmd}")


async def async_main(args):
    cfg, pump = load_config(args.config, args.pump)
    dst = destination(cfg, pump)
    print(f"pump: {pump['name']} device={pump['device_id']} destination={dst}")
    app = make_app(cfg)
    try:
        await asyncio.wait_for(command(app, dst, args), timeout=float(cfg.get("timeout", 5.0)))
    finally:
        app.close()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=ROOT / "config.json")
    p.add_argument("--pump", type=int, help="configured pump ID")
    p.add_argument("--priority", type=int, default=8, choices=range(1, 17))
    p.add_argument("--tolerance", type=float, default=0.25, help="setpoint confirmation tolerance")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="read the main pump measurements and state")
    b = sub.add_parser("bus", help="enable/disable BACnet bus control")
    b.add_argument("state", choices=("on", "off"))
    sub.add_parser("start", help="command normal/start operating mode")
    sub.add_parser("stop", help="command stop operating mode")
    m = sub.add_parser("mode", help="set control mode")
    m.add_argument("mode", help="number or name, e.g. constant-pressure")
    s = sub.add_parser("setpoint", help="set 0..100 percent setpoint")
    s.add_argument("value", type=float)
    f = sub.add_parser("max-flow", help="set maximum-flow limit in m^3/h")
    f.add_argument("value", type=float)
    r = sub.add_parser("read", help="read an object property, optionally one array element")
    r.add_argument("object", help="e.g. analog-input,5 or device,227011")
    r.add_argument("property", nargs="?", default="present-value")
    r.add_argument("--index", type=int)
    w = sub.add_parser("write", help="write an output present-value, or null to release this priority")
    w.add_argument("object", choices=tuple(OUTPUTS))
    w.add_argument("value")
    return p


def main():
    args = parser().parse_args()
    if args.priority == 6:
        raise SystemExit("BACnet priority 6 is reserved; choose another priority")
    try:
        asyncio.run(async_main(args))
    except Exception as exc:
        raise SystemExit(f"controller error: {exc}")


if __name__ == "__main__":
    main()
