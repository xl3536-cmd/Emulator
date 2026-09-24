#!/usr/bin/env python3
"""
Date: 03-27-2026
Author: Xiaxin Liu

Arctic Heat Pump Modbus Emulator (pymodbus 3.12.1) — Enhanced Manual Controls

Adds:
- Right-panel "Set value" entry + Apply button
- Slider for °C registers (fast manual adjustments)
- Bitfield editor (checkbox toggles) for selected bitfield registers
- Keeps double-click edit in table

No pump logic coupling; purely manual register control.
"""

import asyncio
import threading
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import tkinter as tk
from tkinter import ttk, messagebox

from pymodbus.server import ModbusSerialServer
from pymodbus.framer import FramerType
from pymodbus.datastore import ModbusDeviceContext, ModbusServerContext, ModbusSequentialDataBlock


# ----------------------------------------------------------------------------
# Serial port configuration
PORT_INFO = {
    "Serial File": "/dev/ttyACM0",
    "Timeout": 1.5,
    "Baudrate": 2400,
    "Bytesize": 8,
    "Parity": "E",
    "Stopbits": 1,
}

# ----------------------------------------------------------------------------
# Register definitions
# (address, name, note, signed, unit, scale)
REGS: List[Tuple[int, str, str, bool, str, float]] = [
    (2000, "Unit ON/OFF", "0=OFF, 1=ON", False, "", 1.0),
    (2001, "Working mode", "0=Cooling,1=Underfloor heat,2=Fan coil heat,5=Hot water,6=Auto", False, "", 1.0),
    (2002, "Cooling temp setpoint", "model dependent", False, "°C", 1.0),
    (2003, "Heating temp setpoint", "model dependent", False, "°C", 1.0),
    (2004, "Hot water temp setpoint", "model dependent", False, "°C", 1.0),

    (2052, "Pump behavior after reaching setpoint", "0=cycle using 2053, 1=keep OFF, 2=keep ON", False, "", 1.0),
    (2053, "Water pump running interval", "see manual", False, "", 1.0),
    (2054, "Low ambient temp to run pump in standby", "see manual", True, "°C", 1.0),

    (2056, "Accept compressor freq control", "0=NO, 1=YES", False, "", 1.0),
    (2057, "Compressor freq setting value", "Hz", False, "Hz", 1.0),

    (2100, "Water tank temperature", "", True, "°C", 1.0),
    (2102, "Outlet water temperature", "", True, "°C", 1.0),
    (2103, "Inlet water temperature", "", True, "°C", 1.0),
    (2104, "Discharge temperature", "", True, "°C", 1.0),
    (2105, "Suction temperature", "", True, "°C", 1.0),
    (2107, "External coil temperature", "", True, "°C", 1.0),
    (2108, "Cooling coil temperature", "", True, "°C", 1.0),
    (2110, "Outdoor ambient temperature", "", True, "°C", 1.0),
    (2115, "Brine inlet water temperature", "", True, "°C", 1.0),
    (2116, "Brine outlet water temperature", "", True, "°C", 1.0),

    (2117, "Compressor running frequency", "", False, "Hz", 1.0),
    (2120, "AC supply/drive voltage", "", False, "V", 1.0),
    (2121, "AC current", "", False, "A", 1.0),
    (2122, "DC voltage", "", False, "V", 1.0),
    (2123, "Compressor phase current", "", False, "A", 1.0),

    (2133, "System working status bits", "bitfield", False, "", 1.0),
    (2134, "Error code bits", "bitfield", False, "", 1.0),
    (2135, "Status register 1", "bitfield", False, "", 1.0),
    (2138, "Status register 4 (protections)", "bitfield", False, "", 1.0),
]

BITFIELDS: Dict[int, Tuple[str, Dict[int, str]]] = {
    2133: ("2133 System working status bits", {
        0: "Frequency reaches upper limit",
        1: "Frequency reaches lower limit",
    }),
    2134: ("2134 Error code bits", {
        0: "Brine inlet temp sensor error",
        1: "Brine outlet temp sensor error",
        2: "Brine flow protection",
        3: "Water tank temp sensor error",
    }),
    2135: ("2135 Status register 1 bits", {
        0: "Unit ON/OFF status",
        1: "Compressor status",
        2: "High wind speed",
        3: "Medium wind speed",
        4: "Low wind speed",
        5: "Water pump",
        6: "4-way valve",
        7: "Electric heater",
        8: "Water flow switch",
        9: "High pressure switch",
        10: "Low pressure switch",
        11: "Remote ON/OFF switch",
        12: "Mode switch",
        13: "3-way valve1",
        14: "3-way valve2",
        15: "Brine side water flow switch",
    }),
    2138: ("2138 Protections bits", {
        0: "AC current protection",
        1: "Compressor current protection",
        2: "DC fan motor protection",
        3: "Bus voltage protection",
        4: "IPM temperature protection",
        5: "High discharge temp protection",
        6: "High pressure switch protection",
        7: "Low pressure switch protection",
        8: "Water flow switch protection",
        9: "Cooling external coil overheat protection",
        10: "Low ambient temp protection",
        11: "Primary circuit low pressure protection",
        12: "Secondary circuit low pressure protection",
        13: "Large inlet/outlet temp diff protection",
        14: "Low outlet water temp protection",
        15: "Compressor differential pressure protection",
    }),
}

# ----------------------------------------------------------------------------
# Conversions

def _to_raw(value: float, signed: bool, scale: float) -> int:
    try:
        raw_int = int(round(value / scale))
    except Exception:
        raw_int = 0
    return raw_int & 0xFFFF

def _from_raw(raw: int, signed: bool, scale: float) -> float:
    raw16 = raw & 0xFFFF
    if signed and raw16 >= 0x8000:
        raw16 -= 0x10000
    return raw16 * scale

def _fmt_u16_bin(val: int) -> str:
    b = format(val & 0xFFFF, "016b")
    return f"{b[0:4]} {b[4:8]} {b[8:12]} {b[12:16]}"

# ----------------------------------------------------------------------------
# Models

@dataclass(frozen=True)
class RegisterDef:
    address: int
    name: str
    note: str
    signed: bool
    unit: str
    scale: float

class DeviceEmulator:
    def __init__(self, unit_id: int, regs: List[Tuple[int, str, str, bool, str, float]]):
        self.unit_id = unit_id
        self.reg_defs: Dict[int, RegisterDef] = {}
        max_addr = 0
        for addr, name, note, signed, unit, scale in regs:
            self.reg_defs[addr] = RegisterDef(addr, name, note, signed, unit, scale)
            max_addr = max(max_addr, addr)

        self._lock = threading.Lock()
        self._raw_values: Dict[int, int] = {addr: 0 for addr in self.reg_defs}

        # +2 and addr+1 mapping below compensates 1-based addressing behavior
        # observed with current server/client combination.
        self.datablock = ModbusSequentialDataBlock(0, [0] * (max_addr + 2))
        self._push_all()

    def _push_all(self) -> None:
        for addr, raw in self._raw_values.items():
            self.datablock.setValues(addr + 1, [raw & 0xFFFF])

    def set_raw(self, addr: int, raw_u16: int) -> None:
        if addr not in self.reg_defs:
            return
        raw = raw_u16 & 0xFFFF
        with self._lock:
            self._raw_values[addr] = raw
            self.datablock.setValues(addr + 1, [raw])

    def set_display_value(self, addr: int, value: float) -> None:
        reg = self.reg_defs.get(addr)
        if not reg:
            return
        raw = _to_raw(value, reg.signed, reg.scale)
        self.set_raw(addr, raw)

    def get_raw(self, addr: int) -> int:
        with self._lock:
            return self._raw_values.get(addr, 0) & 0xFFFF

    def get_display_value(self, addr: int) -> float:
        reg = self.reg_defs.get(addr)
        if not reg:
            return 0.0
        raw = self.get_raw(addr)
        return _from_raw(raw, reg.signed, reg.scale)

# ----------------------------------------------------------------------------
# UI: Device tab (table + right-side editor)

class DeviceTab(ttk.Frame):
    COLS = ("addr", "name", "value", "raw")

    def __init__(self, parent, device: DeviceEmulator):
        super().__init__(parent)
        self.device = device

        self._filter_var = tk.StringVar(value="")
        self._selected_addr: Optional[int] = None
        self._edit_entry_cell: Optional[ttk.Entry] = None

        # right-panel state
        self.right_value_str = tk.StringVar(value="")
        self.right_raw_str = tk.StringVar(value="")
        self.right_hex_str = tk.StringVar(value="")
        self.right_bin_str = tk.StringVar(value="")
        self.right_note_str = tk.StringVar(value="")

        self.slider_var = tk.DoubleVar(value=0.0)

        self.bit_vars: Dict[int, tk.BooleanVar] = {}
        self._bit_checkbuttons: List[ttk.Checkbutton] = []

        # ===== Top bar =====
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(top, text="Filter:").pack(side="left")
        ent = ttk.Entry(top, textvariable=self._filter_var, width=28)
        ent.pack(side="left", padx=(6, 10))
        ent.bind("<KeyRelease>", lambda _e: self.refresh_table())

        ttk.Button(top, text="Apply All", command=self.apply_all_from_table).pack(side="left", padx=4)
        ttk.Button(top, text="Reset 0", command=self.reset_all_zero).pack(side="left", padx=4)

        # ===== Split panes =====
        pw = ttk.Panedwindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        left = ttk.Frame(pw)
        right = ttk.Frame(pw)
        pw.add(left, weight=4)
        pw.add(right, weight=2)

        # ===== Table =====
        self.tree = ttk.Treeview(left, columns=self.COLS, show="headings", selectmode="browse", height=22)
        for col, title, w, anchor in [
            ("addr", "Reg", 80, "e"),
            ("name", "Name", 320, "w"),
            ("value", "Value", 110, "e"),
            ("raw", "RAW", 90, "e"),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor=anchor, stretch=(col == "name"))

        ysb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)

        # ===== Right panel =====
        right.grid_columnconfigure(0, weight=1)

        self.detail_title = ttk.Label(right, text="Select a register", font=("TkDefaultFont", 10, "bold"))
        self.detail_title.grid(row=0, column=0, sticky="w", pady=(0, 6))

        meta = ttk.LabelFrame(right, text="Meta")
        meta.grid(row=1, column=0, sticky="ew")
        meta.grid_columnconfigure(1, weight=1)

        ttk.Label(meta, text="Value:").grid(row=0, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.right_value_str).grid(row=0, column=1, sticky="w")

        ttk.Label(meta, text="RAW:").grid(row=1, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.right_raw_str).grid(row=1, column=1, sticky="w")

        ttk.Label(meta, text="HEX:").grid(row=2, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.right_hex_str).grid(row=2, column=1, sticky="w")

        ttk.Label(meta, text="BIN:").grid(row=3, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.right_bin_str).grid(row=3, column=1, sticky="w")

        ttk.Label(meta, text="Note:").grid(row=4, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.right_note_str, wraplength=300, justify="left").grid(row=4, column=1, sticky="w")

        editor = ttk.LabelFrame(right, text="Manual Set")
        editor.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        editor.grid_columnconfigure(1, weight=1)

        ttk.Label(editor, text="New value:").grid(row=0, column=0, sticky="w")
        self.value_entry = ttk.Entry(editor, width=14)
        self.value_entry.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        self.value_entry.bind("<Return>", lambda _e: self.apply_right_value())

        ttk.Button(editor, text="Apply", command=self.apply_right_value).grid(row=0, column=2, sticky="e")

        # slider (shown only for °C regs)
        self.slider_frame = ttk.LabelFrame(right, text="Quick Slider (°C)")
        self.slider_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.slider = ttk.Scale(
            self.slider_frame, from_=-30.0, to=150.0, orient="horizontal",
            variable=self.slider_var, command=self._on_slider
        )
        self.slider.pack(fill="x", padx=8, pady=8)
        self.slider_frame.grid_remove()

        # bitfield editor (shown only for bitfield regs)
        self.bit_frame = ttk.LabelFrame(right, text="Bitfield Editor")
        self.bit_frame.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.bit_frame.grid_columnconfigure(0, weight=1)
        self.bit_frame.grid_remove()

        self.refresh_table()

    # ---------- table helpers ----------
    def _matches_filter(self, addr: int, name: str) -> bool:
        f = self._filter_var.get().strip().lower()
        if not f:
            return True
        return f in str(addr) or f in name.lower()

    def refresh_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for addr, reg_def in sorted(self.device.reg_defs.items()):
            if not self._matches_filter(addr, reg_def.name):
                continue
            disp = self.device.get_display_value(addr)
            raw = self.device.get_raw(addr)
            self.tree.insert("", "end", iid=str(addr), values=(addr, reg_def.name, f"{disp:g}", str(raw)))

    def _update_row(self, addr: int) -> None:
        if str(addr) not in self.tree.get_children(""):
            return
        disp = self.device.get_display_value(addr)
        raw = self.device.get_raw(addr)
        self.tree.set(str(addr), "value", f"{disp:g}")
        self.tree.set(str(addr), "raw", str(raw))

    # ---------- selection / right panel ----------
    def on_select(self, _e=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        addr = int(sel[0])
        self._selected_addr = addr
        self._update_right_panel(addr)

    def _update_right_panel(self, addr: int) -> None:
        reg = self.device.reg_defs.get(addr)
        if not reg:
            return

        self.detail_title.configure(text=f"{addr} — {reg.name}")

        raw = self.device.get_raw(addr)
        disp = self.device.get_display_value(addr)

        self.right_value_str.set(f"{disp:g} {reg.unit}".rstrip())
        self.right_raw_str.set(str(raw))
        self.right_hex_str.set(f"0x{raw:04X}")
        self.right_bin_str.set(_fmt_u16_bin(raw))
        self.right_note_str.set(reg.note or "")

        self.value_entry.delete(0, "end")
        self.value_entry.insert(0, f"{disp:g}")

        if reg.unit == "°C":
            self.slider_var.set(float(disp))
            self.slider_frame.grid()
        else:
            self.slider_frame.grid_remove()

        if addr in BITFIELDS:
            self._build_bit_editor(addr)
            self.bit_frame.grid()
        else:
            self.bit_frame.grid_remove()

    def apply_right_value(self) -> None:
        if self._selected_addr is None:
            return
        addr = self._selected_addr
        reg = self.device.reg_defs.get(addr)
        if not reg:
            return

        s = self.value_entry.get().strip()
        try:
            v = float(s)
        except ValueError:
            messagebox.showwarning("Invalid", f"Value must be numeric: {s}")
            return

        self.device.set_display_value(addr, v)
        self._update_row(addr)
        self._update_right_panel(addr)

    def _on_slider(self, _e=None):
        if self._selected_addr is None:
            return
        addr = self._selected_addr
        reg = self.device.reg_defs.get(addr)
        if not reg or reg.unit != "°C":
            return
        v = float(self.slider_var.get())
        self.device.set_display_value(addr, v)
        self._update_row(addr)
        self.right_value_str.set(f"{self.device.get_display_value(addr):g} {reg.unit}".rstrip())
        raw = self.device.get_raw(addr)
        self.right_raw_str.set(str(raw))
        self.right_hex_str.set(f"0x{raw:04X}")
        self.right_bin_str.set(_fmt_u16_bin(raw))

    def _build_bit_editor(self, addr: int) -> None:
        for cb in self._bit_checkbuttons:
            cb.destroy()
        self._bit_checkbuttons.clear()
        self.bit_vars.clear()

        title, bit_map = BITFIELDS[addr]
        self.bit_frame.configure(text=title)

        raw = self.device.get_raw(addr)

        row = 0
        for bit in sorted(bit_map.keys()):
            var = tk.BooleanVar(value=((raw >> bit) & 1) == 1)
            self.bit_vars[bit] = var

            cb = ttk.Checkbutton(
                self.bit_frame,
                text=f"Bit{bit}: {bit_map[bit]}",
                variable=var,
                command=lambda b=bit: self._on_bit_toggle(addr, b),
            )
            cb.grid(row=row, column=0, sticky="w", padx=8, pady=2)
            self._bit_checkbuttons.append(cb)
            row += 1

        ttk.Label(self.bit_frame, text="(Other bits not shown are left unchanged)").grid(
            row=row, column=0, sticky="w", padx=8, pady=(6, 8)
        )

    def _on_bit_toggle(self, addr: int, bit: int) -> None:
        raw = self.device.get_raw(addr)
        want_on = bool(self.bit_vars[bit].get())
        if want_on:
            raw |= (1 << bit)
        else:
            raw &= ~(1 << bit)
        self.device.set_raw(addr, raw)
        self._update_row(addr)
        self._update_right_panel(addr)

    # ---------- table double-click edit ----------
    def on_double_click(self, event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != "#3":
            return

        rowid = self.tree.identify_row(event.y)
        if not rowid:
            return

        bbox = self.tree.bbox(rowid, col)
        if not bbox:
            return
        x, y, w, h = bbox

        if self._edit_entry_cell:
            self._edit_entry_cell.destroy()
            self._edit_entry_cell = None

        cur = self.tree.set(rowid, "value")
        self._edit_entry_cell = ttk.Entry(self.tree)
        self._edit_entry_cell.insert(0, cur)
        self._edit_entry_cell.select_range(0, "end")
        self._edit_entry_cell.focus()
        self._edit_entry_cell.place(x=x, y=y, width=w, height=h)

        def commit(_e=None):
            if not self._edit_entry_cell:
                return
            new_val = self._edit_entry_cell.get().strip()
            self._edit_entry_cell.destroy()
            self._edit_entry_cell = None

            try:
                float(new_val)
            except ValueError:
                messagebox.showwarning("Invalid", f"Value must be numeric: {new_val}")
                return

            addr = int(rowid)
            self.device.set_display_value(addr, float(new_val))
            self._update_row(addr)
            if self._selected_addr == addr:
                self._update_right_panel(addr)

        def cancel(_e=None):
            if self._edit_entry_cell:
                self._edit_entry_cell.destroy()
                self._edit_entry_cell = None

        self._edit_entry_cell.bind("<Return>", commit)
        self._edit_entry_cell.bind("<FocusOut>", commit)
        self._edit_entry_cell.bind("<Escape>", cancel)

    # ---------- table apply/reset ----------
    def apply_all_from_table(self) -> None:
        for iid in self.tree.get_children():
            addr = int(iid)
            sval = self.tree.set(iid, "value").strip()
            try:
                v = float(sval)
            except ValueError:
                continue
            self.device.set_display_value(addr, v)
            self._update_row(addr)
        if self._selected_addr is not None:
            self._update_right_panel(self._selected_addr)

    def reset_all_zero(self) -> None:
        if not messagebox.askyesno("Reset", "Set ALL registers to 0?"):
            return
        for addr in self.device.reg_defs:
            self.device.set_display_value(addr, 0.0)
        self.refresh_table()
        if self._selected_addr is not None:
            self._update_right_panel(self._selected_addr)


# ----------------------------------------------------------------------------
# App + Server control (async server in background thread)

class ArcticEmulatorApp:
    def __init__(self, root: tk.Tk, devices: Dict[str, DeviceEmulator], port_info: Dict):
        self.root = root
        self.devices = devices
        self.port_info = port_info

        root.title("Arctic Heat Pump Emulator (Manual Control) — pymodbus 3.12.1")
        root.geometry("1200x760")
        root.minsize(980, 600)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[ModbusSerialServer] = None
        self._thread: Optional[threading.Thread] = None

        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=8, pady=8)

        self.status = tk.StringVar(value="Server stopped")
        ttk.Label(bar, textvariable=self.status).pack(side="left")

        ttk.Button(bar, text="Start", command=self.start_server).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="Stop", command=self.stop_server).pack(side="right")

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for name, dev in devices.items():
            nb.add(DeviceTab(nb, dev), text=name)

    def _build_context(self) -> ModbusServerContext:
        devmap = {}
        for dev in self.devices.values():
            devmap[dev.unit_id] = ModbusDeviceContext(hr=dev.datablock)
        return ModbusServerContext(devices=devmap, single=False)

    def start_server(self) -> None:
        if self._thread and self._thread.is_alive():
            messagebox.showinfo("Server", "Server is already running")
            return

        context = self._build_context()

        port = self.port_info["Serial File"]
        baudrate = self.port_info["Baudrate"]
        bytesize = self.port_info["Bytesize"]
        parity = self.port_info["Parity"]
        stopbits = self.port_info["Stopbits"]
        timeout = self.port_info["Timeout"]

        def runner():
            try:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

                async def main_async():
                    self._server = ModbusSerialServer(
                        context,
                        framer=FramerType.RTU,
                        port=port,
                        baudrate=baudrate,
                        bytesize=bytesize,
                        parity=parity,
                        stopbits=stopbits,
                        timeout=timeout,
                    )
                    self.root.after(
                        0,
                        lambda: self.status.set(
                            f"Running {port} @ {baudrate} (IDs: {', '.join(str(d.unit_id) for d in self.devices.values())})"
                        ),
                    )
                    await self._server.serve_forever()

                self.root.after(0, lambda: self.status.set(f"Starting {port} @ {baudrate}..."))
                self._loop.run_until_complete(main_async())

            except Exception as e:
                self.root.after(0, lambda: self.status.set(f"Error: {e}"))
                try:
                    self.root.after(0, lambda: messagebox.showerror("Server error", str(e)))
                except Exception:
                    pass
            finally:
                self.root.after(0, lambda: self.status.set("Server stopped"))
                if self._loop:
                    try:
                        self._loop.stop()
                        self._loop.close()
                    except Exception:
                        pass
                self._loop = None
                self._server = None

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()

    def stop_server(self) -> None:
        if not self._loop or not self._server:
            self.status.set("Server stopped")
            return

        async def _shutdown():
            try:
                await self._server.shutdown()
            except Exception:
                pass

        try:
            fut = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            fut.result(timeout=2.0)
        except Exception:
            pass

        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass

        self.status.set("Server stopping...")


# ----------------------------------------------------------------------------
# Defaults

def _init_default_values(device: DeviceEmulator) -> None:
    defaults = {
        2000: 0, 2001: 5, 2002: 3.0, 2003: 15.0, 2004: 20.0,
        2052: 2, 2053: 5, 2054: -1.0, 2056: 0, 2057: 0,
        2100: 26.0, 2102: 25.0, 2103: 25.0, 2104: 5.0, 2105: 3.0,
        2107: -2.0, 2108: 11.0, 2110: 4.0, 2115: 0.0, 2116: 0.0,
        2117: 0, 2120: 247, 2121: 0, 2122: 348, 2123: 0,
        2133: 0, 2134: 0, 2135: 0, 2138: 0,
    }
    for addr, v in defaults.items():
        device.set_display_value(addr, float(v))


def main() -> None:
    dev1 = DeviceEmulator(unit_id=1, regs=REGS)
    dev4 = DeviceEmulator(unit_id=4, regs=REGS)
    _init_default_values(dev1)
    _init_default_values(dev4)

    devices = {
        "Arctic Heat Pump 1 (ID 1)": dev1,
        "Arctic Heat Pump 2 (ID 4)": dev4,
    }

    root = tk.Tk()

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Treeview", rowheight=22)
    style.configure("Treeview.Heading", font=("TkDefaultFont", 9, "bold"))

    app = ArcticEmulatorApp(root, devices, PORT_INFO)

    def on_close():
        try:
            app.stop_server()
        finally:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
