#!/usr/bin/env python3
"""
Author: Xiaxin Liu
Date: Dec-03-2025

scan_595_tcp_piA.py

Pi A:
- Drives N daisy-chained 74HC595 boards.
- For each 5-bit code, sets all boards to that code, waits DWELL seconds,
  and sends "CODE 00000\n" style lines over TCP to Pi B.
- After finishing, sends "DONE\n", returns outputs to 00000, and exits.

This does NOT talk to any RTD HAT – it just drives the shift-register chain.
"""

import time
import socket
from typing import List

import spidev
import RPi.GPIO as GPIO

# ----------------- CONFIG -----------------

BOARD_COUNT = 24                 # number of 74HC595 boards
CODE_START = 0                   # first 5-bit code (0..31)
CODE_END = 31                    # last 5-bit code (0..31)
DWELL_SECONDS = 1.0              # time to hold each code before moving on

# Bit mapping and ladder behavior (same idea as your scan script)
ACTIVE_BIT_POSITIONS = [0, 1, 2, 3, 4]   # which Q pins carry the 5 bits
UNUSED_LEVEL = 0                         # 0 or 1 for unused outputs
INVERT_BITS = False                      # True if ladder is active-low
REVERSE_BYTE_ORDER = True                # True if chain direction is reversed

# SPI / GPIO
SPI_BUS = 0
SPI_DEV = 0
SPI_MAX_HZ = 1_000_000
SPI_MODE = 0
LATCH_PIN_BCM = 5

# TCP connection settings (Pi B address/port)
SERVER_HOST = "192.168.xx.xx"    # <-- CHANGE to Pi B's IP address by running: hostname -I
SERVER_PORT = 5000

GPIO.setwarnings(False)


# ----------------- LOW-LEVEL HELPERS -----------------

def _pack_code_8bit(code5: int) -> int:
    """
    Map a 5-bit code into an 8-bit value, using ACTIVE_BIT_POSITIONS and UNUSED_LEVEL.
    """
    code5 &= 0x1F
    if INVERT_BITS:
        code5 ^= 0x1F

    byte = 0xFF if UNUSED_LEVEL else 0x00
    for i, qpos in enumerate(ACTIVE_BIT_POSITIONS):
        bit = (code5 >> i) & 0x01
        if bit:
            byte |= (1 << qpos)
        else:
            byte &= ~(1 << qpos)
    return byte & 0xFF


def push_frame(spi, per_board_codes: List[int]):
    """
    Shift out one byte per board and toggle latch.
    per_board_codes is a list of 5-bit integers for each board.
    """
    frame_bytes = [_pack_code_8bit(c) for c in per_board_codes]
    if REVERSE_BYTE_ORDER:
        frame_bytes = list(reversed(frame_bytes))

    if frame_bytes:
        spi.xfer2(frame_bytes)

    GPIO.output(LATCH_PIN_BCM, 1)
    GPIO.output(LATCH_PIN_BCM, 0)


# ----------------- MAIN -----------------

def main():
    # Setup SPI/GPIO
    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEV)
    spi.max_speed_hz = SPI_MAX_HZ
    spi.mode = SPI_MODE

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LATCH_PIN_BCM, GPIO.OUT, initial=GPIO.LOW)

    # Connect to Pi B (TCP)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)

    print(f"Connecting to Pi B at {SERVER_HOST}:{SERVER_PORT} ...")
    try:
        sock.connect((SERVER_HOST, SERVER_PORT))
    except Exception as e:
        print(f"ERROR: Cannot connect to {SERVER_HOST}:{SERVER_PORT}: {e}")
        spi.close()
        GPIO.cleanup(LATCH_PIN_BCM)
        return

    # Small helper to send a line over TCP
    def send_line(text: str):
        try:
            sock.sendall((text + "\n").encode("ascii"))
        except Exception as e:
            print(f"ERROR sending TCP line '{text}': {e}")

    try:
        # Initialize to all zeros
        print("Priming outputs to 00000 ...")
        push_frame(spi, [0] * BOARD_COUNT)
        time.sleep(0.1)

        # Main scan loop
        for code in range(CODE_START, CODE_END + 1):
            code5 = code & 0x1F
            bits_str = format(code5, "05b")

            print(f"Setting boards to code {code5:02d} ({bits_str})")
            push_frame(spi, [code5] * BOARD_COUNT)

            # Inform Pi B about the current code
            send_line(f"CODE {bits_str}")

            # Hold this code so RTDs settle and Pi B can read
            time.sleep(DWELL_SECONDS)

        # Tell Pi B we're done
        print("Scan finished, sending DONE to Pi B")
        send_line("DONE")

        # Reset outputs to 00000
        print("Returning outputs to 00000")
        push_frame(spi, [0] * BOARD_COUNT)
        time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        try:
            send_line("DONE")
        except Exception:
            pass
        push_frame(spi, [0] * BOARD_COUNT)
    finally:
        try:
            sock.close()
        except Exception:
            pass
        try:
            spi.close()
        except Exception:
            pass
        try:
            GPIO.cleanup(LATCH_PIN_BCM)
        except Exception:
            pass
        print("Pi A: Cleaned up and exiting.")


if __name__ == "__main__":
    main()


