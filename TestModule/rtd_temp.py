#!/usr/bin/env python3
# rtd_live_connected_gui.py
# Live GUI: continuously scan RTD HATs and display ONLY "connected" channels.
# Python 3.7 compatible. Requires: sudo pip3 install SMrtd

import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Tuple, Optional, List

# ---- try to import librtd early and be clear if missing ----
try:
    import librtd  # from SMrtd package
except ImportError:
    message = (
        "The 'librtd' module is not installed.\n\n"
        "Install with:\n"
        "  sudo pip3 install SMrtd\n"
    )
    print(message, file=sys.stderr)
    # Let the GUI start; we'll show a dialog too.
    librtd = None  # type: ignore

# ---------------- configuration defaults ----------------
DEFAULT_STACKS   = "0-7"   # stacks to scan
DEFAULT_CHANNELS = "1-8"   # channels to scan
DEFAULT_LOW_OHM  = 80.0    # connected if R < LOW
DEFAULT_HIGH_OHM = 200.0   # or R > HIGH
DEFAULT_PERIOD_MS = 1000   # scan every 1.0 s

# --------------- helpers ---------------
def parse_range(expr: str) -> List[int]:
    """
    Parse range strings like "0-3,5,7-8" into sorted unique ints.
    """
    result: List[int] = []
    for token in expr.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a, b = token.split("-", 1)
            a = int(a.strip()); b = int(b.strip())
            if a <= b:
                result.extend(range(a, b + 1))
            else:
                result.extend(range(a, b - 1, -1))
        else:
            result.append(int(token))
    # dedupe & sort
    return sorted(set(result))

def read_rtd(stack: int, ch: int) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Read (resistance, temperature). Returns (res, temp, err).
    Temperature is computed from resistance via the linear map:
        T = a0 + a1 * R
    with:
        a0 = -116.66666667
        a1 = 1.1111111111
    """
    if librtd is None:
        return None, None, "librtd not installed"
    try:
        # 1) read resistance from the HAT
        res = float(librtd.getRes(stack, ch))

        # 2) linear map R -> T (°C)
        a0 = -116.66666667
        a1 = 1.1111111111
        temp = a0 + a1 * res

        return res, temp, None
    except Exception as e:
        return None, None, str(e)


# --------------- GUI ---------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RTD Live — Connected Channels Only")
        self.minsize(680, 420)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # top controls
        self._build_controls()

        # table
        self._build_table()

        # internal state
        self._timer_id: Optional[str] = None
        self._rows: Dict[Tuple[int,int], str] = {}  # (stack,ch) -> tree item id

        # warn once if librtd missing
        if librtd is None:
            self.after(100, lambda: messagebox.showerror(
                "librtd not found",
                "The 'librtd' module is not installed.\n\n"
                "Install with:\n  sudo pip3 install SMrtd"
            ))

    # ---------- UI builders ----------
    def _build_controls(self):
        f = ttk.LabelFrame(self, text="Scan settings")
        f.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        f.grid_columnconfigure(8, weight=1)

        ttk.Label(f, text="Stacks").grid(row=0, column=0, padx=(8,4), pady=6, sticky="e")
        self.var_stacks = tk.StringVar(value=DEFAULT_STACKS)
        ttk.Entry(f, width=10, textvariable=self.var_stacks).grid(row=0, column=1, padx=4, pady=6, sticky="w")

        ttk.Label(f, text="Channels").grid(row=0, column=2, padx=(16,4), pady=6, sticky="e")
        self.var_channels = tk.StringVar(value=DEFAULT_CHANNELS)
        ttk.Entry(f, width=10, textvariable=self.var_channels).grid(row=0, column=3, padx=4, pady=6, sticky="w")

        ttk.Label(f, text="LOW Ω").grid(row=0, column=4, padx=(16,4), pady=6, sticky="e")
        self.var_low = tk.DoubleVar(value=DEFAULT_LOW_OHM)
        ttk.Entry(f, width=7, textvariable=self.var_low).grid(row=0, column=5, padx=4, pady=6, sticky="w")

        ttk.Label(f, text="HIGH Ω").grid(row=0, column=6, padx=(16,4), pady=6, sticky="e")
        self.var_high = tk.DoubleVar(value=DEFAULT_HIGH_OHM)
        ttk.Entry(f, width=7, textvariable=self.var_high).grid(row=0, column=7, padx=4, pady=6, sticky="w")

        ttk.Label(f, text="Refresh (ms)").grid(row=0, column=8, padx=(16,4), pady=6, sticky="e")
        self.var_period = tk.IntVar(value=DEFAULT_PERIOD_MS)
        ttk.Entry(f, width=8, textvariable=self.var_period).grid(row=0, column=9, padx=4, pady=6, sticky="w")

        self.btn = ttk.Button(f, text="Start", command=self._toggle)
        self.btn.grid(row=0, column=10, padx=(16,8), pady=6)

        # Rule shown
        self.rule_lbl = ttk.Label(f, text=self._rule_text(), foreground="gray")
        self.rule_lbl.grid(row=1, column=0, columnspan=11, sticky="w", padx=8, pady=(0,6))

    def _build_table(self):
        box = ttk.LabelFrame(self, text="Connected channels (live)")
        box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10))
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(0, weight=1)

        cols = ("stack","ch","res","temp","updated")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", height=12)
        self.tree.grid(row=0, column=0, sticky="nsew")

        for c, txt, w in [
            ("stack","Stack",70),
            ("ch","Ch",50),
            ("res","Resistance (Ω)",140),
            ("temp","Temp (°C)",110),
            ("updated","Last Update",120),
        ]:
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="e")

        # scrollbar
        yscroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.grid(row=0, column=1, sticky="ns")

        # footer
        self.count_lbl = ttk.Label(box, text="0 connected")
        self.count_lbl.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=6)

    # ---------- scanning ----------
    def _toggle(self):
        if self._timer_id is None:
            self._start()
        else:
            self._stop()

    def _start(self):
        # re-evaluate rule label
        self.rule_lbl.config(text=self._rule_text())
        self.btn.config(text="Stop")
        # kick off the loop now
        self._scan_once()
        # schedule subsequent scans
        self._schedule_next()

    def _stop(self):
        self.btn.config(text="Start")
        if self._timer_id is not None:
            self.after_cancel(self._timer_id)
            self._timer_id = None

    def _schedule_next(self):
        period = max(100, int(self.var_period.get()))
        self._timer_id = self.after(period, self._tick)

    def _tick(self):
        # one pass + schedule next
        self._scan_once()
        self._schedule_next()

    def _rule_text(self) -> str:
        return f"Connected rule:  R < {self.var_low.get():.1f} Ω  OR  R > {self.var_high.get():.1f} Ω"

    def _scan_once(self):
        stacks = parse_range(self.var_stacks.get() or DEFAULT_STACKS)
        chans  = parse_range(self.var_channels.get() or DEFAULT_CHANNELS)
        low    = float(self.var_low.get())
        high   = float(self.var_high.get())

        now_str = time.strftime("%H:%M:%S")

        seen_connected: Dict[Tuple[int,int], bool] = {}

        for s in stacks:
            for ch in chans:
                res, temp, err = read_rtd(s, ch)
                if res is None:
                    # treat read errors as not connected; remove if present
                    key = (s, ch)
                    if key in self._rows:
                        self.tree.delete(self._rows[key])
                        del self._rows[key]
                    continue

                connected = (res > low) and (res < high)
                key = (s, ch)
                if connected:
                    seen_connected[key] = True
                    text_row = (f"{s}", f"{ch}", f"{res:.2f}", f"{temp:.2f}", now_str)
                    if key in self._rows:
                        self.tree.item(self._rows[key], values=text_row)
                    else:
                        iid = self.tree.insert("", "end", values=text_row)
                        self._rows[key] = iid
                else:
                    # no longer connected -> remove if present
                    if key in self._rows:
                        self.tree.delete(self._rows[key])
                        del self._rows[key]

        # Clean up entries that vanished from scan (e.g., narrowed range)
        for key in list(self._rows.keys()):
            if key not in seen_connected:
                s, ch = key
                if s not in stacks or ch not in chans:
                    self.tree.delete(self._rows[key])
                    del self._rows[key]

        self.count_lbl.config(text=f"{len(self._rows)} connected")

    # ---------- shutdown ----------
    def destroy(self):
        self._stop()
        super().destroy()

if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    finally:
        # ensure latch GPIO is not left configured
        try:
            GPIO.cleanup()  # harmless if unused here
        except Exception:
            pass
