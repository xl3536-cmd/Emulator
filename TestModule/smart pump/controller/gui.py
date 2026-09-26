#!/usr/bin/env python3
"""Desktop GUI for the standalone pump controller. No imports from src."""
import argparse
import asyncio
import copy
import ipaddress
import json
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import pump_controller as controller

# Identity references only; every preset uses the current standalone BASrouter
# defaults, which may differ from the production src topology.
SOURCE_PROFILES = [
    (1, "Climate Master SP0", 11), (2, "Nordic SP0", 12),
    (3, "TESW SP0", 21), (4, "TESW SP1", 22), (5, "TESW SP2", 23),
    (6, "TESC SP0", 31), (7, "TESC SP1", 32), (8, "TESC SP2", 33),
]


def integer(text, name, low, high):
    value = int(text)
    if not low <= value <= high:
        raise ValueError(f"{name} must be {low}..{high}")
    return value


class ControllerGUI:
    def __init__(self, root, path):
        self.root, self.path = root, path
        self.cfg = json.loads(path.read_text(encoding="utf-8"))
        self.events = queue.Queue()
        self.busy = False
        self.current = None
        root.title("Grundfos pump controller")
        root.geometry("1080x800")
        root.protocol("WM_DELETE_WINDOW", self.close)
        connection = ttk.LabelFrame(root, text="Controller connection", padding=8)
        connection.pack(fill="x", padx=8, pady=5)
        self.connection = {}
        for col, (key, label, default) in enumerate([
            ("local_ip", "Controller IP / mask", "192.168.xx.xx/22"), #replace ip address
            ("local_port", "UDP port", 47808), ("device_id", "Controller device ID", 999990),
            ("timeout", "Timeout per request (s)", 5.0),
        ]):
            ttk.Label(connection, text=label).grid(row=0, column=col, sticky="w", padx=4)
            var = tk.StringVar(value=str(self.cfg.get(key, default)))
            self.connection[key] = var
            ttk.Entry(connection, textvariable=var, width=24).grid(row=1, column=col, padx=4)
        body = ttk.Frame(root, padding=8)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=(0, 12))
        self.devices = tk.Listbox(left, width=30, exportselection=False, height=16)
        self.devices.pack(fill="both", expand=True)
        self.devices.bind("<<ListboxSelect>>", self.select)
        self.profile = tk.StringVar(value="Custom device")
        ttk.Combobox(left, textvariable=self.profile,
                     values=["Custom device"] + [f"{p[0]}: {p[1]}" for p in SOURCE_PROFILES],
                     state="readonly", width=28).pack(fill="x", pady=5)
        for label, action in [("Add device", self.add), ("Remove selected", self.remove),
                              ("Save configuration", self.save)]:
            ttk.Button(left, text=label, command=self.guarded(action)).pack(fill="x", pady=3)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        form = ttk.LabelFrame(right, text="Selected pump / real BASrouter", padding=8)
        form.pack(fill="x")
        self.fields = {}
        for i, (key, label) in enumerate([
            ("id", "Pump ID"), ("name", "Name"), ("device_id", "Pump device ID"),
            ("router_ip", "BASrouter IP"), ("router_port", "Router UDP port"),
            ("mstp_network", "MS/TP network"), ("mac", "Pump MS/TP MAC"),
        ]):
            ttk.Label(form, text=label).grid(row=i // 2 * 2, column=i % 2, sticky="w")
            var = tk.StringVar()
            self.fields[key] = var
            ttk.Entry(form, textvariable=var, width=34).grid(row=i // 2 * 2 + 1, column=i % 2, sticky="ew", padx=(0, 8))
        self.enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="Enabled", variable=self.enabled).grid(row=7, column=1)
        ttk.Button(form, text="Apply device edits", command=self.guarded(self.apply)).grid(row=8, column=0, sticky="w", pady=5)
        self.target = tk.StringVar()
        ttk.Label(right, textvariable=self.target, wraplength=650).pack(anchor="w", pady=5)
        actions = ttk.LabelFrame(right, text="BACnet commands to selected pump", padding=8)
        actions.pack(fill="x", pady=5)
        row = ttk.Frame(actions)
        row.pack(fill="x")
        self.priority = tk.StringVar(value="8")
        ttk.Label(row, text="Priority").pack(side="left")
        ttk.Combobox(row, textvariable=self.priority, values=[i for i in range(1, 17) if i != 6], state="readonly", width=4).pack(side="left", padx=5)
        for label, obj, value in [("Bus on", "binary-output,0", "1"), ("Local", "binary-output,0", "0"),
                                  ("Start", "multi-state-output,1", "1"), ("Stop", "multi-state-output,1", "2")]:
            ttk.Button(row, text=label, command=lambda o=obj, v=value: self.submit("write", o, v)).pack(side="left", padx=2)
        row = ttk.Frame(actions)
        row.pack(fill="x", pady=5)
        self.output = tk.StringVar(value="analog-output,0")
        ttk.Combobox(row, textvariable=self.output, values=list(controller.OUTPUTS), state="readonly", width=23).pack(side="left")
        self.value = tk.StringVar(value="50")
        ttk.Entry(row, textvariable=self.value, width=12).pack(side="left", padx=5)
        ttk.Button(row, text="Write", command=lambda: self.submit("write", self.output.get(), self.value.get())).pack(side="left")
        ttk.Button(row, text="Release priority", command=lambda: self.submit("write", self.output.get(), "null")).pack(side="left", padx=5)
        ttk.Label(actions, text="AO0: % | AO5: m3/h | MSO1: 1 start, 2 stop, 3 min, 4 max\nMSO0: 1 curve, 2 pressure, 3 proportional, 4 auto, 5 flow, 6 temperature, 9 flow-adapt, 12 differential", wraplength=650).pack(anchor="w")
        reads = ttk.LabelFrame(right, text="ReadProperty", padding=8)
        reads.pack(fill="x", pady=5)
        self.obj = tk.StringVar(value="analog-input,5")
        self.prop = tk.StringVar(value="present-value")
        self.index = tk.StringVar()
        for label, var, width in [("Object", self.obj, 23), ("Property", self.prop, 19), ("Index (optional)", self.index, 6)]:
            ttk.Label(reads, text=label).pack(side="left")
            ttk.Entry(reads, textvariable=var, width=width).pack(side="left", padx=4)
        ttk.Button(reads, text="Read", command=lambda: self.submit("read", self.obj.get(), self.prop.get(), self.index.get())).pack(side="left")
        row = ttk.Frame(right)
        row.pack(fill="x")
        ttk.Button(row, text="Read pump status", command=lambda: self.submit("status")).pack(side="left")
        self.poll = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Refresh selected pump every 5 seconds", variable=self.poll).pack(side="left", padx=10)
        self.state = tk.StringVar(value="Idle — no connection opened yet")
        ttk.Label(right, textvariable=self.state).pack(anchor="w", pady=4)
        self.log = ScrolledText(right, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)
        self.refresh_list(0)
        root.after(100, self.drain)
        root.after(5000, self.auto_refresh)

    def guarded(self, action):
        def call():
            try:
                action()
            except (ValueError, KeyError, OSError) as exc:
                messagebox.showerror("Configuration", str(exc), parent=self.root)
        return call

    def refresh_list(self, selected=None):
        self.devices.delete(0, "end")
        for pump in self.cfg.get("pumps", []):
            self.devices.insert("end", f"{pump['id']}: {pump['name']}")
        if selected is not None and self.cfg.get("pumps"):
            self.devices.selection_set(selected)
            self.select()
        else:
            self.current = None
            for var in self.fields.values():
                var.set("")
            self.target.set("Add or select a device")

    def select(self, event=None):
        selected = self.devices.curselection()
        if not selected:
            return
        self.current = selected[0]
        pump = self.cfg["pumps"][self.current]
        for key, var in self.fields.items():
            var.set(str(pump.get(key, self.cfg.get(key, ""))))
        self.enabled.set(pump.get("enabled", True))
        self.target.set("Destination: " + controller.destination(self.cfg, pump))

    def apply(self):
        if self.current is None:
            raise ValueError("Select or add a device first")
        pump = {key: var.get().strip() for key, var in self.fields.items()}
        for key, low, high in [("id", 1, 1000000), ("device_id", 0, 4194302),
                               ("mac", 0, 127), ("mstp_network", 1, 65534), ("router_port", 1, 65535)]:
            pump[key] = integer(pump[key], key, low, high)
        ipaddress.IPv4Address(pump["router_ip"])
        if not pump["name"]:
            raise ValueError("Pump name is required")
        pump["enabled"] = self.enabled.get()
        for i, other in enumerate(self.cfg["pumps"]):
            if i == self.current:
                continue
            if pump["id"] == int(other["id"]) or pump["device_id"] == int(other["device_id"]):
                raise ValueError("Pump IDs and BACnet device IDs must be unique")
            if controller.destination(self.cfg, pump) == controller.destination(self.cfg, other):
                raise ValueError("Another configured pump uses this router/network/MAC")
        self.cfg["pumps"][self.current].update(pump)
        self.refresh_list(self.current)

    def add(self):
        pumps = self.cfg.setdefault("pumps", [])
        if self.profile.get() != "Custom device":
            preset_id = int(self.profile.get().split(":", 1)[0])
            pid, name, mac = next(p for p in SOURCE_PROFILES if p[0] == preset_id)
            device_id = 227000 + mac
            if any(int(p["id"]) == pid or int(p["device_id"]) == device_id for p in pumps):
                raise ValueError("This profile ID or device ID is already configured")
            candidate = dict(id=pid, name=name, device_id=device_id, mac=mac, enabled=True)
            if any(controller.destination(self.cfg, p) == controller.destination(self.cfg, candidate) for p in pumps):
                raise ValueError("A configured device already uses this destination")
            pumps.append(candidate)
            self.refresh_list(len(pumps) - 1)
            return
        used = {int(p["mac"]) for p in pumps}
        mac = next((n for n in range(1, 128) if n not in used), None)
        if mac is None:
            raise ValueError("No unused default MAC; edit/remove a device first")
        pid = max((int(p["id"]) for p in pumps), default=0) + 1
        device_id = max((int(p["device_id"]) for p in pumps), default=227010) + 1
        if device_id > 4194302:
            raise ValueError("Set an unused device ID below 4194302 before adding")
        pumps.append(dict(id=pid, name=f"Pump {pid}", device_id=device_id, mac=mac, enabled=True))
        self.refresh_list(len(pumps) - 1)

    def remove(self):
        if self.current is not None:
            del self.cfg["pumps"][self.current]
            self.refresh_list(0)

    def connection_config(self):
        cfg = copy.deepcopy(self.cfg)
        cfg.update({k: v.get().strip() for k, v in self.connection.items()})
        ipaddress.IPv4Interface(cfg["local_ip"])
        cfg["local_port"] = integer(cfg["local_port"], "UDP port", 1, 65535)
        cfg["device_id"] = integer(cfg["device_id"], "Controller device ID", 0, 4194302)
        cfg["timeout"] = float(cfg["timeout"])
        if not math.isfinite(cfg["timeout"]) or not 0 < cfg["timeout"] <= 120:
            raise ValueError("Timeout must be greater than 0 and at most 120 seconds")
        if any(int(p["device_id"]) == cfg["device_id"] for p in cfg["pumps"]):
            raise ValueError("Controller device ID must differ from every pump")
        return cfg

    def save(self):
        if self.current is not None:
            self.apply()
        cfg = self.connection_config()
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        self.cfg = cfg
        self.state.set(f"Saved {self.path.name}")

    def submit(self, action, *args):
        if self.busy:
            self.state.set("Waiting for the current request to finish")
            return
        try:
            self.apply()
            cfg = self.connection_config()
            pump = copy.deepcopy(cfg["pumps"][self.current])
            if not pump.get("enabled", True):
                raise ValueError("This pump is disabled")
            priority = int(self.priority.get())
            if action == "write":
                controller.output_value(args[0], args[1])
            if action == "read" and args[2]:
                integer(args[2], "Array index", 0, 4294967295)
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Request", str(exc), parent=self.root)
            return
        self.busy = True
        target = f"{pump['name']} ({controller.destination(cfg, pump)})"
        self.state.set(f"{action}: {target}")

        def work():
            try:
                result = asyncio.run(self.request(cfg, pump, action, args, priority))
                self.events.put((target, action, result, False))
            except BaseException as exc:
                # BACpypes protocol errors may derive directly from BaseException.
                self.events.put((target, action, str(exc) or type(exc).__name__, True))
        threading.Thread(target=work, daemon=True).start()

    async def request(self, cfg, pump, action, args, priority):
        app = controller.make_app(cfg)
        dst = controller.destination(cfg, pump)
        timeout = cfg["timeout"]

        class TimedApp:
            async def read_property(self, *a, **kw):
                return await asyncio.wait_for(app.read_property(*a, **kw), timeout)

            async def write_property(self, *a, **kw):
                return await asyncio.wait_for(app.write_property(*a, **kw), timeout)
        try:
            client = TimedApp()
            if action == "status":
                return await controller.status(client, dst)
            if action == "read":
                index = int(args[2]) if args[2] else None
                return str(await controller.read(client, dst, args[0], args[1], index))
            return await controller.write_point(client, dst, args[0], args[1], priority)
        finally:
            app.close()

    def drain(self):
        try:
            while True:
                target, action, result, failed = self.events.get_nowait()
                self.busy = False
                self.state.set(f"{'Failed' if failed else 'Complete'}: {action} — {target}")
                self.log.configure(state="normal")
                self.log.insert("end", f"\n{action.upper()} — {target}\n" + (json.dumps(result, indent=2) if isinstance(result, dict) else result) + "\n")
                if int(self.log.index("end-1c").split(".")[0]) > 1500:
                    self.log.delete("1.0", "500.0")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def auto_refresh(self):
        if (self.poll.get() and not self.busy and self.current is not None
                and self.cfg["pumps"][self.current].get("enabled", True)):
            self.submit("status")
        self.root.after(5000, self.auto_refresh)

    def close(self):
        if self.busy:
            self.poll.set(False)
            self.state.set("Wait for the current request, then close again")
            return
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=controller.ROOT / "config.json")
    args = parser.parse_args()
    root = tk.Tk()
    try:
        ControllerGUI(root, args.config.resolve())
    except (OSError, ValueError, KeyError) as exc:
        messagebox.showerror("Cannot open configuration", str(exc), parent=root)
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
