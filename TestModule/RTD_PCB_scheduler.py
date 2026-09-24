#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
play_595_from_csv.py — program the 74HC595 chain row-by-row (no GUI)

Now compatible with mapper output shaped like:
[ Timestamp? ] [ T1 ] [ T2 ] ... [ TN ] [ combine bits ]
- Under each T* is a 5-bit code string.
- 'combine bits' is the concatenated 8-bit bytes (Excel-safe, may start with a ').

Column priority (first match wins):
  0) combine bits                -> big bitstring of all boards (8*N bits)
  1) bits_b1..bits_bN            -> 8-bit strings like "00011110"
  2) byte_b1..byte_bN            -> integers 0..255
  3) T1..TN                      -> 5-bit strings "00000".."11111" (packed into byte)
  4) code_b1..code_bN            -> 5-bit strings "00000".."11111" (packed into byte)
  5) bitstring_40_text/bitstring_40/bitstring -> big bitstring for all boards

Usage examples:
  python play_595_from_csv.py --csv "/path/to/mapped_output.csv"
  python play_595_from_csv.py --csv "/path/to/mapped_output.csv" --interval 1 --loops 1 --reverse-byte-order
  python play_595_from_csv.py --csv "/path/to/mapped_output.csv" --boards 5

Wiring (Raspberry Pi):
  MOSI (BCM10 / pin 19) -> 74HC595 DS
  SCLK (BCM11 / pin 23) -> 74HC595 SHCP
  LATCH (BCM5  / pin 29) -> 74HC595 STCP/RCLK
"""

import argparse
import csv
import re
import time
from typing import List, Optional

import spidev
import RPi.GPIO as GPIO


# ----------------------- helpers -----------------------

_TCOL_RE = re.compile(r'^\s*T(\d+)\s*$', flags=re.IGNORECASE)

def _parse_bits8(s: str) -> int:
    s = str(s).strip().lstrip("'").replace(" ", "")
    s = ''.join(ch for ch in s if ch in '01')
    if not s:
        return 0
    s = s[-8:].rjust(8, "0")  # keep only last 8 bits if longer; left-pad if shorter
    return int(s, 2) & 0xFF

def _parse_bitstring_to_bytes(s: str) -> List[int]:
    """Parse a long '0/1' string (may be Excel-safe `'...`) into a list of bytes."""
    s = str(s).strip().lstrip("'").replace(" ", "")
    s = ''.join(ch for ch in s if ch in '01')
    if not s:
        return []
    # left-pad to multiple of 8
    pad = (-len(s)) % 8
    if pad:
        s = ('0' * pad) + s
    n = len(s) // 8
    return [int(s[i*8:(i+1)*8], 2) & 0xFF for i in range(n)]

def pack_5bit_to_byte(code5: int, invert_bits: bool=False) -> int:
    b = code5 & 0x1F
    if invert_bits:
        b ^= 0x1F
    return b  # Q0..Q4 used, Q5..Q7 = 0

def detect_timestamp_column(fieldnames: List[str]) -> Optional[str]:
    for name in fieldnames:
        if str(name).strip().lower() == "timestamp":
            return name
    for name in fieldnames:
        if "time" in str(name).strip().lower():
            return name
    return None

def detect_t_columns(fieldnames: List[str]) -> List[str]:
    tcols = []
    for c in fieldnames:
        m = _TCOL_RE.match(str(c))
        if m:
            tcols.append((int(m.group(1)), c))
    tcols.sort(key=lambda x: x[0])
    return [c for _, c in tcols]

def detect_board_count(fieldnames: List[str], fallback: int) -> int:
    """Infer N from bits_b*, byte_b*, code_b*, or T*; else use fallback."""
    def max_suffix(prefix: str) -> int:
        m = 0
        for name in fieldnames:
            s = str(name)
            if s.startswith(prefix):
                try:
                    idx = int(s[len(prefix):])
                    if idx > m:
                        m = idx
                except Exception:
                    pass
        return m

    n = max(
        max_suffix("bits_b"),
        max_suffix("byte_b"),
        max_suffix("code_b"),
    )
    tcols = detect_t_columns(fieldnames)
    if tcols:
        n = max(n, len(tcols))
    return n if n > 0 else fallback

def row_to_bytes(row: dict, fieldnames: List[str], boards_hint: int, invert_bits: bool) -> List[int]:
    """Build the per-board byte list from a CSV row using the column priority."""
    # 0) combine bits
    for key in ("combine bits", "combine_bits", "combinebits"):
        if key in row and str(row[key]).strip() != "":
            bs = _parse_bitstring_to_bytes(row[key])
            return bs if bs else [0] * max(1, boards_hint)

    # 1) bits_b1..bits_bN
    boards = detect_board_count(fieldnames, boards_hint)
    if boards <= 0:
        boards = boards_hint if boards_hint > 0 else 1

    have_bits = all((f"bits_b{i}" in row and str(row[f"bits_b{i}"]).strip() != "") for i in range(1, boards+1))
    if have_bits:
        return [_parse_bits8(row[f"bits_b{i}"]) for i in range(1, boards+1)]

    # 2) byte_b1..byte_bN
    have_bytes = all((f"byte_b{i}" in row and str(row[f"byte_b{i}"]).strip() != "") for i in range(1, boards+1))
    if have_bytes:
        out = []
        for i in range(1, boards+1):
            try:
                val = int(float(row[f"byte_b{i}"]))
            except Exception:
                val = 0
            out.append(val & 0xFF)
        return out

    # 3) T1..TN (5-bit strings under T* columns)
    tcols = detect_t_columns(fieldnames)
    if tcols:
        out = []
        for c in tcols:
            s = str(row.get(c, "")).strip().strip("'").replace('"', '')
            try:
                code = int(s, 2) & 0x1F
            except Exception:
                code = 0
            out.append(pack_5bit_to_byte(code, invert_bits=invert_bits))
        return out

    # 4) code_b1..code_bN (5-bit strings)
    have_codes = all((f"code_b{i}" in row and str(row[f"code_b{i}"]).strip() != "") for i in range(1, boards+1))
    if have_codes:
        out = []
        for i in range(1, boards+1):
            s = str(row[f"code_b{i}"]).strip().strip("'").replace('"', '')
            try:
                code = int(s, 2) & 0x1F
            except Exception:
                code = 0
            out.append(pack_5bit_to_byte(code, invert_bits=invert_bits))
        return out

    # 5) big bitstring variants
    for key in ("bitstring_40_text", "bitstring_40", "bitstring"):
        if key in row and str(row[key]).strip() != "":
            bs = _parse_bitstring_to_bytes(row[key])
            # if empty, fall back to zeros for known boards
            return bs if bs else [0] * max(1, boards)

    # fallback
    return [0] * max(1, boards)

def push_frame(spi, latch_pin_bcm: int, bytes_per_board: List[int], reverse_byte_order: bool):
    frame = list(bytes_per_board)
    if reverse_byte_order:
        frame.reverse()
    if frame:
        spi.xfer2(frame)
    GPIO.output(latch_pin_bcm, 1)
    GPIO.output(latch_pin_bcm, 0)


# ----------------------- main -----------------------

def main():
    ap = argparse.ArgumentParser(description="Program 74HC595 chain from CSV, one row per interval.")
    ap.add_argument("--csv", required=True, help="Input CSV path (mapped_output.csv)")
    ap.add_argument("--boards", type=int, default=5, help="Number of boards (auto-detected when possible)")
    ap.add_argument("--interval", type=float, default=1.0, help="Seconds between rows (default 1.0)")
    ap.add_argument("--loops", type=int, default=1, help="Times to loop through the CSV (default 1)")
    ap.add_argument("--invert-bits", action="store_true", help="Invert 5-bit code (applies to T*/code_b* paths)")
    ap.add_argument("--reverse-byte-order", action="store_true", help="Reverse bytes for SPI chain")
    ap.add_argument("--spi-bus", type=int, default=0, help="SPI bus (default 0)")
    ap.add_argument("--spi-dev", type=int, default=0, help="SPI device (default 0)")
    ap.add_argument("--spi-hz", type=int, default=1_000_000, help="SPI clock Hz (default 1MHz)")
    ap.add_argument("--spi-mode", type=int, default=0, help="SPI mode 0..3 (default 0)")
    ap.add_argument("--latch-pin", type=int, default=5, help="BCM pin for STCP/RCLK (default 5)")
    args = ap.parse_args()

    # Prepare SPI/GPIO
    spi = spidev.SpiDev()
    spi.open(args.spi_bus, args.spi_dev)
    spi.max_speed_hz = args.spi_hz
    spi.mode = args.spi_mode

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(args.latch_pin, GPIO.OUT, initial=GPIO.LOW)

    last_frame_len = args.boards  # for safe clear on exit

    try:
        with open(args.csv, "r", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames or []

            # auto-detect board count from header (used for non-dynamic paths)
            boards = detect_board_count(fieldnames, args.boards)

            # timestamp column (for logs only)
            ts_col = detect_timestamp_column(fieldnames)

        for loop in range(max(1, args.loops)):
            for idx, row in enumerate(rows):
                bytes_row = row_to_bytes(row, fieldnames, boards_hint=boards, invert_bits=args.invert_bits)
                last_frame_len = len(bytes_row) if bytes_row else last_frame_len
                push_frame(spi, args.latch_pin, bytes_row, reverse_byte_order=args.reverse_byte_order)

                ts = row.get(ts_col, f"row{idx+1}") if ts_col else f"row{idx+1}"
                print(f"[{loop+1}] {ts} -> {bytes_row}")
                time.sleep(max(0.0, args.interval))

    finally:
        # set all outputs to zero and cleanup
        try:
            push_frame(spi, args.latch_pin, [0] * max(1, last_frame_len), reverse_byte_order=args.reverse_byte_order)
        except Exception:
            pass
        try:
            spi.close()
        except Exception:
            pass
        try:
            GPIO.cleanup(args.latch_pin)
        except Exception:
            pass


if __name__ == "__main__":
    main()
