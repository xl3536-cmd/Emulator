#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Author:Xiaxin Liu
Date: 2025-10-03

Output layout per row:
[ Timestamp? ] [ T1 ] [ T2 ] ... [ TN ] [ combine bits ]

- Under each T* column, we place the 5-bit code (e.g., 10101), NOT the temperature.
- 'combine bits' is a single Excel-safe string of all 8-bit bytes concatenated,
  obeying --reverse-byte-order; bits are optionally inverted via --invert-bits.

Boards count is forced to the number of detected T* columns to keep columns aligned.
"""

import argparse
import csv
import math
import os
import re
from typing import Dict, List, Tuple, Optional

import pandas as pd


# ---------- Core linear mapping ----------
def print_linear_maps(r_min: float, t_min: float, r_max: float, t_max: float) -> None:
    """Print both R→T and T→R linear maps based on anchor points."""
    # T = a0 + a1 * R
    a1 = (t_max - t_min) / (r_max - r_min)
    a0 = t_min - a1 * r_min
    # R = r_min + (T - t_min) * b1
    b1 = (r_max - r_min) / (t_max - t_min)
    print("Linear map (using anchors):")
    print(f"  Anchors:  R_min={r_min:.6f} Ω @ T_min={t_min:.6f} °C,  "
          f"R_max={r_max:.6f} Ω @ T_max={t_max:.6f} °C")
    print("  R→T:  T = a0 + a1·R")
    print(f"        a0 = {a0:.12f}  (°C),  a1 = {a1:.12f}  (°C/Ω)")
    print("  T→R:  R = R_min + (T - T_min)·b1")
    print(f"        b1 = {b1:.12f}  (Ω/°C)")
    print()
def resistance_from_temp(T: float, r_min: float, t_min: float, r_max: float, t_max: float) -> float:
    """Inverse of T = a0 + a1*R using anchors (linear interpolation)."""
    if t_max == t_min:
        return float('nan')
    R = r_min + (T - t_min) * (r_max - r_min) / (t_max - t_min)
    lo, hi = min(r_min, r_max), max(r_min, r_max)
    return max(lo, min(hi, R))


# ---------- Scan CSV helpers ----------
def find_code_columns(cols: List[str]) -> List[str]:
    """Find columns whose names are exactly 5-bit binary strings (e.g., '00000')."""
    out = []
    for c in cols:
        s = str(c).strip().replace('"', '').replace("='", "").replace("'", "")
        if len(s) == 5 and all(ch in '01' for ch in s):
            out.append(s)
    out.sort(key=lambda x: int(x, 2))
    return out

def load_scan(scan_csv: str) -> Dict[int, Dict[int, float]]:
    """Return mapping[board_index][5bit_code] -> resistance_ohms from scan CSV."""
    df = pd.read_csv(scan_csv)
    code_cols = find_code_columns(list(df.columns))
    if not code_cols:
        raise SystemExit("No 5-bit code columns found in scan CSV.")
    board_col = next((c for c in df.columns if str(c).lower().strip() == "board"), None)
    if board_col is None:
        df.insert(0, "board", [i + 1 for i in range(len(df))])
        board_col = "board"

    mapping: Dict[int, Dict[int, float]] = {}
    for _, row in df.iterrows():
        b = int(row[board_col])
        mapping[b] = {}
        for c in code_cols:
            try:
                mapping[b][int(c, 2)] = float(row[c])
            except Exception:
                pass
    return mapping

def clean_lookup(code_to_R: Dict[int, float]) -> List[Tuple[int, float]]:
    """Return [(code, R)] sorted by R desc; drop NaNs and exact-duplicate R."""
    items = [(code, R) for code, R in code_to_R.items()
             if not (isinstance(R, float) and math.isnan(R))]
    items.sort(key=lambda x: (-x[1], x[0]))
    seen = set()
    cleaned = []
    for code, R in items:
        key = round(R, 3)  # ~1 mΩ bucket to drop near-duplicates
        if key in seen:
            continue
        seen.add(key)
        cleaned.append((code, R))
    return cleaned


# ---------- Selection & packing ----------
def choose_code_for_target_R(cleaned: List[Tuple[int, float]], target_R: float) -> int:
    if not cleaned:
        return 0
    best = 0
    best_err = float('inf')
    for code, R in cleaned:
        e = abs(R - target_R)
        if e < best_err:
            best = code
            best_err = e
    return best

def pack_5bit_to_byte(code5: int, invert_bits: bool = False) -> int:
    code5 &= 0x1F
    if invert_bits:
        code5 ^= 0x1F
    return code5  # upper 3 bits are 0

def build_bitstring(bytes_list: List[int], reverse_byte_order: bool = False) -> str:
    bs = list(reversed(bytes_list)) if reverse_byte_order else bytes_list
    return ''.join(f'{b:08b}' for b in bs)


# ---------- Temps helpers ----------
_TCOL_RE = re.compile(r'^\s*T(\d+)\s*$', flags=re.IGNORECASE)

def detect_timestamp_column(df: pd.DataFrame) -> Optional[str]:
    """Pick a timestamp-ish column if present; prefer 'Timestamp', else any column containing 'time'."""
    for c in df.columns:
        if str(c).strip().lower() == "timestamp":
            return c
    for c in df.columns:
        if "time" in str(c).strip().lower():
            return c
    return None

def detect_T_columns(df: pd.DataFrame) -> List[str]:
    """Return T-columns sorted by numeric suffix; case-insensitive."""
    tcols = []
    for c in df.columns:
        m = _TCOL_RE.match(str(c))
        if m:
            tcols.append((int(m.group(1)), c))
    tcols.sort(key=lambda x: x[0])
    return [c for _, c in tcols]


# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(
        description="Temps (T1..TN) -> per-T 5-bit codes under T-columns + combined 8-bit bitstring."
    )
    ap.add_argument("--scan", required=True, help="Path to scan CSV (code→Ω per board)")
    ap.add_argument("--temps", required=True, help="Path to temps CSV (Timestamp optional, needs T1..TN)")
    ap.add_argument("--out", required=True, help="Output CSV path")
    ap.add_argument("--invert-bits", action="store_true", help="Invert 5-bit code (active-low)")
    ap.add_argument("--reverse-byte-order", action="store_true", help="Reverse board byte order in 'combine bits'")
    ap.add_argument("--r-min", type=float, default=96.0, help="R at t_min (Ω)")
    ap.add_argument("--t-min", type=float, default=-10.0, help="t_min (°C)")
    ap.add_argument("--r-max", type=float, default=150.0, help="R at t_max (Ω)")
    ap.add_argument("--t-max", type=float, default=100.0, help="t_max (°C)")
    args = ap.parse_args()

    print_linear_maps(args.r_min, args.t_min, args.r_max, args.t_max)

    # Build lookups per board
    board_code_R = load_scan(args.scan)
    cleaned_luts: Dict[int, List[Tuple[int, float]]] = {b: clean_lookup(m) for b, m in board_code_R.items()}

    # Load temps + detect columns
    tdf = pd.read_csv(args.temps)
    timestamp_col = detect_timestamp_column(tdf)
    tcols = detect_T_columns(tdf)
    if not tcols:
        raise SystemExit("No T-columns detected. Expect columns like T1, T2, ... (case-insensitive).")

    boards = len(tcols)  # force alignment to T-columns

    # Prepare header: [Timestamp?] + T1..TN + 'combine bits'
    hdr: List[str] = []
    if timestamp_col:
        hdr.append(str(timestamp_col))
    hdr.extend([str(c) for c in tcols])
    hdr.append("combine bits")

    out_rows: List[List[str]] = []

    for _, row in tdf.iterrows():
        row_out: List[str] = []
        if timestamp_col:
            row_out.append(str(row[timestamp_col]))

        # For each T column, compute 5-bit code and place it under that T column
        codes5: List[int] = []
        bytes8: List[int] = []

        for idx, c in enumerate(tcols, start=1):
            # Read temperature; if NaN/invalid, use midpoint to produce a code
            try:
                Ti = float(row[c])
                if Ti != Ti:  # NaN
                    raise ValueError
            except Exception:
                Ti = (args.t_min + args.t_max) / 2.0

            target_R = resistance_from_temp(Ti, args.r_min, args.t_min, args.r_max, args.t_max)
            lut = cleaned_luts.get(idx, [])
            code5 = choose_code_for_target_R(lut, target_R)
            byte = pack_5bit_to_byte(code5, invert_bits=args.invert_bits)

            # Under T* column: put the 5-bit string
            row_out.append(format(code5, "05b"))

            # For the combined frame: keep the 8-bit byte
            codes5.append(code5)
            bytes8.append(byte)

        # Build and append combined bitstring (Excel-safe)
        bitstring = build_bitstring(bytes8, reverse_byte_order=args.reverse_byte_order)
        row_out.append("'" + bitstring)  # Excel-safe leading apostrophe

        out_rows.append(row_out)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(out_rows)

    print(f"OK. Wrote: {os.path.abspath(args.out)}")
    print("Columns:", ", ".join(hdr))


if __name__ == "__main__":
    main()
