#!/usr/bin/env python3
# scan_595_broadcast_fast.py
#
# Broadcast mode: set the same 8-bit code on ALL boards at once (one SPI frame),
# wait briefly, then read all mapped RTD channels and log to CSV (saved next to this script).
# Packages we need to install: 
# pip install RPi.GPIO spidev SMrtd

# Use this code for the 8bit V2 RTD emulator PCBs, use GetBoardResAllBits.py for the V0 and V1 RTD emulator PCBs

import time
import csv
import os
from typing import List

import spidev
import RPi.GPIO as GPIO

try:
    import librtd  # from SMrtd
except Exception as e:
    raise SystemExit("Missing 'librtd' (sudo pip3 install SMrtd) :: " + str(e))

# ------------------- SAVE NEXT TO THIS SCRIPT -------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "rtd_board_code_scan_broadcast.csv")
# ---------------------------------------------------------------

# ------------------- CONFIG -------------------
BOARD_COUNT        = 44                 # number of 74HC595-driven boards
BIT_WIDTH          = 8                  # 8-bit codes (0..255)
INVERT_BITS        = False              # True if the ladder is active-low
REVERSE_BYTE_ORDER = True               # Flip if your daisy-chain direction is opposite

# SPI/GPIO
SPI_BUS            = 0
SPI_DEV            = 0
SPI_MAX_HZ         = 1_000_000
SPI_MODE           = 0
LATCH_PIN_BCM      = 5                  # BCM5 -> STCP/RCLK

# RTD HAT reading
# Map boards 1..44 to their respective stack and channel
# Boards 1-8 -> Stack 0, channels 1-8
# Boards 9-16 -> Stack 1, channels 1-8
# Boards 17-24 -> Stack 2, channels 1-8
# Boards 25-32 -> Stack 3, channels 1-8
# Boards 33-40 -> Stack 4, channels 1-8
# Boards 41-44 -> Stack 5, channels 1-4
BOARD_TO_STACK_CHANNEL = []
for board_num in range(1, BOARD_COUNT + 1):
    stack = (board_num - 1) // 8
    channel = ((board_num - 1) % 8) + 1
    BOARD_TO_STACK_CHANNEL.append((stack, channel))

# Timing (tuned for speed; increase if your loop needs more time)
SETTLE_SECONDS     = 0.8                # wait after each code change
N_SAMPLES          = 1                  # set >1 if you want averaging
SAMPLE_INTERVAL_S  = 0.0

# Excel-safe header text (keeps leading zeros visually if you open in Excel)
EXCEL_SAFE_HEADERS = False              # set True to use headers like ="00000000"
# ---------------------------------------------

# Exact 8-bit, zero-padded codes: '00000000'...'11111111'
BIN_CODES = [format(i, f"0{BIT_WIDTH}b") for i in range(2 ** BIT_WIDTH)]

def code_header_list() -> List[str]:
    """Return column headers preserving leading zeros. Optionally Excel-safe."""
    if EXCEL_SAFE_HEADERS:
        # Excel interprets ="00000000" as text with visible leading zeros
        return [f'="{c}"' for c in BIN_CODES]
    return BIN_CODES[:]

def setup_spi_and_gpio():
    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEV)
    spi.max_speed_hz = SPI_MAX_HZ
    spi.mode = SPI_MODE
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LATCH_PIN_BCM, GPIO.OUT, initial=GPIO.LOW)
    return spi

def cleanup(spi):
    try: spi.close()
    except Exception: pass
    try: GPIO.cleanup(LATCH_PIN_BCM)
    except Exception: pass

def _pack_code(v: int) -> int:
    mask = (2 ** BIT_WIDTH) - 1
    v &= mask
    if INVERT_BITS:
        v ^= mask
    return v

def push_frame(spi, per_board_codes: List[int]):
    frame = [_pack_code(c) for c in per_board_codes]
    if REVERSE_BYTE_ORDER:
        frame = list(reversed(frame))
    if frame:
        spi.xfer2(frame)
    GPIO.output(LATCH_PIN_BCM, 1)
    GPIO.output(LATCH_PIN_BCM, 0)

def set_all_boards(spi, code_val: int):
    mask = (2 ** BIT_WIDTH) - 1
    codes = [(code_val & mask)] * BOARD_COUNT
    push_frame(spi, codes)

def read_resistance(stack: int, ch: int) -> float:
    return float(librtd.getRes(stack, ch))

def measure_avg_resistance(stack: int, ch: int) -> float:
    if N_SAMPLES <= 1:
        return read_resistance(stack, ch)
    acc = 0.0
    for i in range(N_SAMPLES):
        acc += read_resistance(stack, ch)
        if i + 1 < N_SAMPLES and SAMPLE_INTERVAL_S > 0:
            time.sleep(SAMPLE_INTERVAL_S)
    return acc / N_SAMPLES

def quick_channel_selftest():
    """Read each mapped channel once to catch invalid channels early."""
    ok = True
    for idx, (stack, ch) in enumerate(BOARD_TO_STACK_CHANNEL):
        try:
            _ = read_resistance(stack, ch)
        except Exception as e:
            print(f"[WARN] Board {idx+1} → stack {stack} channel {ch}: read failed ({e}); "
                  f"this will appear as 'nan' in CSV.")
            ok = False
    return ok

def main():
    if len(BOARD_TO_STACK_CHANNEL) != BOARD_COUNT:
        raise SystemExit(f"BOARD_TO_STACK_CHANNEL length ({len(BOARD_TO_STACK_CHANNEL)}) "
                         f"must equal BOARD_COUNT ({BOARD_COUNT}).")

    spi = setup_spi_and_gpio()
    try:
        # Initialize all boards to 00000000 (or appropriate zero value)
        push_frame(spi, [0] * BOARD_COUNT)

        # Sanity-check channels to avoid all-NaN surprises
        quick_channel_selftest()

        # Prepare rows: one row per board
        headers = ["board"] + code_header_list()
        rows = [{"board": i + 1} for i in range(BOARD_COUNT)]

        total_codes = 2 ** BIT_WIDTH
        for code_int in range(total_codes):
            # Broadcast same code to every board
            set_all_boards(spi, code_int)

            # Allow settle
            if SETTLE_SECONDS > 0:
                time.sleep(SETTLE_SECONDS)

            # Read all mapped channels
            avgs = []
            for b_idx in range(BOARD_COUNT):
                stack, ch = BOARD_TO_STACK_CHANNEL[b_idx]
                try:
                    r = measure_avg_resistance(stack, ch)
                except Exception:
                    r = float("nan")
                avgs.append(r)

            # Write this code's readings into each board's row
            code_str = format(code_int, f"0{BIT_WIDTH}b")
            # If Excel-safe headers, we must write to the exact header text used
            header_key = f'="{code_str}"' if EXCEL_SAFE_HEADERS else code_str
            for b_idx, r_ohm in enumerate(avgs):
                rows[b_idx][header_key] = f"{r_ohm:.6f}"

            # Progress indicator
            if (code_int + 1) % 64 == 0:
                print(f"Progress: {code_int + 1}/{total_codes} codes processed...")

        # Write CSV next to this script
        with open(OUTPUT_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

        print(f"Done. Wrote: {os.path.abspath(OUTPUT_CSV)}")
        print(f"Total codes: {total_codes} (8-bit range)")
        print(f"Total boards: {BOARD_COUNT}")
        print("Columns: board, " + ", ".join(headers[1:]))

    finally:
        # Return outputs to 00000000 and clean up
        try: push_frame(spi, [0] * BOARD_COUNT)
        except Exception: pass
        cleanup(spi)

if __name__ == "__main__":
    main()
