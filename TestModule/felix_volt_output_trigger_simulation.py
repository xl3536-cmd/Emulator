#!/usr/bin/env python3
"""
Sequent Microsystems 16‑Channel 0‑10 V Output HAT ─ GUI Controller
==============================================================
This script gives you a **simple Tkinter GUI** where you can dial‑in any
voltage between **0 V and 10 V** on each of the 16 analog‑output channels of
the Sequent Microsystems Industrial I/O HAT that you have stacked on your
Raspberry Pi.

───────────────────────────────
Prerequisites
───────────────────────────────
1. **Hardware power** – The HAT needs an external supply (labelled
   `24 VAC / 12‑35 V DC`). Without that supply the DAC cannot source any
   voltage.

2. **Python deps**
   ```bash
   # 1) Tkinter for the GUI (system package, not installed via pip!)
   sudo apt-get update && sudo apt-get install -y python3-tk

   # 2) Vendor driver. Either:
   #    a) If Sequent publishes it to PyPI (check):
   pip install megaind
   #    b) Or from source:
   git clone https://github.com/SequentMicrosystems/megaind.git
   cd megaind/utils && sudo make install  # installs the Python module system‑wide
   ```

3. **Run**
   ```bash
   python3 felix_volt_output_trigger_simulation.py
   ```

───────────────────────────────
Usage notes
───────────────────────────────
* The board stack level is **0** by default (first HAT on the 40‑pin header).
  If you stack multiple Sequent boards, change `STACK_LEVEL` accordingly
  (0‑7).
* Move a slider or type a value (0‑10) then press **↵** to update that
  channel immediately.
* All voltages are sent in **millivolts** to the driver: 0‑10 V ⇒ 0‑10000 mV.
* A helper readback function is included but commented out – uncomment if you
  want to poll the board for the actual output (handy when several apps might
  change the outputs).
"""

import tkinter as tk
from tkinter import ttk, StringVar
from functools import partial

try:
    import megaind  # Official Sequent Microsystems Python module
except ImportError:
    raise SystemExit("\n[ERROR] 'megaind' module not found. Install the vendor driver first.\n")

# ── User‑tweakable constants ────────────────────────────────────────────────
STACK_LEVEL = 0          # 0‑7, 0 = first (bottom) board on the Pi
CH_COUNT    = 16         # The 0‑10 V HAT has 16 outputs
MAX_VOLT    = 10.0       # DAC full‑scale
SLIDER_RES  = 0.01       # Slider step in volts
SLIDER_LEN  = 230        # Pixel length of slider widget

# ── Helper functions ────────────────────────────────────────────────────────

def send_voltage(chan: int, volt_f: float) -> None:
    """Convert volts→millivolts and send to the board."""
    mv = int(round(max(0.0, min(MAX_VOLT, volt_f)) * 1000))
    megaind.set0_10Out(STACK_LEVEL, chan, mv)


def on_slider_move(chan: int, sv: StringVar, val: str) -> None:
    """Called when user drags a slider."""
    sv.set(f"{float(val):.2f}")       # update entry box text
    send_voltage(chan, float(val))


def on_entry_commit(event, chan: int, scale: tk.Scale, sv: StringVar):
    """Called when user hits <Return> in the entry box."""
    try:
        v = float(sv.get())
    except ValueError:
        return  # ignore invalid input

    v = max(0.0, min(MAX_VOLT, v))    # clamp
    scale.set(v)                      # will trigger on_slider_move

# ── OPTIONAL: readback (uncomment if you need it) ───────────────────────────
# def refresh_readback():
#     """Poll the board and update GUI – call every N ms."""
#     for ch in range(CH_COUNT):
#         mv = megaind.get0_10Out(STACK_LEVEL, ch)  # or get0_10In(...)
#         v  = mv / 1000.0
#         vars_[ch].set(f"{v:.2f}")
#         scales[ch].set(v)
#     root.after(1000, refresh_readback)  # 1 s cadence

# ── Build GUI ───────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("0‑10 V Output HAT Controller")
root.resizable(False, False)

main = ttk.Frame(root, padding=10)
main.grid(row=0, column=0, sticky="nsew")

vars_   = []   # StringVar for each entry box
scales  = []   # Reference to Scale widgets (if we need to programmatically set)

header = ttk.Label(main, text="Channel", font=("Segoe UI", 10, "bold"))
header.grid(row=0, column=0, padx=4, pady=4)
header = ttk.Label(main, text="Voltage [V] (type↵ or drag)", font=("Segoe UI", 10, "bold"))
header.grid(row=0, column=1, padx=4, pady=4, columnspan=2)

for ch in range(CH_COUNT):
    ttk.Label(main, text=f"OUT{ch:02d}").grid(row=ch+1, column=0, sticky="e", padx=(0,6))

    sv = StringVar(value="0.00")
    vars_.append(sv)

    scale = tk.Scale(
        main, from_=0, to=MAX_VOLT, resolution=SLIDER_RES, orient="horizontal",
        length=SLIDER_LEN,
        command=partial(on_slider_move, ch, sv)
    )
    scale.grid(row=ch+1, column=1, sticky="w")
    scales.append(scale)

    entry = ttk.Entry(main, textvariable=sv, width=6)
    entry.grid(row=ch+1, column=2, padx=(6,0))
    entry.bind("<Return>", partial(on_entry_commit, chan=ch, scale=scale, sv=sv))

# ── Kick‑off optional readback loop ─────────────────────────────────────────
# refresh_readback()  # uncomment if you enabled the function above

root.mainloop()
