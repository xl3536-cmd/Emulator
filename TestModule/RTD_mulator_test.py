# Date: 2025-09-25
# Author: Xiaxin Liu
# rtd_emulator_gui_nboards.py
# Multi‑board RTD emulator controller for Raspberry Pi using 74HC595 shift registers.

import spidev, RPi.GPIO as GPIO
import tkinter as tk
from tkinter import ttk

# optional RTD library (pip3 install SMrtd)
try:
    import librtd
    _HAS_LIBRTD = True
except Exception:
    _HAS_LIBRTD = False

# Hardware configuration
LATCH_PIN   = 5   # BCM5 -> STCP/RCLK of the 74HC595
SPI_BUS     = 0
SPI_DEV     = 0
SPI_MAX_HZ  = 1_000_000
SPI_MODE    = 0
MAX_BOARDS  = 40  # maximum boards in chain
# Select which RTD hat (0..7) and channel (1..8) to read
STACK = 0     # your Sequent RTD board’s stack address
CHANNEL = 1   # channel number on that board

class ChainDriver:
    """Drives one or more daisy‑chained 74HC595s.  Each board uses only bits Q0…Q4."""

    def __init__(self, n_boards=1, invert=False, reverse=True):
        self.spi = spidev.SpiDev()
        self.spi.open(SPI_BUS, SPI_DEV)
        self.spi.max_speed_hz = SPI_MAX_HZ
        self.spi.mode = SPI_MODE

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(LATCH_PIN, GPIO.OUT, initial=GPIO.LOW)

        # Default state
        self.n_boards    = 1
        self.invert_bits = invert
        self.reverse     = reverse
        self.bits        = [0,0,0,0,0]
        self.configure(n_boards, invert, reverse)

    def configure(self, n_boards, invert, reverse):
        self.n_boards = max(1, min(int(n_boards), MAX_BOARDS))
        self.invert_bits = bool(invert)
        self.reverse = bool(reverse)
        # Re‑push current bits on change
        self.push_bits(self.bits)

    def push_bits(self, bits):
        """Send a 5‑bit pattern to all boards (unused bits cleared)."""
        self.bits = [1 if b else 0 for b in bits[:5]]
        b0,b1,b2,b3,b4 = self.bits
        code = (b0<<0)|(b1<<1)|(b2<<2)|(b3<<3)|(b4<<4)
        if self.invert_bits:
            code ^= 0x1F  # invert only lower five bits
        code &= 0x1F      # clear unused bits 5–7
        frame = [code] * self.n_boards
        if self.reverse:
            frame.reverse()
        self.spi.xfer2(frame)
        GPIO.output(LATCH_PIN, 1)
        GPIO.output(LATCH_PIN, 0)

    def get_frame(self):
        """Return the current frame (list of bytes)."""
        b0,b1,b2,b3,b4 = self.bits
        code = (b0<<0)|(b1<<1)|(b2<<2)|(b3<<3)|(b4<<4)
        if self.invert_bits: code ^= 0x1F
        code &= 0x1F
        frame = [code] * self.n_boards
        if self.reverse: frame.reverse()
        return frame

    def close(self):
        """Release SPI and GPIO."""
        try: self.spi.close()
        finally: GPIO.cleanup(LATCH_PIN)

# Tkinter UI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RTD(0,1) + Programmable Resistor Control")
        self.minsize(650, 320)
        self.grid_columnconfigure(0, weight=1)

        # driver with default settings (3 boards, no inversion, reversed)
        self.driver = ChainDriver(n_boards=3, invert=False, reverse=True)
        self._build_controls()
        self._build_rtd_display()
        self._poll_rtd()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_controls(self):
        ctrl = ttk.LabelFrame(self, text="Programmable Resistor Settings")
        ctrl.grid(row=0, column=0, sticky="nsew", padx=10, pady=8)

        # number of boards
        ttk.Label(ctrl, text="Number of boards").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.var_boards = tk.IntVar(value=self.driver.n_boards)
        spin = ttk.Spinbox(ctrl, from_=1, to=MAX_BOARDS, width=4,
                            textvariable=self.var_boards, command=self._apply_config)
        spin.grid(row=0, column=1, padx=4, pady=6, sticky="w")

        # invert bits
        self.var_invert = tk.BooleanVar(value=self.driver.invert_bits)
        ttk.Checkbutton(ctrl, text="Invert bits (active‑low)",
                        variable=self.var_invert, command=self._apply_config)\
            .grid(row=0, column=2, padx=8, pady=6)

        # reverse order
        self.var_reverse = tk.BooleanVar(value=self.driver.reverse)
        ttk.Checkbutton(ctrl, text="Reverse byte order",
                        variable=self.var_reverse, command=self._apply_config)\
            .grid(row=0, column=3, padx=8, pady=6)

        # bit toggles b4…b0
        bits_frame = ttk.Frame(ctrl)
        bits_frame.grid(row=1, column=0, columnspan=4, pady=6)
        self.bit_vars = [tk.IntVar(value=0) for _ in range(5)]
        labels = ["b4","b3","b2","b1","b0"]
        for ui_idx,label in enumerate(labels):
            idx = 4 - ui_idx
            ttk.Checkbutton(bits_frame, text=label,
                            variable=self.bit_vars[idx], command=self._apply_bits)\
                .grid(row=0, column=ui_idx, padx=8, pady=4)

        # quick presets
        presets = ttk.Frame(ctrl)
        presets.grid(row=2, column=0, columnspan=4, pady=(4,8))
        ttk.Button(presets, text="All 0 (max Ω)",
                   command=lambda: self._set_bits([0,0,0,0,0])).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(presets, text="All 1 (min Ω)",
                   command=lambda: self._set_bits([1,1,1,1,1])).grid(row=0, column=1, padx=4, pady=4)
        ttk.Button(presets, text="Increment", command=self._increment_code)\
            .grid(row=0, column=2, padx=4, pady=4)
        ttk.Button(presets, text="Decrement", command=self._decrement_code)\
            .grid(row=0, column=3, padx=4, pady=4)

        # status line
        self.lbl_status = ttk.Label(ctrl, text="", foreground="blue")
        self.lbl_status.grid(row=3, column=0, columnspan=4, padx=8, pady=(4,8), sticky="w")
        self._update_status()

    def _build_rtd_display(self):
        box = ttk.LabelFrame(self, text="RTD Readback (stack 0, channel 1)")
        box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10))
        self.lbl_rtd = ttk.Label(box, text="Temp: … °C   |   Res: … Ω")
        self.lbl_rtd.grid(row=0, column=0, padx=8, pady=8, sticky="w")

    def _apply_config(self):
        self.driver.configure(self.var_boards.get(),
                              self.var_invert.get(),
                              self.var_reverse.get())
        self.driver.push_bits([v.get() for v in self.bit_vars])
        self._update_status()

    def _set_bits(self, arr):
        for i,b in enumerate(arr):
            self.bit_vars[i].set(1 if b else 0)
        self._apply_bits()

    def _apply_bits(self):
        bits = [self.bit_vars[i].get() for i in range(5)]
        self.driver.push_bits(bits)
        self._update_status()

    def _current_code(self):
        b = [v.get() for v in self.bit_vars]
        return (b[4]<<4)|(b[3]<<3)|(b[2]<<2)|(b[1]<<1)|(b[0]<<0)

    def _increment_code(self):
        c = (self._current_code() + 1) & 0x1F
        self._set_bits([(c>>0)&1, (c>>1)&1, (c>>2)&1, (c>>3)&1, (c>>4)&1])

    def _decrement_code(self):
        c = (self._current_code() - 1) & 0x1F
        self._set_bits([(c>>0)&1, (c>>1)&1, (c>>2)&1, (c>>3)&1, (c>>4)&1])

    def _update_status(self):
        code = self._current_code()
        frame = self.driver.get_frame()
        frame_str = " ".join(f"0x{b:02X}" for b in frame)
        self.lbl_status.config(text=
            f"5‑bit code: 0b{code:05b} (0x{code:02X})   |   Frame bytes: {frame_str}")

    def _poll_rtd(self):
        if _HAS_LIBRTD:
            try:
                temp = float(librtd.get_poly5(STACK, CHANNEL))
                res  = float(librtd.getRes(STACK, CHANNEL))
                self.lbl_rtd.config(
                    text=f"Temp: {temp:.2f} °C   |   Res: {res:.2f} Ω")
            except Exception as e:
                self.lbl_rtd.config(text=f"RTD read error: {e}")
        else:
            self.lbl_rtd.config(text="librtd module not found – install SMrtd")
        self.after(1000, self._poll_rtd)

    def _on_close(self):
        self.driver.close()
        self.destroy()

if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    finally:
        GPIO.cleanup(LATCH_PIN)
