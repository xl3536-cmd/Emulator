#!/usr/bin/env python3
"""Manage the existing C MS/TP emulator from a desktop GUI."""
import argparse
from collections import deque
import copy
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import uuid

from run import ROOT, MODES, prepare
from group_config import adapter_key, device_config, validate_devices

LIVE_FIELDS = {
    "local_control_mode": ("initial", "control_mode", 1, 12, True),
    "local_operating_mode": ("initial", "operating_mode", 1, 4, True),
    "local_setpoint": ("initial", "setpoint", 0, 100, False),
    "fault_code": ("initial", "fault_code", 0, 65535, True),
    "warning_code": ("initial", "warning_code", 0, 65535, True),
    "flow_gpm": ("readings", "flow_gpm", 0, 1000000, False),
    "pressure_psi": ("readings", "pressure_psi", 0, 1000000, False),
    "power_w": ("readings", "power_w", 0, 1000000, False),
    "current_a": ("readings", "current_a", 0, 1000000, False),
    "temperature_c": ("readings", "temperature_c", -273.15, 1000, False),
    "remote_temperature_c": ("readings", "remote_temperature_c", -273.15, 1000, False),
    "electronics_temperature_c": ("readings", "electronics_temperature_c", -273.15, 1000, False),
}


class EmulatorGUI:
    def __init__(self, root, path, base_path):
        self.root, self.path = root, path
        self.base = device_config(json.loads(base_path.read_text(encoding="utf-8")))
        self.profiles = json.loads((ROOT / "pump_profiles.json").read_text(encoding="utf-8"))
        configs = json.loads(path.read_text(encoding="utf-8"))["devices"] if path.exists() else [copy.deepcopy(self.base)]
        self.configs = {uuid.uuid4().hex: device_config(cfg) for cfg in configs}
        for cfg in configs:
            prepare(cfg)
        for key, cfg in self.configs.items():
            self.validate_unique(key, cfg)
        self.running, self.history, self.snapshots, self.pending = {}, {}, {}, {}
        self.groups = {}
        self.events = queue.Queue()
        self.current = None
        self.closing = False
        root.title("Grundfos MS/TP pump emulator")
        root.geometry("1150x830")
        root.protocol("WM_DELETE_WINDOW", self.close)
        ttk.Label(root, text="Emulator → USB/RS485 → real BASrouter → controller", font=("TkDefaultFont", 13, "bold")).pack(anchor="w", padx=12, pady=8)
        ttk.Label(root, text="Pumps with the same serial path share one adapter group. Different paths create independent groups.").pack(anchor="w", padx=12)
        body = ttk.Frame(root, padding=10)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=(0, 10))
        self.devices = ttk.Treeview(left, columns=("state",), show="tree headings", height=18)
        self.devices.heading("#0", text="Emulated device")
        self.devices.column("#0", width=185)
        self.devices.heading("state", text="Process")
        self.devices.column("state", width=85)
        self.devices.pack(fill="both", expand=True)
        self.devices.bind("<<TreeviewSelect>>", self.select)
        self.profile = tk.StringVar(value="Custom device")
        profile_names = ["Custom device"] + [f"{p['id']}: {p.get('source_name', p['name'])}" for p in self.profiles]
        ttk.Combobox(left, textvariable=self.profile, values=profile_names, state="readonly", width=32).pack(fill="x", pady=5)
        for label, action in [("Add device from profile", self.add), ("Remove selected", self.remove),
                              ("Save all profiles", self.save), ("Start selected adapter group", self.start),
                              ("Stop selected adapter group", self.stop_selected)]:
            ttk.Button(left, text=label, command=self.guarded(action)).pack(fill="x", pady=3)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="x")
        self.form = {}
        connection = ttk.Frame(self.tabs, padding=8)
        startup = ttk.Frame(self.tabs, padding=8)
        readings = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(connection, text="Device / serial")
        self.tabs.add(startup, text="Starting state")
        self.tabs.add(readings, text="Simulated readings")
        self.make_fields(connection, [
            ("pump.id", "Profile ID", "int"), ("pump.name", "Device name (ASCII, 32 max)", "str"),
            ("pump.device_id", "BACnet device ID", "int"), ("pump.mac", "MS/TP MAC (0..127)", "int"),
            ("serial_port", "Serial adapter path", "str"), ("baud", "Baud rate", "int"),
            ("max_master", "Max Master", "int"), ("max_info_frames", "Max Info Frames", "int"),
            ("router_mac", "BASrouter MAC (blue on router status)", "int"),
        ])
        self.make_fields(startup, [
            ("initial.bus_control", "Bus control on at startup (0/1)", "bool"),
            ("initial.control_mode", "Local control mode", "int"),
            ("initial.operating_mode", "Local operation (1 start / 2 stop / 3 min / 4 max)", "int"),
            ("initial.setpoint", "Local setpoint (%)", "float"),
            ("initial.fault_code", "Fault code (0 = none)", "int"),
            ("initial.warning_code", "Warning code (0 = none)", "int"),
            ("initial.operating_hours", "Starting operating hours", "float"),
            ("initial.on_hours", "Starting powered-on hours", "float"),
        ])
        self.make_fields(readings, [(f"readings.{key}", key, "float") for key in self.base["readings"]])
        ttk.Button(right, text="Apply profile edits (device must be stopped)", command=self.guarded(self.apply)).pack(anchor="w", pady=5)
        live = ttk.LabelFrame(right, text="Change running simulation", padding=8)
        live.pack(fill="x", pady=5)
        self.live_field = tk.StringVar(value="fault_code")
        self.live_value = tk.StringVar(value="0")
        ttk.Combobox(live, textvariable=self.live_field, values=list(LIVE_FIELDS), state="readonly", width=28).pack(side="left")
        ttk.Entry(live, textvariable=self.live_value, width=12).pack(side="left", padx=6)
        ttk.Button(live, text="Apply live", command=self.guarded(self.apply_live)).pack(side="left")
        ttk.Label(right, text="Local modes/setpoint apply while bus control is off. Controller commands retain BACnet priority behavior.\nFlow, pressure, power, and current are base readings scaled by the running setpoint. Fault > 0 stops simulated flow.", wraplength=760).pack(anchor="w", pady=4)
        self.state = tk.StringVar(value="Stopped — no serial port opened")
        ttk.Label(right, textvariable=self.state, wraplength=750).pack(anchor="w", pady=4)
        state_table = ttk.Frame(right)
        state_table.pack(fill="both", expand=True)
        self.values = ttk.Treeview(state_table, columns=("value",), show="tree headings", height=8)
        self.values.heading("#0", text="Live state")
        self.values.heading("value", text="Value")
        state_scroll = ttk.Scrollbar(state_table, orient="vertical", command=self.values.yview)
        self.values.configure(yscrollcommand=state_scroll.set)
        state_scroll.pack(side="right", fill="y")
        self.values.pack(side="left", fill="both", expand=True)
        self.log = ScrolledText(right, height=8, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, pady=5)
        for key in self.configs:
            self.add_row(key)
        if self.configs:
            self.devices.selection_set(next(iter(self.configs)))
            self.select()
        root.after(100, self.drain)

    def guarded(self, action):
        def call():
            try:
                action()
            except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
                messagebox.showerror("Emulator", str(exc), parent=self.root)
        return call

    def make_fields(self, frame, fields):
        for row, (key, label, kind) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            ttk.Entry(frame, textvariable=var, width=40).grid(row=row, column=1, sticky="ew", padx=8)
            self.form[key] = (var, kind)
        frame.columnconfigure(1, weight=1)

    def selected(self):
        if self.current is None:
            raise ValueError("Select or add a device first")
        return self.current

    def add_row(self, key):
        pump = self.configs[key]["pump"]
        self.devices.insert("", "end", iid=key, text=f"{pump['id']}: {pump['name']}", values=("Stopped",))

    def select(self, event=None):
        selection = self.devices.selection()
        if not selection:
            return
        self.current = selection[0]
        self.fill_form()
        self.show_state()
        self.show_log()

    def fill_form(self):
        cfg = self.configs[self.current]
        for key, (var, kind) in self.form.items():
            parts = key.split(".")
            value = cfg[parts[0]] if len(parts) == 1 else cfg[parts[0]][parts[1]]
            var.set(str(int(value)) if kind == "bool" else str(value))

    def validate_unique(self, key, cfg):
        pid = cfg["pump"]["id"]
        if not isinstance(pid, int) or pid < 1:
            raise ValueError("Profile ID must be a positive integer")
        for other_key, other in self.configs.items():
            if other_key == key:
                continue
            if pid == other["pump"]["id"] or cfg["pump"]["device_id"] == other["pump"]["device_id"]:
                raise ValueError("Profile IDs and BACnet device IDs must be unique")

    def apply(self):
        key = self.selected()
        if key in self.running:
            raise ValueError("Stop this adapter group to edit its profiles; use Apply live for running changes")
        cfg = copy.deepcopy(self.configs[key])
        for name, (var, kind) in self.form.items():
            value = var.get().strip()
            if kind == "bool":
                if value not in ("0", "1"):
                    raise ValueError("Bus control must be 0 or 1")
                value = value == "1"
            elif kind == "int":
                value = int(value)
            elif kind == "float":
                value = float(value)
            parts = name.split(".")
            if len(parts) == 1:
                cfg[parts[0]] = value
            else:
                cfg[parts[0]][parts[1]] = value
        cfg = device_config(cfg)
        self.validate_unique(key, cfg)
        self.configs[key] = cfg
        pump = cfg["pump"]
        self.devices.item(key, text=f"{pump['id']}: {pump['name']}")
        self.state.set("Profile applied; Save all profiles to keep it for the next session")

    def add(self):
        cfg = copy.deepcopy(self.base)
        if self.profile.get() != "Custom device":
            pid = int(self.profile.get().split(":", 1)[0])
            cfg["pump"] = copy.deepcopy(next(p for p in self.profiles if p["id"] == pid))
        else:
            pumps = [c["pump"] for c in self.configs.values()]
            pid = max((p["id"] for p in pumps), default=0) + 1
            mac = next((n for n in range(1, 128)
                        if n != cfg["router_mac"] and all(p["mac"] != n for p in pumps)), None)
            if mac is None:
                raise ValueError("No unused default MAC available")
            cfg["pump"] = dict(id=pid, name=f"Pump {pid}", mac=mac,
                               device_id=max((p["device_id"] for p in pumps), default=227010) + 1)
        key = uuid.uuid4().hex
        prepare(cfg)
        self.validate_unique(key, cfg)
        self.configs[key] = cfg
        self.add_row(key)
        self.devices.selection_set(key)
        self.select()
        self.state.set("Device added. Set its serial adapter, MAC and device ID before starting.")

    def remove(self):
        key = self.selected()
        if key in self.running:
            raise ValueError("Stop the device before removing it")
        del self.configs[key]
        self.devices.delete(key)
        self.history.pop(key, None)
        self.snapshots.pop(key, None)
        self.current = None
        if self.configs:
            self.devices.selection_set(next(iter(self.configs)))
            self.select()
        else:
            for var, _ in self.form.values():
                var.set("")
            self.show_state()
            self.show_log()

    def save(self):
        if self.current is not None and self.current not in self.running:
            self.apply()
        for key, cfg in self.configs.items():
            prepare(cfg)
            self.validate_unique(key, cfg)
        validate_devices(list(self.configs.values()))
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({"devices": list(self.configs.values())}, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        self.state.set(f"Saved {self.path.name}; running-device startup edits are not applied")

    def start(self):
        if self.closing:
            raise ValueError("The GUI is closing")
        key = self.selected()
        if key in self.running:
            raise ValueError("This adapter group is already running or starting")
        if sys.platform != "linux":
            raise ValueError("Start the emulator GUI on the Raspberry Pi/Linux desktop")
        self.apply()
        cfg = self.configs[key]
        port = adapter_key(cfg)
        if port in self.groups:
            raise ValueError("Stop this adapter group before changing its pump membership, then start it again")
        validated = validate_devices(list(self.configs.values()))
        group_configs = validated[port]
        members = [k for k, c in self.configs.items() if adapter_key(c) == port]
        by_id = {self.configs[k]["pump"]["id"]: k for k in members}
        if any(not (ROOT / "build" / name).is_file() for name in ("mstp_bus", "pump_worker")):
            raise ValueError("Build the new group executables first: python3 build.py")
        directory = tempfile.TemporaryDirectory(prefix="pump-gui-")
        config_path = Path(directory.name) / "config.json"
        try:
            config_path.write_text(json.dumps({"devices": group_configs}), encoding="utf-8")
            process = subprocess.Popen([sys.executable, "-u", str(ROOT / "run_group.py"),
                                        "--config", str(config_path), "--interactive"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                       errors="replace", bufsize=1, cwd=ROOT, start_new_session=True)
        except Exception:
            directory.cleanup()
            raise
        self.groups[port] = dict(process=process, directory=directory, members=members, ready=False)
        for member in members:
            self.running[member] = dict(process=process, group=port,
                                        config=copy.deepcopy(self.configs[member]), ready=False)
            self.snapshots.pop(member, None)
            self.devices.item(member, values=("Starting",))
        self.show_state()
        self.state.set(f"Starting {len(members)} pump stations on {port}")

        def collect():
            try:
                for line in process.stdout:
                    line = line.rstrip()
                    if line.startswith("DEVICE "):
                        parts = line.split(" ", 2)
                        if len(parts) == 3 and parts[1].isdigit() and int(parts[1]) in by_id:
                            self.events.put((by_id[int(parts[1])], "line", parts[2]))
                            continue
                    if line.startswith("BUS BUS_READY "):
                        self.events.put((port, "group_ready", line))
                    for member in members:
                        self.events.put((member, "line", line))
            finally:
                self.events.put((port, "group_exit", process.wait()))
        threading.Thread(target=collect, daemon=True).start()

    def stop_selected(self):
        self.stop(self.selected())

    def stop(self, key):
        entry = self.running.get(key)
        if not entry and key in self.configs:
            # Also allow stopping a group from a newly-added, not-yet-running
            # profile that names the same adapter.
            port = adapter_key(self.configs[key])
            group = self.groups.get(port)
            if group:
                entry = self.running.get(group["members"][0])
        if not entry:
            return
        group = self.groups[entry["group"]]
        if group.get("stopping"):
            return
        group["stopping"] = True
        process = entry["process"]
        for member in group["members"]:
            self.running[member]["ready"] = False
            self.running[member]["stopping"] = True
            self.devices.item(member, values=("Stopping",))
        if process.poll() is None:
            process.terminate()
        def force_stop():
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.root.after(4000, force_stop)

    def apply_live(self):
        key = self.selected()
        entry = self.running.get(key)
        if not entry or not entry["ready"] or entry["process"].poll() is not None:
            raise ValueError("Start the device and wait for live state first")
        if key in self.pending:
            raise ValueError("Waiting for the previous live change acknowledgement")
        field = self.live_field.get()
        section, setting, low, high, whole = LIVE_FIELDS[field]
        value = float(self.live_value.get())
        if not math.isfinite(value) or not low <= value <= high or (whole and value != int(value)):
            raise ValueError(f"{field} must be {'an integer ' if whole else ''}in {low}..{high}")
        if field == "local_control_mode" and value not in MODES:
            raise ValueError(f"Control modes: {sorted(MODES)}")
        process = entry["process"]
        pid = entry["config"]["pump"]["id"]
        process.stdin.write(f"set {pid} {field} {value:.17g}\n")
        process.stdin.flush()
        self.pending[key] = (field, int(value) if whole else value, time.monotonic())
        self.state.set(f"Sent {field}; waiting for emulator acknowledgement")

    def show_state(self):
        children = self.values.get_children()
        if children:
            self.values.delete(*children)
        for field, value in self.snapshots.get(self.current, {}).items():
            self.values.insert("", "end", text=field, values=(value,))
        if self.current is not None:
            pump = self.configs[self.current]["pump"]
            state = self.devices.item(self.current, "values")[0]
            cfg = self.configs[self.current]
            group = [c for c in self.configs.values() if adapter_key(c) == adapter_key(cfg)]
            macs = ", ".join(str(c["pump"]["mac"]) for c in group)
            self.state.set(f"{pump['name']}: {state}; device {pump['device_id']}, MAC {pump['mac']}\n"
                           f"Adapter {cfg['serial_port']} — configured pump MACs: {macs}")

    def show_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", "\n".join(self.history.get(self.current, [])))
        self.log.see("end")
        self.log.configure(state="disabled")

    def drain(self):
        try:
            while True:
                key, kind, data = self.events.get_nowait()
                if kind == "group_ready":
                    group = self.groups[key]
                    group["ready"] = True
                    for member in group["members"]:
                        entry = self.running[member]
                        if member in self.snapshots and not entry.get("stopping"):
                            entry["ready"] = True
                            self.devices.item(member, values=("Running",))
                    self.show_state()
                    continue
                if kind == "group_exit":
                    group = self.groups.pop(key)
                    try:
                        group["process"].stdin.close()
                    except OSError:
                        pass
                    group["process"].stdout.close()
                    group["directory"].cleanup()
                    for member in group["members"]:
                        self.running.pop(member, None)
                        self.pending.pop(member, None)
                        self.devices.item(member, values=(f"Exited {data}",))
                        self.history.setdefault(member, deque(maxlen=400)).append(
                            f"Adapter group exited ({data}). Displayed values are the last snapshot.")
                    self.show_state()
                    self.show_log()
                    continue
                elif data.startswith("STATE "):
                    try:
                        self.snapshots[key] = json.loads(data[6:])
                    except ValueError:
                        continue
                    entry = self.running.get(key)
                    if entry and self.groups[entry["group"]]["ready"] and not entry.get("stopping"):
                        entry["ready"] = True
                        self.devices.item(key, values=("Running",))
                    if key == self.current:
                        self.show_state()
                    continue
                elif data.startswith("APPLIED "):
                    pending = self.pending.get(key)
                    if pending and data.split()[1] == pending[0]:
                        field, value, _ = self.pending.pop(key)
                        section, setting, *_ = LIVE_FIELDS[field]
                        self.configs[key][section][setting] = value
                        if key == self.current:
                            self.form[f"{section}.{setting}"][0].set(str(value))
                elif data.startswith("ERROR "):
                    self.pending.pop(key, None)
                self.history.setdefault(key, deque(maxlen=400)).append(data)
                if key == self.current:
                    self.show_log()
        except queue.Empty:
            pass
        for key, (_, _, started) in list(self.pending.items()):
            if time.monotonic() - started > 5:
                self.pending.pop(key)
                self.history.setdefault(key, deque(maxlen=400)).append("No live-change acknowledgement; rebuild the updated emulator if needed.")
                if key == self.current:
                    self.show_log()
        if self.closing and not self.running:
            self.root.destroy()
            return
        self.root.after(100, self.drain)

    def close(self):
        self.closing = True
        for key in list(self.running):
            self.stop(key)
        self.state.set("Stopping emulator processes before closing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "gui_devices.json", help="GUI device list; created by Save all profiles")
    parser.add_argument("--base-config", type=Path, default=ROOT / "config.json", help="existing single-device defaults")
    args = parser.parse_args()
    root = tk.Tk()
    try:
        EmulatorGUI(root, args.config.resolve(), args.base_config.resolve())
    except (OSError, ValueError, KeyError) as exc:
        messagebox.showerror("Cannot open configuration", str(exc), parent=root)
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
