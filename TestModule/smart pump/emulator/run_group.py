#!/usr/bin/env python3
"""Run one group of independent pump MACs through one real RS485 adapter."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

from group_config import validate_devices
from run import ROOT, prepare


def clean_environment():
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("BACNET_", "PUMP_"))}


def stop_children(children):
    for child in children:
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + 2
    for child in children:
        try:
            child.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
    for child in children:
        child.wait()
        for stream in (child.stdin, child.stdout):
            if stream:
                stream.close()


def serve(port, configs, interactive):
    import fcntl

    serial = Path(port).resolve(strict=True)
    if not stat.S_ISCHR(serial.stat().st_mode) or not os.access(serial, os.R_OK | os.W_OK):
        raise ValueError(f"Cannot access {serial}; check serial path and dialout permissions")
    bus_binary, worker_binary = ROOT / "build" / "mstp_bus", ROOT / "build" / "pump_worker"
    for binary, flag, expected in [(bus_binary, "--version", "pump-mstp-group-1"),
                                   (worker_binary, "--transport", "mstp-worker-1")]:
        if not binary.is_file():
            raise ValueError("Rebuild the updated emulator first: python3 build.py")
        actual = subprocess.check_output([str(binary), flag], text=True, timeout=5).strip()
        if actual != expected:
            raise ValueError(f"Unexpected {binary.name} version; run python3 build.py")
    # Same lock namespace as the original single-device run.py.
    digest = hashlib.sha256(str(serial).encode()).hexdigest()[:16]
    lock = open(Path(tempfile.gettempdir()) / f"grundfos-mstp-{digest}.lock", "a")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError(f"Another emulator group or terminal emulator is using {serial}") from None

    children, pairs, workers = [], [], {}
    selector = selectors.DefaultSelector()
    stopped = False

    def stop(signum, frame):
        nonlocal stopped
        stopped = True

    previous_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    buffers = {}
    bus_ready = False
    started_at = time.monotonic()

    def register(stream, label):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, label)
        buffers[stream.fileno()] = bytearray()

    def output(label, line):
        nonlocal bus_ready
        if label == "BUS":
            if line.startswith("BUS_READY "):
                bus_ready = True
            print(f"BUS {line}", flush=True)
        else:
            print(f"DEVICE {label} {line}", flush=True)

    def control(line):
        nonlocal stopped
        if line == "stop":
            stopped = True
            return
        parts = line.split()
        if len(parts) != 4 or parts[0] != "set":
            print("BUS ERROR expected: set PROFILE_ID FIELD VALUE", flush=True)
            return
        try:
            pid = int(parts[1])
            child = workers[pid]
            # Pump main.c validates the field and range; one short line, no shell.
            child.stdin.write(f"set {parts[2]} {parts[3]}\n".encode("ascii"))
            child.stdin.flush()
        except (ValueError, KeyError, OSError, UnicodeError) as exc:
            print(f"BUS ERROR live control failed: {exc}", flush=True)

    try:
        env = clean_environment()
        env["PUMP_PARENT_PID"] = str(os.getpid())
        for cfg in configs:
            pair = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            pairs.append(pair)
        argv = [str(bus_binary), str(serial), str(configs[0]["baud"]), str(configs[0]["max_master"])]
        for cfg, (bus_socket, _) in zip(configs, pairs):
            argv.append(f"{cfg['pump']['mac']}:{bus_socket.fileno()}:{cfg['max_info_frames']}")
        bus_fds = tuple(p[0].fileno() for p in pairs) + (lock.fileno(),)
        bus = subprocess.Popen(argv, pass_fds=bus_fds, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        children.append(bus)
        register(bus.stdout, "BUS")
        for cfg, (bus_socket, worker_socket) in zip(configs, pairs):
            worker_env = dict(env)
            worker_env.update(prepare(cfg))
            worker_env["PUMP_BUS_FD"] = str(worker_socket.fileno())
            worker_env["PUMP_GUI_CONTROL"] = "1"
            child = subprocess.Popen([str(worker_binary)], pass_fds=(worker_socket.fileno(),),
                                     env=worker_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, bufsize=0)
            children.append(child)
            pid = cfg["pump"]["id"]
            workers[pid] = child
            register(child.stdout, pid)
            bus_socket.close()
            worker_socket.close()
        if interactive:
            register(sys.stdin.buffer, "CONTROL")
        print(f"BUS Starting {len(configs)} pump stations on {serial}", flush=True)
        while not stopped:
            for key, _ in selector.select(timeout=0.05):
                stream, label = key.fileobj, key.data
                try:
                    chunk = os.read(stream.fileno(), 8192)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    if label == "CONTROL":
                        stopped = True  # GUI pipe closed; release the whole group.
                    continue
                buffer = buffers[stream.fileno()]
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, remaining = buffer.partition(b"\n")
                    buffer[:] = remaining
                    text = line.decode("utf-8", errors="replace").rstrip("\r")
                    if label == "CONTROL":
                        control(text)
                    else:
                        output(label, text)
                if len(buffer) > 65536:
                    raise ValueError("Overlong group control/log line")
            if not stopped:
                for child in children:
                    if child.poll() is not None:
                        raise RuntimeError(f"Group child {child.pid} exited ({child.returncode}); stopping the group")
                if not bus_ready and time.monotonic() - started_at > 10:
                    raise RuntimeError("Serial group did not become ready within 10 seconds")
    finally:
        for pair in pairs:
            for endpoint in pair:
                endpoint.close()
        selector.close()
        stop_children(children)
        lock.close()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "gui_devices.json")
    parser.add_argument("--serial-port", help="select one adapter group from the saved device list")
    parser.add_argument("--interactive", action="store_true", help="accept GUI control lines on stdin")
    parser.add_argument("--check", action="store_true", help="validate groups without opening adapters")
    args = parser.parse_args()
    document = json.loads(args.config.read_text(encoding="utf-8"))
    groups = validate_devices(document["devices"])
    if args.serial_port:
        port = str(Path(args.serial_port).expanduser().resolve())
        if port not in groups:
            parser.error("No configured group uses that serial adapter")
        groups = {port: groups[port]}
    if args.check:
        print(json.dumps({port: [c["pump"] for c in configs] for port, configs in groups.items()}, indent=2))
        return 0
    if len(groups) != 1:
        parser.error("Select one adapter with --serial-port, or use the GUI to start several groups")
    if sys.platform != "linux":
        parser.error("Run adapter groups on Raspberry Pi OS/Linux")
    port, configs = next(iter(groups.items()))
    return serve(port, configs, args.interactive)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(f"BUS ERROR Cannot run adapter group: {exc}")
