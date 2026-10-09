"""Process/pipe adapter for the bundled C MS/TP engine; no fake BACnet server."""
from collections import deque
import copy
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

from src.sensors.grundfos.points import POINTS, SIMULATION_FIELDS


ENGINE_ROOT = Path(__file__).resolve().parents[3] / "grundfos_engine"
OBJECT_KEYS = {point["object"] for point in POINTS}
SIMULATION_KEYS = {field["field"] for field in SIMULATION_FIELDS}
OVERRIDE_KEYS = {point["field"] for point in POINTS if (point.get("field") or "").startswith("ai_")}


def numeric_snapshot(data, expected):
    return isinstance(data, dict) and set(data) == expected and all(
        type(value) in (int, float) and math.isfinite(value) for value in data.values()
    )


class PumpTransportError(RuntimeError):
    pass


class AdapterGroup:
    def __init__(self, port, configs):
        self.port = port
        self.configs = copy.deepcopy(configs)
        self.process = None
        self.reader = None
        self.directory = None
        self.condition = threading.Condition()
        self.command_lock = threading.Lock()
        self.ready = False
        self.stopping = False
        self.error = None
        self.logs = deque(maxlen=60)
        self.objects = {}
        self.simulation = {}
        self.overrides = {}
        self.updated = {}
        self.pending = None

    @staticmethod
    def availability():
        if sys.platform != "linux":
            return False, "MS/TP requires Raspberry Pi OS/Linux. Configuration can be edited here."
        missing = [name for name in ("mstp_bus", "pump_worker") if not (ENGINE_ROOT / "build" / name).is_file()]
        if missing:
            return False, "Build the bundled engine first: cd backend/grundfos_engine && python3 build.py"
        return True, "MS/TP binaries available; Start checks the adapter and permissions."

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        available, message = self.availability()
        if not available:
            self.error = message
            raise PumpTransportError(message)
        try:
            self.directory = tempfile.TemporaryDirectory(prefix="grundfos-web-")
            config_path = Path(self.directory.name) / "devices.json"
            config_path.write_text(json.dumps({"devices": self.configs}), encoding="utf-8")
            self.process = subprocess.Popen(
                [sys.executable, "-u", str(ENGINE_ROOT / "run_group.py"),
                 "--config", str(config_path), "--serial-port", self.port, "--interactive"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                start_new_session=True,
            )
            self.reader = threading.Thread(target=self._read_output, name="grundfos-output", daemon=True)
            self.reader.start()
            expected = {cfg["pump"]["id"] for cfg in self.configs}
            with self.condition:
                finished = self.condition.wait_for(
                    lambda: (self.ready and expected <= self.objects.keys()) or self.error or not self.alive(),
                    timeout=12,
                )
                if not finished or self.error or not self.alive():
                    raise PumpTransportError(self.error or "Pump group did not become ready within 12 seconds")
        except (OSError, RuntimeError) as exc:
            self.error = str(exc)
            self.stop()
            raise PumpTransportError(str(exc)) from exc

    def _read_output(self):
        try:
            for line in self.process.stdout:
                self._handle_line(line.strip())
        except (OSError, ValueError) as exc:
            with self.condition:
                self.error = str(exc)
        finally:
            self.process.wait()
            with self.condition:
                self.ready = False
                if not self.stopping and not self.error:
                    self.error = f"Adapter group exited ({self.process.returncode})"
                self.condition.notify_all()

    def _handle_line(self, line):
        with self.condition:
            if line.startswith("BUS BUS_READY "):
                self.ready = True
            elif line.startswith("DEVICE "):
                try:
                    _, pid_text, content = line.split(" ", 2)
                    pid = int(pid_text)
                    if pid not in {cfg["pump"]["id"] for cfg in self.configs}:
                        raise ValueError("Unknown pump in engine output")
                    kind, _, payload = content.partition(" ")
                    if kind in ("OBJECTS", "SIMULATION", "OVERRIDES"):
                        data = json.loads(payload)
                        if kind == "OBJECTS":
                            if not numeric_snapshot(data, OBJECT_KEYS):
                                raise ValueError("Invalid object snapshot")
                            self.objects[pid] = data
                            self.updated[pid] = time.monotonic()
                        elif kind == "SIMULATION":
                            if not numeric_snapshot(data, SIMULATION_KEYS):
                                raise ValueError("Invalid simulation snapshot")
                            self.simulation[pid] = data
                        else:
                            if not isinstance(data, list) or any(not isinstance(item, str) or item not in OVERRIDE_KEYS for item in data):
                                raise ValueError("Invalid override snapshot")
                            self.overrides[pid] = data
                            if self.pending and self.pending["pid"] == pid and self.pending.get("ack"):
                                self.pending["done"] = True
                    elif kind == "APPLIED":
                        field = payload.split()[0]
                        if self.pending and self.pending["pid"] == pid and self.pending["field"] == field:
                            self.pending["ack"] = True
                    elif kind == "ERROR":
                        self.logs.append(line)
                        if self.pending and self.pending["pid"] == pid:
                            self.pending["error"] = payload
                    elif kind != "STATE":
                        self.logs.append(line)
                except (ValueError, IndexError, TypeError):
                    self.error = "Invalid state received from pump engine; rebuild the bundled engine."
            else:
                self.logs.append(line)
                if "ERROR" in line:
                    self.error = line
            self.condition.notify_all()

    def edit(self, pid, field, value):
        # One outstanding command per adapter; acknowledgements cannot cross requests.
        with self.command_lock:
            with self.condition:
                if not self.alive() or not self.ready or self.stopping or self.error:
                    raise PumpTransportError(self.error or "Start the adapter group first")
                pending = {"pid": pid, "field": field}
                self.pending = pending
                try:
                    self.process.stdin.write(f"set {pid} {field} {value:.17g}\n")
                    self.process.stdin.flush()
                    received = self.condition.wait_for(
                        lambda: pending.get("done") or pending.get("error") or self.error or not self.alive(),
                        timeout=5,
                    )
                    if pending.get("error"):
                        raise ValueError(pending["error"])
                    if self.error or not self.alive():
                        raise PumpTransportError(self.error or "Adapter group exited")
                    if not received:
                        # Never accept a late acknowledgement as the next command's result.
                        self.error = "Live edit acknowledgement timed out; stop and restart this adapter group."
                        raise PumpTransportError(self.error)
                    return {"success": True, "field": field, "value": value}
                except OSError as exc:
                    self.error = str(exc)
                    raise PumpTransportError(str(exc)) from exc
                finally:
                    self.pending = None

    def stop(self):
        with self.condition:
            self.stopping = True
            self.ready = False
        if self.alive():
            self.process.terminate()  # run_group handles SIGTERM and reaps workers.
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=2)
        if self.reader:
            self.reader.join(timeout=2)
        if self.process:
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    stream.close()
        if self.directory:
            self.directory.cleanup()
            self.directory = None

    def snapshot(self):
        with self.condition:
            alive = self.alive()
            return dict(serial_port=self.port, running=alive and self.ready and not self.stopping and not self.error,
                        active=alive, error=self.error, logs=list(self.logs),
                        devices={pid: dict(values=copy.deepcopy(values),
                                          simulation=copy.deepcopy(self.simulation.get(pid, {})),
                                          overrides=list(self.overrides.get(pid, [])),
                                          live=alive and self.ready and not self.error and not self.stopping and
                                          time.monotonic() - self.updated.get(pid, 0) < 5)
                                 for pid, values in self.objects.items()})
