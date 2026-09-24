#!/usr/bin/env python3
"""
Author: Xiaxin Liu
Date: Dec-03-2025

rtd_tcp_logger_piB.py

Pi B:
- Listens on TCP port for Pi A.
- Receives plain text lines:
    "CODE 00000"
    "CODE 00001"
    ...
    "DONE"
- For each CODE line, immediately reads all RTD channels using librtd,
  and logs the resistance under that code column.
- On DONE (or connection close), writes CSV in the same shape as:
    board_id, stack, channel, 00000, 00001, ..., 11111
"""

import socket
import time
import csv
import os
from typing import Dict, List, Tuple

try:
    import librtd  # from SMrtd
except Exception as e:
    print("ERROR: Could not import librtd (SMrtd). Install with 'sudo pip3 install SMrtd'.")
    print("Import error:", e)
    raise SystemExit(1)

# ----------------- CONFIG -----------------

LISTEN_HOST = "0.0.0.0"   # listen on all interfaces
LISTEN_PORT = 5000

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "rtd_code_scan_from_tcp_24pcs.csv")

BOARD_COUNT = 24
STACKS = [0, 1, 2]                # same mapping as in your original code
SCAN_CHANNELS = list(range(1, 8 + 1))  # channels 1..8

# ----------------- MAPPING -----------------

def build_board_map(board_count: int) -> List[Tuple[int, int]]:
    """
    Reproduce the mapping from board index -> (stack, channel) just like your script:
    board 0 -> stack 0, ch 1
    board 1 -> stack 0, ch 2
    ...
    board 7 -> stack 0, ch 8
    board 8 -> stack 1, ch 1
    ...
    board 23 -> stack 2, ch 8
    """
    mapping = []
    per_stack = len(SCAN_CHANNELS)
    for b in range(board_count):
        stack = b // per_stack
        chan = SCAN_CHANNELS[b % per_stack]
        mapping.append((stack, chan))
    return mapping


def read_resistance(stack: int, ch: int) -> float:
    try:
        return float(librtd.getRes(stack, ch))
    except Exception:
        return float("nan")


# ----------------- SERVER LOGIC -----------------

def handle_client(conn: socket.socket, addr):
    print(f"Client connected from {addr}")
    board_map = build_board_map(BOARD_COUNT)

    # Initialize rows: one row per board with static info
    rows: Dict[int, Dict[str, str]] = {}
    for b, (st, ch) in enumerate(board_map):
        rows[b] = {"board_id": b + 1, "stack": st, "channel": ch}

    # Track which codes we saw (in order of arrival)
    codes_seen: List[str] = []

    # Wrap socket with file-like object for easy line reading
    f = conn.makefile("r", encoding="ascii", newline="\n")

    try:
        for line in f:
            line = line.strip()
            if not line:
                continue

            upper = line.upper()
            if upper.startswith("CODE"):
                parts = line.split()
                if len(parts) < 2:
                    print(f"Malformed CODE line: {line}")
                    continue
                code_bits = parts[1].strip().strip("'").strip('"')

                # Validate a 5-bit string
                if len(code_bits) != 5 or any(c not in "01" for c in code_bits):
                    print(f"Ignoring non-5bit code '{code_bits}' from line: {line}")
                    continue

                if code_bits not in codes_seen:
                    codes_seen.append(code_bits)

                # Sample all boards for this code
                print(f"Logging RTDs for CODE {code_bits} ...")
                for b, (st, ch) in enumerate(board_map):
                    val = read_resistance(st, ch)
                    rows[b][code_bits] = f"{val:.6f}"

            elif upper.startswith("DONE"):
                print("Received DONE; finishing logging.")
                break
            else:
                print(f"Ignoring unknown line from client: {line}")

    except Exception as e:
        print("ERROR while reading from client:", e)
    finally:
        try:
            f.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    # After DONE or connection close, write CSV if we saw any codes
    if codes_seen:
        write_csv(rows, codes_seen)
    else:
        print("No CODE lines were received; nothing to write.")


def write_csv(rows: Dict[int, Dict[str, str]], codes_seen: List[str]):
    # Build headers: static then code columns in the order we saw them
    fieldnames = ["board_id", "stack", "channel"] + codes_seen

    out_path = OUTPUT_CSV
    try:
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for b in sorted(rows.keys()):
                w.writerow(rows[b])
        print(f"Wrote RTD log CSV: {out_path}")
    except Exception as e:
        print("ERROR writing CSV:", e)


def main():
    print(f"Pi B: listening on {LISTEN_HOST}:{LISTEN_PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((LISTEN_HOST, LISTEN_PORT))
        s.listen(1)

        while True:
            try:
                print("Waiting for Pi A to connect...")
                conn, addr = s.accept()
                handle_client(conn, addr)
                print("Client done; server ready for next connection.")
            except KeyboardInterrupt:
                print("\nPi B: KeyboardInterrupt, shutting down.")
                break
            except Exception as e:
                print("ERROR in accept/handle:", e)
                time.sleep(1.0)  # small backoff and continue listening


if __name__ == "__main__":
    main()


