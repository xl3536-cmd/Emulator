"""
Programmable Resistor Control GUI (Python 3.7 compatible)
=========================================================

Control one or more daisy-chained 74HC595 boards (5 control bits per board).
Wiring (Pi 4):
  MOSI (BCM10 / pin 19) -> DS
  SCLK (BCM11 / pin 23) -> SHCP
  LATCH (BCM5 / pin 29) -> STCP/RCLK
  +5V (pin 2 or 4) and GND (pin 6) to the boards.

No RTD readback—this only drives the shift registers.
"""

import spidev
import RPi.GPIO as GPIO
import tkinter as tk
from tkinter import ttk
from typing import List

# -------- Hardware config --------
LATCH_PIN   = 5     # BCM5 -> 74HC595 STCP/RCLK
SPI_BUS     = 0
SPI_DEV     = 0
SPI_MAX_HZ  = 1_000_000
SPI_MODE    = 0
MAX_BOARDS  = 40

# -------- Driver --------
class ChainDriver:
    """
    Manage one or more daisy-chained 74HC595s.
    Each board contributes one byte; only bits 0..4 are used (Q0..Q4).
    Bits 5..7 are forced low.
    """

    def __init__(self, n_boards=1, invert=False, reverse=True):
        # SPI
        self.spi = spidev.SpiDev()
        self.spi.open(SPI_BUS, SPI_DEV)
        self.spi.max_speed_hz = SPI_MAX_HZ
        self.spi.mode = SPI_MODE

        # GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(LATCH_PIN, GPIO.OUT, initial=GPIO.LOW)

        # State
        self.board_bits = []  # type: List[List[int]]
        self.n_boards = 1
        self.invert_bits = bool(invert)
        self.reverse_order = bool(reverse)

        self.configure(n_boards, invert, reverse)

    def close(self):
        try:
            self.spi.close()
        finally:
            GPIO.cleanup(LATCH_PIN)

    def configure(self, n_boards, invert, reverse):
        new_count = max(1, min(int(n_boards), MAX_BOARDS))
        self.invert_bits = bool(invert)
        self.reverse_order = bool(reverse)

        old = self.board_bits[:]
        self.board_bits = []
        for i in range(new_count):
            if i < len(old):
                bits = (old[i] + [0,0,0,0,0])[:5]
            else:
                bits = [0,0,0,0,0]
            self.board_bits.append([1 if b else 0 for b in bits])
        self.n_boards = new_count
        self.push_all()

    def _calc_code(self, bits):  # type: (List[int]) -> int
        code = 0
        for i in range(5):
            if i < len(bits) and bits[i]:
                code |= (1 << i)
        if self.invert_bits:
            code ^= 0x1F
        return code & 0x1F

    def push_all(self):
        frame = [self._calc_code(b) for b in self.board_bits]
        if self.reverse_order:
            frame = list(reversed(frame))
        if frame:
            self.spi.xfer2(frame)
        GPIO.output(LATCH_PIN, 1)
        GPIO.output(LATCH_PIN, 0)

    def set_board_bit(self, board_idx, bit_idx, value):
        if 0 <= board_idx < self.n_boards and 0 <= bit_idx < 5:
            self.board_bits[board_idx][bit_idx] = 1 if value else 0
            self.push_all()

    def set_board_bits(self, board_idx, bits):  # type: (int, List[int]) -> None
        if 0 <= board_idx < self.n_boards:
            packed = [(1 if (i < len(bits) and bits[i]) else 0) for i in range(5)]
            self.board_bits[board_idx] = packed
            self.push_all()

    def get_frame(self):  # type: () -> List[int]
        frame = [self._calc_code(b) for b in self.board_bits]
        if self.reverse_order:
            frame = list(reversed(frame))
        return frame

# -------- GUI --------
DEFAULT_N_BOARDS = 3
DEFAULT_INVERT_BITS = False
DEFAULT_REVERSE_ORDER = True

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Programmable Resistor Control")
        self.minsize(700, 400)
        self.grid_columnconfigure(0, weight=1)

        self.driver = ChainDriver(
            n_boards=DEFAULT_N_BOARDS,
            invert=DEFAULT_INVERT_BITS,
            reverse=DEFAULT_REVERSE_ORDER,
        )

        self.board_bit_vars = []  # type: List[List[tk.IntVar]]

        self._build_top_controls()

        self.board_frame_container = ttk.Frame(self)
        self.board_frame_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.board_frame_container.grid_columnconfigure(0, weight=1)

        self._rebuild_board_controls()

        self.status_label = ttk.Label(self, text="", foreground="blue")
        self.status_label.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="w")
        self._update_status()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_top_controls(self):
        top = ttk.LabelFrame(self, text="Global Settings")
        top.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        top.grid_columnconfigure(4, weight=1)

        ttk.Label(top, text="Number of boards").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.var_boards = tk.IntVar(value=self.driver.n_boards)
        boards_spin = ttk.Spinbox(
            top, from_=1, to=MAX_BOARDS, width=4,
            textvariable=self.var_boards, command=self._apply_top_config,
        )
        boards_spin.grid(row=0, column=1, padx=4, pady=6, sticky="w")

        self.var_invert = tk.BooleanVar(value=self.driver.invert_bits)
        ttk.Checkbutton(top, text="Invert bits",
                        variable=self.var_invert, command=self._apply_top_config)\
            .grid(row=0, column=2, padx=8, pady=6)

        self.var_reverse = tk.BooleanVar(value=self.driver.reverse_order)
        ttk.Checkbutton(top, text="Reverse byte order",
                        variable=self.var_reverse, command=self._apply_top_config)\
            .grid(row=0, column=3, padx=8, pady=6)

    def _rebuild_board_controls(self):
        for child in self.board_frame_container.winfo_children():
            child.destroy()
        self.board_bit_vars = []

        for board_index in range(self.driver.n_boards):
            frame = ttk.LabelFrame(self.board_frame_container, text=f"Board {board_index + 1}")
            frame.grid(row=board_index, column=0, sticky="w", padx=5, pady=5)

            vars_for_board = []  # type: List[tk.IntVar]
            for bit_index in range(5):
                v = tk.IntVar(value=self.driver.board_bits[board_index][bit_index])
                vars_for_board.append(v)
            self.board_bit_vars.append(vars_for_board)

            for ui_idx, label in enumerate(["b4","b3","b2","b1","b0"]):
                bit_idx = 4 - ui_idx
                ttk.Checkbutton(
                    frame, text=label, variable=vars_for_board[bit_idx],
                    command=lambda b=board_index, bi=bit_idx: self._on_board_bit_toggle(b, bi)
                ).grid(row=0, column=ui_idx, padx=4, pady=4)

            quick = ttk.Frame(frame)
            quick.grid(row=1, column=0, columnspan=5, pady=(2, 4))
            ttk.Button(quick, text="All 0", width=6,
                       command=lambda b=board_index: self._set_board_bits(b, [0,0,0,0,0]))\
                .grid(row=0, column=0, padx=2)
            ttk.Button(quick, text="All 1", width=6,
                       command=lambda b=board_index: self._set_board_bits(b, [1,1,1,1,1]))\
                .grid(row=0, column=1, padx=2)

    def _on_board_bit_toggle(self, board_index, bit_index):
        val = self.board_bit_vars[board_index][bit_index].get()
        self.driver.set_board_bit(board_index, bit_index, val)
        self._update_status()

    def _set_board_bits(self, board_index, bits):
        for i in range(5):
            self.board_bit_vars[board_index][i].set(1 if (i < len(bits) and bits[i]) else 0)
        self.driver.set_board_bits(board_index, bits)
        self._update_status()

    def _apply_top_config(self):
        self.driver.configure(self.var_boards.get(), self.var_invert.get(), self.var_reverse.get())
        self._rebuild_board_controls()
        self._update_status()

    def _update_status(self):
        frame = self.driver.get_frame()
        self.status_label.config(text="Frame bytes: " + " ".join(f"0x{b:02X}" for b in frame))

    def _on_close(self):
        self.driver.close()
        self.destroy()

if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    finally:
        GPIO.cleanup(LATCH_PIN)
