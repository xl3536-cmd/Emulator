#!/usr/bin/env python3
import logging
import threading
import random
import tkinter as tk
from tkinter import ttk, messagebox

from pymodbus.server.sync import ModbusSerialServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.transaction import ModbusRtuFramer

# ---- Fixed serial settings to match the Taidacent RS485 Modbus sensor ----
PORT = "/dev/ttyACM0"
UNIT_ID = 1

BAUDRATE = 9600
PARITY = "N"
STOPBITS = 1
BYTESIZE = 8
TIMEOUT = 1  # small so stop works

logging.basicConfig(level=logging.WARNING)

server = None
server_thread = None
stop_event = threading.Event()
lock = threading.Lock()


def to_raw100(x: float) -> int:
    """Magnification=100: 25.06C -> 2506"""
    return int(round(x * 100.0))


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class AliasedHR(ModbusSequentialDataBlock):
    """
    Store:
      HR[1] = temperature (x100)
      HR[2] = humidity    (x100)

    Accept BOTH conventions:
      - READ addr=0,count=2 -> mapped to addr=1,count=2 -> (temp, hum)
      - READ addr=1,count=2 -> (temp, hum)
    """
    def _map_addr(self, address: int) -> int:
        return 1 if address == 0 else address

    def getValues(self, address, count=1):
        mapped = self._map_addr(address)
        vals = super().getValues(mapped, count)
        print(f"[EMU] READ  fc=3 addr={address}(mapped={mapped}) count={count} -> {list(vals)}", flush=True)
        return vals

    def setValues(self, address, values):
        mapped = self._map_addr(address)
        print(f"[EMU] WRITE addr={address}(mapped={mapped}) values={list(values)}", flush=True)
        return super().setValues(mapped, values)


class App:
    def __init__(self, root):
        self.root = root
        root.title("Temp/Hum Sensor Emulator (Modbus RTU)")

        # status
        self.status = tk.StringVar(value="Stopped")

        # UI values (entry + sliders are kept in sync)
        self.temp_ui = tk.DoubleVar(value=27.65)
        self.hum_ui = tk.DoubleVar(value=17.46)

        # internal measured state
        self.temp_meas = float(self.temp_ui.get())
        self.hum_meas = float(self.hum_ui.get())

        # behavior controls
        self.auto_follow_ui = tk.BooleanVar(value=True)
        self.add_noise = tk.BooleanVar(value=True)
        self.freeze_output = tk.BooleanVar(value=False)

        # jitter / update interval dropdown (default 2s)
        self.interval_options_ms = [
            ("0.5 s", 500),
            ("1 s", 1000),
            ("2 s (default)", 2000),
            ("3 s", 3000),
            ("5 s", 5000),
        ]
        self.interval_label_to_ms = {k: v for k, v in self.interval_options_ms}
        self.update_interval_label = tk.StringVar(value="2 s (default)")
        self.update_period_ms = self.interval_label_to_ms[self.update_interval_label.get()]

        # noise amplitude (you can tune these)
        self.temp_noise_amp = 0.05   # +/- °C
        self.hum_noise_amp = 0.20    # +/- %RH

        # lag factor toward target when auto-follow is enabled
        self.alpha = 0.45  # higher = faster convergence per tick

        # modbus registers
        self.hr = AliasedHR(0, [0] * 30)
        self._write_regs(self.temp_meas, self.hum_meas)

        self.context = ModbusServerContext(
            slaves={UNIT_ID: ModbusSlaveContext(hr=self.hr)},
            single=False
        )

        self._build_ui()
        self._update_reg_view()
        self.start_server()

        # periodic loops
        self._tick_reg_view()
        self._tick_measurement()

    # ---------- UI ----------
    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        # Connection
        conn = ttk.LabelFrame(frm, text="Connection")
        conn.grid(row=0, column=0, sticky="ew", pady=6)

        ttk.Label(conn, text=f"Port: {PORT}").grid(row=0, column=0, sticky="w")
        ttk.Label(conn, text=f"Unit ID: {UNIT_ID}").grid(row=0, column=1, sticky="w", padx=12)
        ttk.Label(conn, text="Status:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(conn, textvariable=self.status).grid(row=1, column=1, sticky="w", pady=(6, 0))

        btns = ttk.Frame(conn)
        btns.grid(row=0, column=2, rowspan=2, padx=(12, 0))
        ttk.Button(btns, text="Reconnect (Start)", command=self.start_server).grid(row=0, column=0, sticky="ew", pady=2)
        ttk.Button(btns, text="Disconnect (Stop)", command=self.stop_server).grid(row=1, column=0, sticky="ew", pady=2)

        # Values
        vals = ttk.LabelFrame(frm, text="Values (setpoint via slider or entry)")
        vals.grid(row=1, column=0, sticky="ew", pady=6)
        vals.columnconfigure(1, weight=1)
        vals.columnconfigure(4, weight=1)

        # Temperature slider + entry
        ttk.Label(vals, text="Temperature (°C):").grid(row=0, column=0, sticky="w")
        self.temp_scale = ttk.Scale(
            vals, from_=-30.0, to=150.0, orient="horizontal",
            variable=self.temp_ui, command=self._on_temp_slider
        )
        self.temp_scale.grid(row=0, column=1, sticky="ew", padx=6)

        self.temp_entry = ttk.Entry(vals, width=10)
        self.temp_entry.grid(row=0, column=2, sticky="w")
        self.temp_entry.insert(0, f"{self.temp_ui.get():.2f}")
        ttk.Label(vals, text="Range: -30..150").grid(row=0, column=3, sticky="w", padx=(12, 0))

        # Humidity slider + entry
        ttk.Label(vals, text="Humidity (%RH):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.hum_scale = ttk.Scale(
            vals, from_=0.0, to=100.0, orient="horizontal",
            variable=self.hum_ui, command=self._on_hum_slider
        )
        self.hum_scale.grid(row=1, column=1, sticky="ew", padx=6, pady=(8, 0))

        self.hum_entry = ttk.Entry(vals, width=10)
        self.hum_entry.grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.hum_entry.insert(0, f"{self.hum_ui.get():.2f}")
        ttk.Label(vals, text="Range: 0..100").grid(row=1, column=3, sticky="w", padx=(12, 0), pady=(8, 0))

        # Apply Once
        ttk.Button(vals, text="Apply Once", command=self.apply_once).grid(row=0, column=4, rowspan=2, padx=(12, 0), sticky="ns")

        # Behavior
        beh = ttk.LabelFrame(frm, text="Behavior")
        beh.grid(row=2, column=0, sticky="ew", pady=6)

        ttk.Checkbutton(beh, text="Auto-follow UI (continuous updating)", variable=self.auto_follow_ui).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(beh, text="Add noise/jitter", variable=self.add_noise).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Checkbutton(beh, text="Freeze output (stuck value)", variable=self.freeze_output).grid(row=0, column=2, sticky="w", padx=(12, 0))

        # Interval dropdown (default 2s)
        ttk.Label(beh, text="Update interval:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        interval_combo = ttk.Combobox(
            beh, textvariable=self.update_interval_label,
            values=[k for k, _ in self.interval_options_ms],
            state="readonly", width=16
        )
        interval_combo.grid(row=1, column=1, sticky="w", pady=(8, 0))
        interval_combo.bind("<<ComboboxSelected>>", self._on_interval_change)

        # Register view
        reg = ttk.LabelFrame(frm, text="Register View (what master reads)")
        reg.grid(row=3, column=0, sticky="ew", pady=6)
        self.reg_label = ttk.Label(reg, text="")
        self.reg_label.grid(row=0, column=0, sticky="w")

        ttk.Button(frm, text="Quit", command=self.on_quit).grid(row=4, column=0, sticky="e", pady=(8, 0))

        # Bind entry edits
        self.temp_entry.bind("<Return>", lambda e: self._entry_to_slider("temp"))
        self.hum_entry.bind("<Return>", lambda e: self._entry_to_slider("hum"))
        self.temp_entry.bind("<FocusOut>", lambda e: self._entry_to_slider("temp"))
        self.hum_entry.bind("<FocusOut>", lambda e: self._entry_to_slider("hum"))

    def _on_temp_slider(self, _):
        self.temp_entry.delete(0, tk.END)
        self.temp_entry.insert(0, f"{self.temp_ui.get():.2f}")

    def _on_hum_slider(self, _):
        self.hum_entry.delete(0, tk.END)
        self.hum_entry.insert(0, f"{self.hum_ui.get():.2f}")

    def _entry_to_slider(self, which: str):
        try:
            if which == "temp":
                v = float(self.temp_entry.get())
                v = clamp(v, -30.0, 150.0)
                self.temp_ui.set(v)
                self._on_temp_slider(None)
            else:
                v = float(self.hum_entry.get())
                v = clamp(v, 0.0, 100.0)
                self.hum_ui.set(v)
                self._on_hum_slider(None)
        except ValueError:
            # revert entry to slider value
            if which == "temp":
                self._on_temp_slider(None)
            else:
                self._on_hum_slider(None)

    def _on_interval_change(self, _event=None):
        label = self.update_interval_label.get()
        self.update_period_ms = self.interval_label_to_ms.get(label, 2000)

    # ---------- Modbus register handling ----------
    def _write_regs(self, temp_c: float, hum_pct: float):
        with lock:
            self.hr.setValues(1, [to_raw100(temp_c)])  # temp
            self.hr.setValues(2, [to_raw100(hum_pct)])  # hum

    def _update_reg_view(self):
        with lock:
            rT = self.hr.getValues(1, 1)[0]
            rH = self.hr.getValues(2, 1)[0]
        self.reg_label.config(
            text=f"HR[1]={rT} (T={rT/100:.2f}C)   HR[2]={rH} (H={rH/100:.2f}%)   "
                 f"(addr=0 aliased→1)"
        )

    def apply_once(self):
        """Set measured output immediately to the UI values."""
        t = float(self.temp_ui.get())
        h = float(self.hum_ui.get())
        self.temp_meas = clamp(t, -30.0, 150.0)
        self.hum_meas = clamp(h, 0.0, 100.0)
        self._write_regs(self.temp_meas, self.hum_meas)
        self._update_reg_view()

    # ---------- Periodic loops ----------
    def _tick_reg_view(self):
        self._update_reg_view()
        self.root.after(500, self._tick_reg_view)

    def _tick_measurement(self):
        """
        Update registers like a real sensor would:
        - Every update_period_ms (default 2000ms)
        - Optionally converge toward UI setpoint (auto-follow)
        - Optionally add noise/jitter
        """
        if not self.freeze_output.get():
            t_target = float(self.temp_ui.get())
            h_target = float(self.hum_ui.get())

            if self.auto_follow_ui.get():
                self.temp_meas = (1 - self.alpha) * self.temp_meas + self.alpha * t_target
                self.hum_meas = (1 - self.alpha) * self.hum_meas + self.alpha * h_target
            else:
                # if not auto-follow, we keep the last measured values (unless user presses Apply Once)
                pass

            if self.add_noise.get():
                self.temp_meas += random.uniform(-self.temp_noise_amp, self.temp_noise_amp)
                self.hum_meas += random.uniform(-self.hum_noise_amp, self.hum_noise_amp)

            self.temp_meas = clamp(self.temp_meas, -30.0, 150.0)
            self.hum_meas = clamp(self.hum_meas, 0.0, 100.0)

            self._write_regs(self.temp_meas, self.hum_meas)

        self.root.after(self.update_period_ms, self._tick_measurement)

    # ---------- Server control ----------
    def start_server(self):
        global server, server_thread, stop_event

        self.stop_server()
        stop_event.clear()

        def serve():
            global server
            try:
                self.status.set(f"Running ({BAUDRATE} 8N1) on {PORT}")
                server = ModbusSerialServer(
                    context=self.context,
                    framer=ModbusRtuFramer,
                    port=PORT,
                    baudrate=BAUDRATE,
                    parity=PARITY,
                    stopbits=STOPBITS,
                    bytesize=BYTESIZE,
                    timeout=TIMEOUT,
                )
                server.serve_forever()
            except Exception as e:
                if not stop_event.is_set():
                    print("[EMU] server exception:", repr(e), flush=True)
                    self.status.set(f"Error: {e}")
                    try:
                        messagebox.showerror("Server error", str(e))
                    except Exception:
                        pass
            finally:
                self.status.set("Stopped")

        server_thread = threading.Thread(target=serve, daemon=True)
        server_thread.start()

    def stop_server(self):
        global server, server_thread, stop_event
        stop_event.set()

        if server is not None:
            try:
                if getattr(server, "socket", None) is not None:
                    try:
                        server.socket.close()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass

        server = None
        server_thread = None
        self.status.set("Stopped")

    def on_quit(self):
        self.stop_server()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
