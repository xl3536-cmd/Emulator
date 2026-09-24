#!/usr/bin/env python3
"""
Author: Xiaxin Liu
Date: Feb-27-2026
Arctic Heat Pump Modbus Emulator (pymodbus 3.12.1) - WORKING BUILD

Fixes:
- ModbusServerContext uses devices= (NOT slaves=)
- Proper asyncio event loop in a server thread (avoids "no running event loop")
- No deprecated/unknown kwargs (e.g., allow_multiple_devices)

Run:
  python3 arctic_hp_emulator_pymodbus3121.py
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
# Serial port configuration (edit if needed)
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


def _fmt_bitfield(raw: int, bit_map: Dict[int, str]) -> str:
    raw16 = raw & 0xFFFF
    bits = format(raw16, "016b")
    lines = [
        f"RAW: {raw16}    HEX: 0x{raw16:04X}",
        f"BIN: {bits[0:4]} {bits[4:8]} {bits[8:12]} {bits[12:16]}",
        "",
    ]
    on = []
    for b in range(16):
        if (raw16 >> b) & 1:
            on.append(f"Bit{b}: {bit_map.get(b, 'Reserved/Undefined')}")
    if on:
        lines.append("ON bits:")
        lines.extend(on)
    else:
        lines.append("ON bits: (none)")
    return "\n".join(lines)


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

        self._raw_values: Dict[int, int] = {addr: 0 for addr in self.reg_defs}
        self._lock = threading.Lock()

        # Holding registers as "hr"
        self.datablock = ModbusSequentialDataBlock(0, [0] * (max_addr + 1))
        self._push_all()

    def _push_all(self) -> None:
        for addr, raw in self._raw_values.items():
            self.datablock.setValues(addr, [raw & 0xFFFF])

    def set_display_value(self, addr: int, value: float) -> None:
        reg = self.reg_defs.get(addr)
        if not reg:
            return
        raw = _to_raw(value, reg.signed, reg.scale)
        with self._lock:
            self._raw_values[addr] = raw
            self.datablock.setValues(addr, [raw])

    def get_display_value(self, addr: int) -> float:
        reg = self.reg_defs.get(addr)
        if not reg:
            return 0.0
        with self._lock:
            raw = self._raw_values.get(addr, 0)
        return _from_raw(raw, reg.signed, reg.scale)

    def get_raw(self, addr: int) -> int:
        with self._lock:
            return self._raw_values.get(addr, 0) & 0xFFFF

    def decode_bitfield(self, addr: int) -> str:
        raw = self.get_raw(addr)
        _, bit_map = BITFIELDS.get(addr, ("", {}))
        return _fmt_bitfield(raw, bit_map)


# ----------------------------------------------------------------------------
# UI helpers

class Tooltip:
    def __init__(self, widget, text_func):
        self.widget = widget
        self.text_func = text_func
        self.tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)

    def _schedule(self, _e=None):
        self._after_id = self.widget.after(400, self._show)

    def _show(self):
        if self.tip:
            return
        text = self.text_func()
        if not text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        ttk.Label(tw, text=text, padding=6, relief="solid").pack()

    def _hide(self, _e=None):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ----------------------------------------------------------------------------
# Device Tab UI

class DeviceTab(ttk.Frame):
    COLS = ("addr", "name", "value")

    def __init__(self, parent, device: DeviceEmulator):
        super().__init__(parent)
        self.device = device
        self._filter_var = tk.StringVar(value="")
        self._selected_addr: Optional[int] = None
        self._edit_entry: Optional[ttk.Entry] = None

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(top, text="Filter:").pack(side="left")
        ent = ttk.Entry(top, textvariable=self._filter_var, width=28)
        ent.pack(side="left", padx=(6, 10))
        ent.bind("<KeyRelease>", lambda _e: self.refresh_table())

        ttk.Button(top, text="Apply All", command=self.apply_all_from_table).pack(side="left", padx=4)
        ttk.Button(top, text="Reset 0", command=self.reset_all_zero).pack(side="left", padx=4)

        pw = ttk.Panedwindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        left = ttk.Frame(pw)
        right = ttk.Frame(pw)
        pw.add(left, weight=4)
        pw.add(right, weight=2)

        self.tree = ttk.Treeview(left, columns=self.COLS, show="headings", selectmode="browse", height=22)
        self.tree.heading("addr", text="Reg")
        self.tree.heading("name", text="Name")
        self.tree.heading("value", text="Value")

        self.tree.column("addr", width=80, anchor="e", stretch=False)
        self.tree.column("name", width=360, anchor="w", stretch=True)
        self.tree.column("value", width=120, anchor="e", stretch=False)

        ysb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)

        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.detail_title = ttk.Label(right, text="Select a register", font=("TkDefaultFont", 10, "bold"))
        self.detail_title.grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.detail_meta = ttk.Label(right, text="", justify="left")
        self.detail_meta.grid(row=1, column=0, sticky="w")

        self.detail_text = tk.Text(right, height=12, wrap="word")
        self.detail_text.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        self.detail_text.configure(state="disabled")

        Tooltip(ent, lambda: "Type address/name, e.g. 2135 or 'compressor'")
        self.refresh_table()

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
            val = self.device.get_display_value(addr)
            self.tree.insert("", "end", iid=str(addr), values=(addr, reg_def.name, f"{val:g}"))

    def on_select(self, _e=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        addr = int(sel[0])
        self._selected_addr = addr
        self._update_details(addr)

    def _update_details(self, addr: int) -> None:
        reg = self.device.reg_defs.get(addr)
        if not reg:
            return

        self.detail_title.configure(text=f"{addr} — {reg.name}")
        raw = self.device.get_raw(addr)
        disp = self.device.get_display_value(addr)

        meta_lines = [
            f"Display: {disp:g} {reg.unit}".rstrip(),
            f"RAW: {raw}   HEX: 0x{raw:04X}",
        ]
        if reg.note:
            meta_lines.append(f"Note: {reg.note}")
        self.detail_meta.configure(text="\n".join(meta_lines))

        if addr in BITFIELDS:
            text = self.device.decode_bitfield(addr)
        else:
            text = "Not a bitfield register."

        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

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

        if self._edit_entry:
            self._edit_entry.destroy()
            self._edit_entry = None

        cur = self.tree.set(rowid, "value")
        self._edit_entry = ttk.Entry(self.tree)
        self._edit_entry.insert(0, cur)
        self._edit_entry.select_range(0, "end")
        self._edit_entry.focus()
        self._edit_entry.place(x=x, y=y, width=w, height=h)

        def commit(_e=None):
            if not self._edit_entry:
                return
            new_val = self._edit_entry.get().strip()
            self._edit_entry.destroy()
            self._edit_entry = None

            try:
                float(new_val)
            except ValueError:
                messagebox.showwarning("Invalid", f"Value must be numeric: {new_val}")
                return

            self.tree.set(rowid, "value", new_val)
            self._apply_one(int(rowid), new_val)

        def cancel(_e=None):
            if self._edit_entry:
                self._edit_entry.destroy()
                self._edit_entry = None

        self._edit_entry.bind("<Return>", commit)
        self._edit_entry.bind("<FocusOut>", commit)
        self._edit_entry.bind("<Escape>", cancel)

    def _apply_one(self, addr: int, sval: str) -> None:
        try:
            v = float(sval)
        except ValueError:
            return
        self.device.set_display_value(addr, v)
        if self._selected_addr == addr:
            self._update_details(addr)

    def apply_all_from_table(self) -> None:
        for iid in self.tree.get_children():
            addr = int(iid)
            sval = self.tree.set(iid, "value")
            self._apply_one(addr, sval)
        self.refresh_table()

    def reset_all_zero(self) -> None:
        if not messagebox.askyesno("Reset", "Set ALL registers to 0?"):
            return
        for addr in self.device.reg_defs:
            self.device.set_display_value(addr, 0.0)
        self.refresh_table()
        if self._selected_addr is not None:
            self._update_details(self._selected_addr)


# ----------------------------------------------------------------------------
# App + Server control (async server in background thread)

class ArcticEmulatorApp:
    def __init__(self, root: tk.Tk, devices: Dict[str, DeviceEmulator], port_info: Dict):
        self.root = root
        self.devices = devices
        self.port_info = port_info

        root.title("Arctic Heat Pump Emulator (pymodbus 3.12.1)")
        root.geometry("1120x720")
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
        # pymodbus 3.12.1: ModbusServerContext(devices=None, single=True)
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
                # create loop in this thread
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

                async def main_async():
                    # create server INSIDE coroutine (running loop exists)
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
        2133: 0, 2134: 0, 2135: 3584, 2138: 0,
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
