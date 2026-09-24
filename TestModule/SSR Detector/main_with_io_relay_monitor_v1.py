#!/usr/bin/env python3
"""
Date: 03/11/2026
Author: Xiaxin Liu
GUI Application with Voltage Input/Output Control
==================================================
Integrates RTD control with voltage sensing and output ramping.

When voltage input changes on ANY channel:
- CSV playback slows to real-time (1 CSV min = 1 real min)
- Voltage outputs ramp accordingly (2V ↔ 10V over 90s)
- After 90s of stability, returns to fast mode (1 CSV min = 1 sec)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Dict, Any, Tuple
import csv
import os
import time
import threading

from chain_driver import ChainDriver, MAX_BOARDS
from csv_utils import detect_t_columns, detect_board_count, row_to_bytes

# Try to import I/O libraries
try:
    import lib16univin
    import SM16uout
    IO_AVAILABLE = True
except ImportError:
    IO_AVAILABLE = False
    print("[Warning] lib16univin or SM16uout not available - I/O features disabled")

# Try to import SMBus for relay detector inputs
try:
    from smbus2 import SMBus
    RELAY_BUS_AVAILABLE = True
except ImportError:
    SMBus = None
    RELAY_BUS_AVAILABLE = False
    print("[Warning] smbus2 not available - relay detect display disabled")

# GUI configuration
DEFAULT_N_BOARDS = 24
DEFAULT_INVERT_BITS = False
DEFAULT_REVERSE_ORDER = False
BOARDS_PER_COLUMN = 8

# I/O Configuration
I2C_BUS = 1
V_MIN = 2.0
V_MAX = 10.0
RAMP_SECONDS = 10.0
ON_THRESHOLD = 9.0
OFF_THRESHOLD = 2
# Valve command semantics:
# - VIN >= ON_THRESHOLD: OPEN command (start/continue ramp up to 10V)
# - VIN around 0V: IDLE (do NOT change valve state; do NOT interrupt an in-progress ramp)
# - VIN in CLOSE band: CLOSE command (start/continue ramp down to 2V)
IDLE_THRESHOLD = 0.2

CLOSE_TRIGGER_LO = 1.8
CLOSE_TRIGGER_HI = 2.2
POLL_PERIOD = 0.5  # Poll inputs every 500ms
STABILITY_TIMEOUT = 90.0  # Return to fast mode after 90s of no changes

# Input/Output channel mapping
# Format: (stack, num_channels)
VIN_BOARDS = [(0, 16), (1, 16), (2, 4)]  # Stack 0: 16ch, Stack 1: 16ch, Stack 2: 4ch
VOUT_BOARDS = [(0, 16), (1, 16), (2, 4)]  # Same mapping

# Valve-number remap (requested):
# V25/26/27 <-> V28/29/30 on stack 1 channels 9-14.
# V11 <-> V24 between (0,11) and (1,8).
VALVE_TO_CHANNEL_OVERRIDES = {
    11: (1, 8),
    24: (0, 11),
    25: (1, 12),
    26: (1, 13),
    27: (1, 14),
    28: (1, 9),
    29: (1, 10),
    30: (1, 11),
}

# Dedicated 0-10V user-controlled output board (stack 3)
USER_VOUT_STACK = 3
USER_VOUT_CHANNELS = 15  # channels 1-15 usable
USER_VOUT_NAMES = [
    "IR6U1", "IR6U2", "IR6L1", "IR6L2",
    "IR16U1", "IR16U2", "IR16L1", "IR16L2",
    "IRVWU1", "IRVWU2", "IRVWL1", "IRVWL2",
    "PCM6 - in tank", "PCM16 - in tank", "PCMWarm - in tank",
]

# Relay detector (MCP23017) display config
RELAY_BUS_NUM = 1
RELAY_ACTIVE_LOW = False
RELAY_USE_INTERNAL_PULLUPS = False
RELAY_STACK_BOARDS = [
    {"stack": 0, "name": "Relay stack0", "addr": 0x20, "channels": 16},
    {"stack": 1, "name": "Relay stack1", "addr": 0x21, "channels": 16},
    {"stack": 2, "name": "Relay stack2", "addr": 0x22, "channels": 8},
]

# MCP23017 registers (BANK=0)
IODIRA = 0x00
IODIRB = 0x01
GPPUA = 0x0C
GPPUB = 0x0D
GPIOA = 0x12
GPIOB = 0x13


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def build_valve_channel_maps(stack_boards: List[Dict[str, Any]], overrides: Dict[int, Tuple[int, int]]):
    """
    Build valve/channel maps for display using stack order, then apply swap overrides.
    Returns (valve_to_channel, channel_to_valve).
    """
    valve_to_channel = {}
    all_channels = set()
    valve_num = 1
    for board in stack_boards:
        stack = int(board["stack"])
        channels = int(board["channels"])
        for ch in range(1, channels + 1):
            valve_to_channel[valve_num] = (stack, ch)
            all_channels.add((stack, ch))
            valve_num += 1

    max_valve = valve_num - 1
    for vnum, mapped in overrides.items():
        if 1 <= int(vnum) <= max_valve and mapped in all_channels:
            valve_to_channel[int(vnum)] = (int(mapped[0]), int(mapped[1]))

    channel_to_valve = {}
    for vnum in sorted(valve_to_channel.keys()):
        channel_to_valve[valve_to_channel[vnum]] = vnum

    return valve_to_channel, channel_to_valve


class RelayDetector:
    """Read relay detect states from MCP23017 stacks for GUI display."""

    def __init__(self):
        self.enabled = RELAY_BUS_AVAILABLE
        self.error = ""
        self.bus = None
        self.boards = []

        for cfg in RELAY_STACK_BOARDS:
            self.boards.append({
                "stack": int(cfg["stack"]),
                "name": str(cfg["name"]),
                "addr": int(cfg["addr"]),
                "channels": int(cfg["channels"]),
            })

        if not self.enabled:
            self.error = "smbus2 unavailable"
            return

        try:
            self.bus = SMBus(RELAY_BUS_NUM)
        except Exception as e:
            self.enabled = False
            self.error = f"I2C bus open failed: {e}"
            return

        init_errors = []
        for board in self.boards:
            try:
                self._init_mcp(board["addr"])
            except Exception as e:
                init_errors.append(f"stack {board['stack']} (0x{board['addr']:02X}): {e}")

        if init_errors:
            self.error = "; ".join(init_errors)

    def _init_mcp(self, addr: int):
        """Configure one MCP23017: all inputs, optional pull-ups."""
        self.bus.write_byte_data(addr, IODIRA, 0xFF)
        self.bus.write_byte_data(addr, IODIRB, 0xFF)
        if RELAY_USE_INTERNAL_PULLUPS:
            self.bus.write_byte_data(addr, GPPUA, 0xFF)
            self.bus.write_byte_data(addr, GPPUB, 0xFF)
        else:
            self.bus.write_byte_data(addr, GPPUA, 0x00)
            self.bus.write_byte_data(addr, GPPUB, 0x00)

    def _read16(self, addr: int) -> int:
        a = self.bus.read_byte_data(addr, GPIOA)
        b = self.bus.read_byte_data(addr, GPIOB)
        return a | (b << 8)

    def _word_to_states(self, word: int, count: int) -> List[int]:
        states = []
        for ch in range(1, count + 1):
            raw = (word >> (ch - 1)) & 1
            states.append((1 - raw) if RELAY_ACTIVE_LOW else raw)
        return states

    def poll(self) -> Dict[int, Dict[str, Any]]:
        """
        Poll all configured relay boards.
        Returns dict keyed by stack with keys: connected, error, states.
        """
        result = {}
        for board in self.boards:
            stack = board["stack"]
            addr = board["addr"]
            count = board["channels"]
            state_info = {
                "stack": stack,
                "name": board["name"],
                "addr": addr,
                "connected": False,
                "error": "",
                "states": [None] * count,
            }

            if not self.enabled or self.bus is None:
                state_info["error"] = self.error or "disabled"
                result[stack] = state_info
                continue

            try:
                raw_word = self._read16(addr)
                state_info["states"] = self._word_to_states(raw_word, count)
                state_info["connected"] = True
            except Exception as e:
                state_info["error"] = str(e)

            result[stack] = state_info

        return result

    def close(self):
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:
                pass
            self.bus = None


class IOController:
    """Manages voltage inputs and outputs with ramping."""

    def __init__(self):
        self.enabled = IO_AVAILABLE
        self.vin_boards = {}
        self.vout_boards = {}
        self.user_vout_board = None
        self.channel_states = {}
        self.user_outputs = {}
        self.last_change_time = 0
        self.any_activity = False

        for ch in range(1, USER_VOUT_CHANNELS + 1):
            self.user_outputs[ch] = 0.0

        if not self.enabled:
            return

        # Initialize input boards (try each stack individually)
        # Try to initialize each VIN stack
        for stack, num_ch in VIN_BOARDS:
            try:
                self.vin_boards[stack] = lib16univin.SM16univin(stack=stack, i2c=I2C_BUS)
                print(f"[IO Init] VIN stack {stack} initialized ({num_ch} channels)")
            except Exception as e:
                print(f"[IO Init] VIN stack {stack} not available (skipping): {e}")

        # Try to initialize each VOUT stack
        for stack, num_ch in VOUT_BOARDS:
            try:
                self.vout_boards[stack] = SM16uout.SM16uout(stack=stack, i2c=I2C_BUS)
                print(f"[IO Init] VOUT stack {stack} initialized ({num_ch} channels)")
            except Exception as e:
                print(f"[IO Init] VOUT stack {stack} not available (skipping): {e}")

        # Initialize dedicated user output board (stack 3)
        try:
            self.user_vout_board = SM16uout.SM16uout(stack=USER_VOUT_STACK, i2c=I2C_BUS)
            print(f"[IO Init] User VOUT stack {USER_VOUT_STACK} initialized ({USER_VOUT_CHANNELS} channels)")
        except Exception as e:
            self.user_vout_board = None
            print(f"[IO Init] User VOUT stack {USER_VOUT_STACK} not available (skipping): {e}")

        # If no boards initialized at all, disable I/O
        if not self.vin_boards and not self.vout_boards:
            print("[IO Init] No I/O boards available - I/O features disabled")
            self.enabled = False
            return

        print(f"[IO Init] Total: {len(self.vin_boards)} VIN stacks, {len(self.vout_boards)} VOUT stacks")

        # State tracking for each channel (only for boards that exist)
        # Key: (stack, channel), Value: dict with state info

        for stack, num_ch in VIN_BOARDS:
            # Only create state for stacks that actually exist
            if stack not in self.vin_boards:
                continue

            for ch in range(1, num_ch + 1):
                self.channel_states[(stack, ch)] = {
                    # input_high is kept for compatibility/logging; it indicates the OPEN command latch.
                    'input_high': False,
                    'mode': 'LOW',  # LOW, HIGH, RAMP_UP, RAMP_DOWN
                    'current_vout': V_MIN,
                    'ramp_start_time': 0,
                    'ramp_start_v': V_MIN,
                    'last_vin': 0.0,
                    'manual_override': False,
                    'manual_vout': V_MIN,
                }
                # Initialize output to V_MIN (if vout board exists)
                if stack in self.vout_boards:
                    try:
                        self.vout_boards[stack].set_u_out(ch, V_MIN)
                    except Exception as e:
                        print(f"[IO Init] Failed to set vout({stack},{ch}) to V_MIN: {e}")

        # Track user-controlled outputs (stack 3)
        if self.user_vout_board:
            for ch in range(1, USER_VOUT_CHANNELS + 1):
                try:
                    self.user_vout_board.set_u_out(ch, 0.0)
                    self.user_outputs[ch] = 0.0
                except Exception as e:
                    print(f"[IO Init] Failed to set user vout({USER_VOUT_STACK},{ch}) to 0.0: {e}")

        self.last_change_time = 0  # Time of last voltage change
        self.any_activity = False

    def poll_inputs(self) -> bool:
        """
        Poll all input channels and update outputs.
        Returns True if any voltage change detected.
        """
        if not self.enabled:
            return False

        now = time.monotonic()
        activity_detected = False

        for stack, num_ch in VIN_BOARDS:
            # Skip stacks that don't exist
            if stack not in self.vin_boards:
                continue

            for ch in range(1, num_ch + 1):
                key = (stack, ch)
                state = self.channel_states[key]

                # Read input voltage
                try:
                    vin = float(self.vin_boards[stack].get_u_in(ch))
                except Exception as e:
                    print(f"[IO Error] Failed to read vin({stack},{ch}): {e}")
                    continue

                # Interpret VIN as commands (do NOT let 0V "idle" cause a close or interrupt ramps)
                open_cmd = vin >= ON_THRESHOLD
                # Treat near-0V as idle; treat ~1V as explicit CLOSE command.
                close_cmd = (CLOSE_TRIGGER_LO <= vin <= CLOSE_TRIGGER_HI)
                # Idle is anything at/below IDLE_THRESHOLD (typically ~0V)

                # Track open_cmd for display/logging; this is not used to auto-close.
                state['input_high'] = open_cmd

                # Manual override path: ignore VIN commands and hold a user-specified VOUT (0-10V).
                if state.get('manual_override', False):
                    manual_v = clamp(float(state.get('manual_vout', state['current_vout'])), 0.0, 10.0)
                    state['mode'] = 'MANUAL'
                    if abs(manual_v - state['current_vout']) > 0.01:
                        activity_detected = True
                        self.last_change_time = now
                        if stack in self.vout_boards:
                            try:
                                self.vout_boards[stack].set_u_out(ch, manual_v)
                                state['current_vout'] = manual_v
                            except Exception as e:
                                print(f"[IO Error] Failed to write manual vout({stack},{ch}): {e}")
                        else:
                            state['current_vout'] = manual_v
                    state['last_vin'] = vin
                    continue

                # Start ramps only on explicit commands; once a ramp starts, it continues to completion
                # even if VIN goes back to idle (0V).
                if open_cmd and state['mode'] not in ('RAMP_UP', 'HIGH'):
                    activity_detected = True
                    self.last_change_time = now
                    state['ramp_start_time'] = now
                    state['ramp_start_v'] = state['current_vout']
                    state['mode'] = 'RAMP_UP'
                    print(f"[IO] vin({stack},{ch}) OPEN cmd ({vin:.2f}V), ramping vout UP")
                elif close_cmd and state['mode'] not in ('RAMP_DOWN', 'LOW'):
                    activity_detected = True
                    self.last_change_time = now
                    state['ramp_start_time'] = now
                    state['ramp_start_v'] = state['current_vout']
                    state['mode'] = 'RAMP_DOWN'
                    print(f"[IO] vin({stack},{ch}) CLOSE cmd ({vin:.2f}V), ramping vout DOWN")

                # Compute new output voltage
                if state['mode'] in ('RAMP_UP', 'RAMP_DOWN'):
                    elapsed = now - state['ramp_start_time']
                    frac = min(1.0, elapsed / RAMP_SECONDS)

                    if state['mode'] == 'RAMP_UP':
                        target = V_MAX
                        new_v = state['ramp_start_v'] + (target - state['ramp_start_v']) * frac
                        if frac >= 1.0:
                            state['mode'] = 'HIGH'
                            print(f"[IO] vin({stack},{ch}) ramp UP complete")
                    else:
                        target = V_MIN
                        new_v = state['ramp_start_v'] + (target - state['ramp_start_v']) * frac
                        if frac >= 1.0:
                            state['mode'] = 'LOW'
                            print(f"[IO] vin({stack},{ch}) ramp DOWN complete")
                else:
                    # Holding steady
                    new_v = V_MAX if state['mode'] == 'HIGH' else V_MIN

                new_v = clamp(new_v, V_MIN, V_MAX)

                # Write output if changed (only if vout board exists)
                if abs(new_v - state['current_vout']) > 0.01:
                    if stack in self.vout_boards:
                        try:
                            self.vout_boards[stack].set_u_out(ch, new_v)
                            state['current_vout'] = new_v
                        except Exception as e:
                            print(f"[IO Error] Failed to write vout({stack},{ch}): {e}")
                    else:
                        # No output board for this stack, just update state
                        state['current_vout'] = new_v

                state['last_vin'] = vin

        # Check if we should be in real-time mode
        time_since_change = now - self.last_change_time
        self.any_activity = time_since_change < STABILITY_TIMEOUT

        return activity_detected

    def is_realtime_mode(self) -> bool:
        """
        Returns True if CSV playback should be in real-time mode.
        Real-time mode when ANY channel is ramping (RAMP_UP or RAMP_DOWN).
        Returns to fast mode when ALL channels are stable (HIGH or LOW).
        """
        # Check if any channel is actively ramping
        for state in self.channel_states.values():
            if state['mode'] in ('RAMP_UP', 'RAMP_DOWN'):
                return True
        return False

    def get_valve_states(self) -> List[Dict[str, Any]]:
        """
        Get status of all valves for display.
        Returns list of dicts with valve info.
        """
        valves = []
        total_valves = sum(num_ch for _, num_ch in VIN_BOARDS)
        for valve_num in range(1, total_valves + 1):
            mapped = self.valve_number_to_channel(valve_num)
            if not mapped:
                continue
            stack, ch = mapped
            key = (stack, ch)

            # Check if this valve exists
            vin_available = stack in self.vin_boards
            vout_available = stack in self.vout_boards

            if key in self.channel_states:
                state = self.channel_states[key]
                valves.append({
                    'num': valve_num,
                    'stack': stack,
                    'channel': ch,
                    'connected': vin_available and vout_available,
                    'mode': state['mode'],
                    'vin': state['last_vin'],
                    'vout': state['current_vout'],
                    'manual_override': bool(state.get('manual_override', False)),
                    'manual_vout': float(state.get('manual_vout', V_MIN)),
                })
            else:
                valves.append({
                    'num': valve_num,
                    'stack': stack,
                    'channel': ch,
                    'connected': False,
                    'mode': 'DISCONNECTED',
                    'vin': 0.0,
                    'vout': 0.0,
                    'manual_override': False,
                    'manual_vout': V_MIN,
                })

        return valves

    def valve_number_to_channel(self, valve_num: int):
        """Map UI valve number (1..36) to (stack, channel)."""
        if valve_num < 1:
            return None
        if valve_num in VALVE_TO_CHANNEL_OVERRIDES:
            return VALVE_TO_CHANNEL_OVERRIDES[valve_num]
        index = 1
        for stack, num_ch in VIN_BOARDS:
            for ch in range(1, num_ch + 1):
                if index == valve_num:
                    return (stack, ch)
                index += 1
        return None

    def set_valve_manual_override(self, stack: int, channel: int, enabled: bool, voltage: float = None) -> Tuple[bool, str]:
        """
        Enable/disable manual VOUT override for valve channels on stacks 0-2.
        When enabled, VIN-driven response is bypassed and VOUT is forced to the manual value.
        """
        key = (stack, channel)
        if key not in self.channel_states:
            return False, "Valve channel not found"

        state = self.channel_states[key]
        if enabled:
            if voltage is None:
                return False, "Manual voltage is required when enabling override"
            target_v = clamp(float(voltage), 0.0, 10.0)
            state['manual_override'] = True
            state['manual_vout'] = target_v
            state['mode'] = 'MANUAL'
            try:
                if stack in self.vout_boards:
                    self.vout_boards[stack].set_u_out(channel, target_v)
                state['current_vout'] = target_v
                return True, ""
            except Exception as e:
                return False, str(e)

        # Disable manual override by returning valve to a deterministic LOW baseline (2.0V).
        # VIN command logic remains unchanged and can ramp from LOW on the next polls.
        target_v = V_MIN
        try:
            if stack in self.vout_boards:
                self.vout_boards[stack].set_u_out(channel, target_v)
            state['current_vout'] = target_v
        except Exception as e:
            return False, str(e)

        state['manual_override'] = False
        state['manual_vout'] = target_v
        state['mode'] = 'LOW'
        return True, ""

    def set_user_output(self, channel: int, voltage: float) -> Tuple[bool, str]:
        """
        Set user-controlled 0-10V output on stack 3.
        Returns (success, message). Message is empty when success is True.
        """
        if not self.enabled or not self.user_vout_board:
            return False, "User output board not available"
        if channel < 1 or channel > USER_VOUT_CHANNELS:
            return False, f"Channel must be 1-{USER_VOUT_CHANNELS}"

        target_v = clamp(voltage, 0.0, 10.0)
        try:
            self.user_vout_board.set_u_out(channel, target_v)
            self.user_outputs[channel] = target_v
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_user_outputs(self) -> List[Dict[str, Any]]:
        """Return list of user output channel states for UI."""
        outputs = []
        board_available = self.user_vout_board is not None and self.enabled
        for ch in range(1, USER_VOUT_CHANNELS + 1):
            name = USER_VOUT_NAMES[ch - 1] if ch - 1 < len(USER_VOUT_NAMES) else f"CH{ch}"
            outputs.append({
                'channel': ch,
                'name': name,
                'voltage': self.user_outputs.get(ch, 0.0),
                'available': board_available,
            })
        return outputs

    def cleanup(self):
        """Reset all outputs to V_MIN."""
        if not self.enabled:
            return
        for stack, num_ch in VOUT_BOARDS:
            # Only cleanup stacks that exist
            if stack not in self.vout_boards:
                continue
            for ch in range(1, num_ch + 1):
                try:
                    self.vout_boards[stack].set_u_out(ch, V_MIN)
                except Exception as e:
                    print(f"[IO Cleanup] Failed to reset vout({stack},{ch}): {e}")
        if self.user_vout_board:
            for ch in range(1, USER_VOUT_CHANNELS + 1):
                try:
                    self.user_vout_board.set_u_out(ch, 0.0)
                except Exception as e:
                    print(f"[IO Cleanup] Failed to reset user vout({USER_VOUT_STACK},{ch}) to 0.0: {e}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RTD Control with Voltage I/O")
        self.minsize(1400, 700)

        # Two main columns: boards on left, valves on right
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        # Give both the board area (row 2) and the valve area (row 1) room
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Right-side container spanning rows 1-2 so valve + stack3 can use the full height
        self.right_panel = ttk.Frame(self)
        self.right_panel.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(0, 10), pady=(6, 10))
        self.right_panel.grid_columnconfigure(0, weight=1)
        # Valves take remaining height; manual + stack3 stay compact
        self.right_panel.grid_rowconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(1, weight=0)
        self.right_panel.grid_rowconfigure(2, weight=0)

        self.driver = ChainDriver(
            n_boards=DEFAULT_N_BOARDS,
            invert=DEFAULT_INVERT_BITS,
            reverse=DEFAULT_REVERSE_ORDER,
        )

        # I/O Controller
        self.io_controller = IOController()
        self.relay_detector = RelayDetector()
        self.relay_valve_to_channel, self.relay_channel_to_valve = build_valve_channel_maps(
            RELAY_STACK_BOARDS, VALVE_TO_CHANNEL_OVERRIDES
        )
        self.relay_channel_labels = {}
        self.relay_status_var = None

        # Mode: manual vs auto
        self.mode_var = tk.StringVar(value="manual")

        # CSV / auto-playback state
        self.csv_rows: List[Dict[str, Any]] = []
        self.csv_header: List[str] = []
        self.csv_tcols: List[str] = []
        self.csv_row_index: int = 0
        self.auto_interval_ms = tk.IntVar(value=1000)  # Fast mode: 1 CSV min = 1 sec
        self.auto_loop = tk.BooleanVar(value=True)
        self.auto_after_id = None
        self.realtime_mode = False  # Track if in real-time mode

        self.board_bit_vars: List[List[tk.IntVar]] = []

        self._build_mode_selector()
        self._build_top_controls()
        self._build_board_grid()
        self._build_valve_display()
        self._build_valve_manual_panel()
        self._build_user_vout_panel()
        self._build_auto_controls()
        self._build_io_status()

        self.status_label = ttk.Label(self, text="", foreground="blue")
        self.status_label.grid(row=5, column=0, columnspan=2, padx=10, pady=(4, 10), sticky="w")
        self._update_status()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start periodic polling if either I/O or relay detector is available.
        if self.io_controller.enabled or self.relay_detector.enabled:
            self.after(int(POLL_PERIOD * 1000), self._poll_io)

    def _build_mode_selector(self):
        frame = ttk.Frame(self)
        frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))
        ttk.Label(frame, text="Mode:").grid(row=0, column=0, padx=(0, 6))
        ttk.Radiobutton(
            frame, text="Manual", value="manual",
            variable=self.mode_var, command=self._on_mode_change
        ).grid(row=0, column=1, padx=4)
        ttk.Radiobutton(
            frame, text="Auto (CSV)", value="auto",
            variable=self.mode_var, command=self._on_mode_change
        ).grid(row=0, column=2, padx=4)

        # Timer mode indicator
        ttk.Label(frame, text="Timer:").grid(row=0, column=3, padx=(20, 6))
        self.timer_mode_var = tk.StringVar(value="FAST")
        self.timer_label = ttk.Label(frame, textvariable=self.timer_mode_var,
                                     font=("TkDefaultFont", 10, "bold"),
                                     foreground="green")
        self.timer_label.grid(row=0, column=4, padx=4)

        frame.grid_columnconfigure(5, weight=1)

    def _build_top_controls(self):
        top = ttk.LabelFrame(self, text="Global Settings")
        top.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 0))
        top.grid_columnconfigure(4, weight=1)

        ttk.Label(top, text="Number of boards").grid(
            row=0, column=0, padx=6, pady=6, sticky="e"
        )
        self.var_boards = tk.IntVar(value=self.driver.n_boards)
        boards_spin = ttk.Spinbox(
            top, from_=1, to=MAX_BOARDS, width=4,
            textvariable=self.var_boards,
            command=self._apply_top_config,
        )
        boards_spin.grid(row=0, column=1, padx=4, pady=6, sticky="w")

        self.var_invert = tk.BooleanVar(value=self.driver.invert_bits)
        ttk.Checkbutton(
            top, text="Invert bits",
            variable=self.var_invert,
            command=self._apply_top_config,
        ).grid(row=0, column=2, padx=8, pady=6)

        self.var_reverse = tk.BooleanVar(value=self.driver.reverse_order)
        ttk.Checkbutton(
            top, text="Reverse byte order",
            variable=self.var_reverse,
            command=self._apply_top_config,
        ).grid(row=0, column=3, padx=8, pady=6)

    def _build_board_grid(self):
        self.board_frame_container = ttk.Frame(self)
        self.board_frame_container.grid(
            row=2, column=0, sticky="nsew", padx=10, pady=10
        )
        self._rebuild_board_controls()

    def _build_valve_display(self):
        """Build valve status display on the right side."""
        valve_frame = ttk.LabelFrame(self.right_panel, text="Valve Status (V1-V36)")
        valve_frame.grid(row=0, column=0, sticky="nsew")
        valve_frame.grid_columnconfigure(0, weight=0)
        valve_frame.grid_columnconfigure(1, weight=1)

        # Left: existing valve table (unchanged behavior)
        grid = ttk.Frame(valve_frame)
        grid.grid(row=0, column=0, sticky="nw", padx=(4, 2), pady=4)

        def build_header(col_offset: int):
            ttk.Label(grid, text="Valve", width=5, font=("TkDefaultFont", 8, "bold")).grid(row=0, column=col_offset + 0, sticky="w", padx=(0, 4))
            ttk.Label(grid, text="Status", width=8, font=("TkDefaultFont", 8, "bold")).grid(row=0, column=col_offset + 1, sticky="w", padx=(0, 4))
            ttk.Label(grid, text="VIN", width=6, font=("TkDefaultFont", 8, "bold")).grid(row=0, column=col_offset + 2, sticky="w", padx=(0, 4))
            ttk.Label(grid, text="VOUT", width=6, font=("TkDefaultFont", 8, "bold")).grid(row=0, column=col_offset + 3, sticky="w", padx=(0, 10))

        build_header(0)
        build_header(4)

        self.valve_labels = []
        for i in range(36):
            group = 0 if i < 18 else 1
            row = (i % 18) + 1
            col_offset = 0 if group == 0 else 4

            valve_label = ttk.Label(grid, text=f"V{i+1:02d}", width=5, font=("TkDefaultFont", 8))
            valve_label.grid(row=row, column=col_offset + 0, sticky="w", padx=(0, 4), pady=1)

            status_label = ttk.Label(grid, text="---", width=8, font=("TkDefaultFont", 8))
            status_label.grid(row=row, column=col_offset + 1, sticky="w", padx=(0, 4), pady=1)

            vin_label = ttk.Label(grid, text="0.0V", width=6, font=("TkDefaultFont", 8))
            vin_label.grid(row=row, column=col_offset + 2, sticky="w", padx=(0, 4), pady=1)

            vout_label = ttk.Label(grid, text="0.0V", width=6, font=("TkDefaultFont", 8))
            vout_label.grid(row=row, column=col_offset + 3, sticky="w", padx=(0, 10), pady=1)

            self.valve_labels.append({'status': status_label, 'vin': vin_label, 'vout': vout_label})

        # Right: relay detector uses the blank area next to valve table.
        relay_box = ttk.LabelFrame(valve_frame, text="Relay Detect (V1-V40)")
        relay_box.grid(row=0, column=1, sticky="nsew", padx=(2, 4), pady=4)
        relay_box.grid_columnconfigure(0, weight=1)

        self.relay_status_var = tk.StringVar(value="Initializing relay detector...")
        ttk.Label(relay_box, textvariable=self.relay_status_var, font=("TkDefaultFont", 8, "bold")).grid(
            row=0, column=0, padx=4, pady=(2, 3), sticky="w"
        )

        self.relay_channel_labels = {}
        row_cursor = 1
        for board in RELAY_STACK_BOARDS:
            stack = int(board["stack"])
            addr = int(board["addr"])
            channels = int(board["channels"])

            stack_row = ttk.Frame(relay_box)
            stack_row.grid(row=row_cursor, column=0, padx=4, pady=1, sticky="w")
            row_cursor += 1
            ttk.Label(stack_row, text=f"S{stack} (0x{addr:02X})", width=11, font=("TkDefaultFont", 8, "bold")).grid(
                row=0, column=0, padx=(0, 3), sticky="w"
            )

            tiles = ttk.Frame(stack_row)
            tiles.grid(row=0, column=1, sticky="w")

            for ch in range(1, channels + 1):
                r = (ch - 1) // 8
                c = (ch - 1) % 8
                valve_num = self.relay_channel_to_valve.get((stack, ch))
                valve_text = f"V{valve_num:02d}" if valve_num else "V--"
                title = f"C{ch:02d}/{valve_text}"
                lbl = tk.Label(
                    tiles,
                    text=f"{title}\n---",
                    width=8,
                    height=2,
                    relief="ridge",
                    bd=1,
                    font=("TkDefaultFont", 7, "bold"),
                    bg="#b0b0b0",
                    fg="white",
                )
                lbl.grid(row=r, column=c, padx=1, pady=1, sticky="w")
                self.relay_channel_labels[(stack, ch)] = {"label": lbl, "title": title}

        self._update_relay_display()

    def _build_user_vout_panel(self):
        """User-facing controls for stack 3 (0-10V outputs)."""
        panel = ttk.LabelFrame(self.right_panel, text="Stack 3 — 0-10V Outputs (CH1-15)")
        # Keep this compact (no tall empty box)
        panel.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        # No scrollbar: use a compact 2-column layout so CH1-15 always visible.
        for c in range(10):
            panel.grid_columnconfigure(c, weight=0)
        panel.grid_columnconfigure(9, weight=1)

        def build_header(col_offset: int):
            ttk.Label(panel, text="CH", width=3, font=("TkDefaultFont", 8, "bold")).grid(row=0, column=col_offset + 0, padx=(2, 2), pady=2, sticky="w")
            ttk.Label(panel, text="Name", width=16, font=("TkDefaultFont", 8, "bold")).grid(row=0, column=col_offset + 1, padx=(0, 6), pady=2, sticky="w")
            ttk.Label(panel, text="Set", width=5, font=("TkDefaultFont", 8, "bold")).grid(row=0, column=col_offset + 2, padx=(0, 6), pady=2, sticky="w")
            ttk.Label(panel, text="", width=4).grid(row=0, column=col_offset + 3)  # button column
            ttk.Label(panel, text="Now", width=6, font=("TkDefaultFont", 8, "bold")).grid(row=0, column=col_offset + 4, padx=(0, 10), pady=2, sticky="w")

        build_header(0)
        build_header(5)

        self.user_vout_vars: List[tk.DoubleVar] = []
        self.user_vout_entries: List[ttk.Entry] = []
        self.user_vout_buttons: List[ttk.Button] = []
        self.user_vout_status_labels: List[ttk.Label] = []

        for idx in range(USER_VOUT_CHANNELS):
            ch = idx + 1
            name = USER_VOUT_NAMES[idx] if idx < len(USER_VOUT_NAMES) else f"CH{ch}"
            var = tk.DoubleVar(value=0.0)
            self.user_vout_vars.append(var)

            # 8 rows left column, remaining on right
            group = 0 if idx < 8 else 1
            row = (idx % 8) + 1
            col_offset = 0 if group == 0 else 5

            ttk.Label(panel, text=f"{ch:02d}", width=3).grid(row=row, column=col_offset + 0, padx=(2, 2), pady=2, sticky="w")
            ttk.Label(panel, text=name, width=16).grid(row=row, column=col_offset + 1, padx=(0, 6), pady=2, sticky="w")

            entry = ttk.Entry(panel, width=5, textvariable=var)
            entry.grid(row=row, column=col_offset + 2, padx=(0, 6), pady=2, sticky="w")
            self.user_vout_entries.append(entry)

            btn = ttk.Button(panel, text="Set", width=4, command=lambda c=ch: self._on_user_vout_set(c))
            btn.grid(row=row, column=col_offset + 3, padx=(0, 6), pady=2, sticky="w")
            self.user_vout_buttons.append(btn)

            status = ttk.Label(panel, text="0.00V", width=6)
            status.grid(row=row, column=col_offset + 4, padx=(0, 10), pady=2, sticky="w")
            self.user_vout_status_labels.append(status)

        self._update_user_vout_display(initial=True)

    def _build_valve_manual_panel(self):
        """Manual override controls for valve VOUT (stacks 0-2 only)."""
        panel = ttk.LabelFrame(self.right_panel, text="Valve Manual Override (Stacks 0-2)")
        panel.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        panel.grid_columnconfigure(8, weight=1)

        self.manual_valve_var = tk.StringVar(value="1")
        self.manual_enable_var = tk.BooleanVar(value=False)
        self.manual_vout_var = tk.DoubleVar(value=V_MIN)
        self.manual_status_var = tk.StringVar(value="")

        ttk.Label(panel, text="Valve").grid(row=0, column=0, padx=(6, 4), pady=6, sticky="w")
        self.manual_valve_combo = ttk.Combobox(
            panel, width=6, state="readonly",
            values=[str(i) for i in range(1, 37)],
            textvariable=self.manual_valve_var,
        )
        self.manual_valve_combo.grid(row=0, column=1, padx=(0, 8), pady=6, sticky="w")
        self.manual_valve_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_manual_override_controls())

        self.manual_enable_check = ttk.Checkbutton(
            panel,
            text="Enable manual override",
            variable=self.manual_enable_var,
            command=self._on_manual_enable_toggle,
        )
        self.manual_enable_check.grid(row=0, column=2, padx=(0, 8), pady=6, sticky="w")

        ttk.Label(panel, text="VOUT (0-10V)").grid(row=0, column=3, padx=(0, 4), pady=6, sticky="w")
        self.manual_vout_entry = ttk.Entry(panel, width=7, textvariable=self.manual_vout_var)
        self.manual_vout_entry.grid(row=0, column=4, padx=(0, 8), pady=6, sticky="w")

        self.manual_apply_btn = ttk.Button(panel, text="Apply", command=self._apply_manual_override)
        self.manual_apply_btn.grid(row=0, column=5, padx=(0, 6), pady=6, sticky="w")
        self.manual_disable_btn = ttk.Button(panel, text="Disable", command=self._disable_manual_override)
        self.manual_disable_btn.grid(row=0, column=6, padx=(0, 6), pady=6, sticky="w")

        self.manual_status_label = ttk.Label(panel, textvariable=self.manual_status_var, foreground="gray")
        self.manual_status_label.grid(row=0, column=7, columnspan=2, padx=(4, 6), pady=6, sticky="w")

        self._refresh_manual_override_controls()

    def _get_selected_valve_channel(self):
        try:
            valve_num = int(self.manual_valve_var.get())
        except Exception:
            return None
        return self.io_controller.valve_number_to_channel(valve_num)

    def _refresh_manual_override_controls(self, preserve_entry: bool = False):
        selected = self._get_selected_valve_channel()
        if not selected:
            self.manual_status_var.set("Invalid valve")
            return

        stack, ch = selected
        channel_states = getattr(self.io_controller, 'channel_states', {})
        state = channel_states.get((stack, ch))
        if not state:
            self.manual_valve_combo.state(["disabled"])
            self.manual_enable_check.state(["disabled"])
            self.manual_vout_entry.state(["disabled"])
            self.manual_apply_btn.state(["disabled"])
            self.manual_disable_btn.state(["disabled"])
            self.manual_status_var.set(f"V{int(self.manual_valve_var.get()):02d} not available")
            return

        board_available = self.io_controller.enabled and (stack in self.io_controller.vout_boards)
        state_flag = ["!disabled"] if board_available else ["disabled"]
        self.manual_valve_combo.state(state_flag)
        self.manual_enable_check.state(state_flag)
        self.manual_vout_entry.state(state_flag)
        self.manual_apply_btn.state(state_flag)
        self.manual_disable_btn.state(state_flag)

        self.manual_enable_var.set(bool(state.get('manual_override', False)))
        if not preserve_entry:
            self.manual_vout_var.set(float(state.get('manual_vout', state.get('current_vout', V_MIN))))

        vnum = int(self.manual_valve_var.get())
        mode = state.get('mode', 'LOW')
        self.manual_status_var.set(
            f"V{vnum:02d} -> stack {stack} ch {ch}, mode={mode}, now={state.get('current_vout', 0.0):.2f}V"
        )

    def _apply_manual_override(self):
        selected = self._get_selected_valve_channel()
        if not selected:
            messagebox.showerror("Selection error", "Select a valid valve.")
            return
        stack, ch = selected

        enabled = bool(self.manual_enable_var.get())
        if enabled:
            try:
                target_v = float(self.manual_vout_var.get())
            except Exception:
                messagebox.showerror("Invalid voltage", "Enter a number between 0 and 10 volts.")
                return
            target_v = clamp(target_v, 0.0, 10.0)
            self.manual_vout_var.set(target_v)
            ok, msg = self.io_controller.set_valve_manual_override(stack, ch, True, target_v)
        else:
            ok, msg = self.io_controller.set_valve_manual_override(stack, ch, False, None)

        if not ok:
            messagebox.showerror("Manual override error", msg)

        self._update_valve_display()
        self._refresh_manual_override_controls()

    def _on_manual_enable_toggle(self):
        """Apply enable/disable immediately when checkbox is toggled."""
        selected = self._get_selected_valve_channel()
        if not selected:
            self.manual_enable_var.set(False)
            return
        stack, ch = selected

        enabled = bool(self.manual_enable_var.get())
        if enabled:
            try:
                target_v = float(self.manual_vout_var.get())
            except Exception:
                self.manual_enable_var.set(False)
                messagebox.showerror("Invalid voltage", "Enter a number between 0 and 10 volts.")
                return
            target_v = clamp(target_v, 0.0, 10.0)
            self.manual_vout_var.set(target_v)
            ok, msg = self.io_controller.set_valve_manual_override(stack, ch, True, target_v)
        else:
            ok, msg = self.io_controller.set_valve_manual_override(stack, ch, False, None)

        if not ok:
            self.manual_enable_var.set(False)
            messagebox.showerror("Manual override error", msg)

        self._update_valve_display()
        self._refresh_manual_override_controls(preserve_entry=True)

    def _disable_manual_override(self):
        selected = self._get_selected_valve_channel()
        if not selected:
            messagebox.showerror("Selection error", "Select a valid valve.")
            return
        stack, ch = selected
        ok, msg = self.io_controller.set_valve_manual_override(stack, ch, False, None)
        if not ok:
            messagebox.showerror("Manual override error", msg)
        self._update_valve_display()
        self._refresh_manual_override_controls()

    def _build_auto_controls(self):
        auto = ttk.LabelFrame(self, text="Auto Mode — CSV Playback")
        auto.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 4))
        auto.grid_columnconfigure(6, weight=1)

        ttk.Button(
            auto, text="Load CSV…",
            command=self._load_csv
        ).grid(row=0, column=0, padx=6, pady=6, sticky="w")

        ttk.Label(auto, text="Interval (ms)").grid(row=0, column=1, padx=(16, 4), pady=6, sticky="e")
        ttk.Entry(auto, width=8, textvariable=self.auto_interval_ms).grid(
            row=0, column=2, padx=4, pady=6, sticky="w"
        )

        ttk.Checkbutton(
            auto, text="Loop",
            variable=self.auto_loop
        ).grid(row=0, column=3, padx=8, pady=6, sticky="w")

        self.auto_btn = ttk.Button(
            auto, text="Start Auto",
            command=self._toggle_auto
        )
        self.auto_btn.grid(row=0, column=4, padx=8, pady=6, sticky="w")

        self.csv_info_label = ttk.Label(auto, text="No CSV loaded", foreground="gray")
        self.csv_info_label.grid(row=1, column=0, columnspan=7, padx=6, pady=(0, 6), sticky="w")

    def _on_user_vout_set(self, channel: int):
        """Handle Set button for user 0-10V outputs."""
        idx = channel - 1
        if idx < 0 or idx >= len(self.user_vout_vars):
            return
        try:
            val = float(self.user_vout_vars[idx].get())
        except Exception:
            messagebox.showerror("Invalid voltage", "Enter a number between 0 and 10 volts.")
            return

        # Clamp to 0-10V as safety
        if val < 0.0:
            val = 0.0
        if val > 10.0:
            val = 10.0
        self.user_vout_vars[idx].set(val)

        ok, msg = self.io_controller.set_user_output(channel, val)
        if not ok:
            messagebox.showerror("Output error", msg)
        self._update_user_vout_display()

    def _update_user_vout_display(self, initial: bool = False):
        """Refresh labels/state for stack 3 outputs."""
        outputs = self.io_controller.get_user_outputs()
        board_available = bool(outputs and outputs[0]['available'])

        for out in outputs:
            idx = out['channel'] - 1
            if idx >= len(self.user_vout_status_labels):
                continue
            if initial:
                self.user_vout_vars[idx].set(out['voltage'])
            self.user_vout_status_labels[idx].config(text=f"{out['voltage']:.2f}V")

            state_flag = ["!disabled"] if board_available else ["disabled"]
            self.user_vout_entries[idx].state(state_flag)
            self.user_vout_buttons[idx].state(state_flag)

    def _build_io_status(self):
        """Build I/O status display."""
        io_frame = ttk.LabelFrame(self, text="Voltage I/O Status")
        io_frame.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 4))

        self.io_status_var = tk.StringVar()
        if self.io_controller.enabled:
            vin_stacks = sorted(self.io_controller.vin_boards.keys())
            vout_stacks = sorted(self.io_controller.vout_boards.keys())
            status = f"I/O enabled - VIN stacks: {vin_stacks}, VOUT stacks: {vout_stacks}"
            self.io_status_var.set(status)
        else:
            self.io_status_var.set("I/O disabled - lib16univin or SM16uout not available")

        ttk.Label(io_frame, textvariable=self.io_status_var).grid(
            row=0, column=0, padx=6, pady=6, sticky="w"
        )

    def _rebuild_board_controls(self):
        for child in self.board_frame_container.winfo_children():
            child.destroy()
        self.board_bit_vars = []

        n = self.driver.n_boards
        n_columns = (n + BOARDS_PER_COLUMN - 1) // BOARDS_PER_COLUMN

        for c in range(n_columns):
            self.board_frame_container.grid_columnconfigure(c, weight=1)
        # Don't stretch board rows vertically (this created the big blank space).
        for r in range(BOARDS_PER_COLUMN):
            self.board_frame_container.grid_rowconfigure(r, weight=0)
        # Add a spacer row that takes remaining space and keeps boards packed at the top.
        self.board_frame_container.grid_rowconfigure(BOARDS_PER_COLUMN, weight=1)

        for board_index in range(n):
            col = board_index // BOARDS_PER_COLUMN
            row = board_index % BOARDS_PER_COLUMN

            frame = ttk.LabelFrame(
                self.board_frame_container, text=f"Board {board_index + 1}"
            )
            frame.grid(row=row, column=col, sticky="w", padx=5, pady=5)

            vars_for_board: List[tk.IntVar] = []
            for bit_index in range(5):
                v = tk.IntVar(value=self.driver.board_bits[board_index][bit_index])
                vars_for_board.append(v)
            self.board_bit_vars.append(vars_for_board)

            for ui_idx, label in enumerate(["b4", "b3", "b2", "b1", "b0"]):
                bit_idx = 4 - ui_idx
                chk = ttk.Checkbutton(
                    frame, text=label,
                    variable=vars_for_board[bit_idx],
                    command=lambda b=board_index, bi=bit_idx: self._on_board_bit_toggle(b, bi),
                )
                chk.grid(row=0, column=ui_idx, padx=4, pady=4)

            quick = ttk.Frame(frame)
            quick.grid(row=1, column=0, columnspan=5, pady=(2, 4))
            btn_all0 = ttk.Button(
                quick, text="All 0", width=6,
                command=lambda b=board_index: self._set_board_bits(b, [0, 0, 0, 0, 0]),
            )
            btn_all1 = ttk.Button(
                quick, text="All 1", width=6,
                command=lambda b=board_index: self._set_board_bits(b, [1, 1, 1, 1, 1]),
            )
            btn_all0.grid(row=0, column=0, padx=2)
            btn_all1.grid(row=0, column=1, padx=2)

        self._update_manual_controls_state(enabled=(self.mode_var.get() == "manual"))

    def _on_board_bit_toggle(self, board_index: int, bit_index: int):
        if self.mode_var.get() != "manual":
            return
        val = self.board_bit_vars[board_index][bit_index].get()
        self.driver.set_board_bit(board_index, bit_index, val)
        self._update_status()

    def _set_board_bits(self, board_index: int, bits: List[int]):
        if self.mode_var.get() != "manual":
            return
        for i in range(5):
            self.board_bit_vars[board_index][i].set(
                1 if (i < len(bits) and bits[i]) else 0
            )
        self.driver.set_board_bits(board_index, bits)
        self._update_status()

    def _sync_gui_from_driver(self):
        for b_idx, bits in enumerate(self.driver.board_bits):
            if b_idx >= len(self.board_bit_vars):
                break
            for i in range(5):
                self.board_bit_vars[b_idx][i].set(1 if (i < len(bits) and bits[i]) else 0)

    def _apply_top_config(self):
        self.driver.configure(
            self.var_boards.get(),
            self.var_invert.get(),
            self.var_reverse.get(),
        )
        self._rebuild_board_controls()
        self._update_status()

    def _update_status(self, extra: str = ""):
        frame = self.driver.get_frame_bytes()
        text = "Frame bytes: " + " ".join(f"0x{b:02X}" for b in frame[:8])
        if len(frame) > 8:
            text += f" ... (total {len(frame)} boards)"
        if extra:
            text += "   |   " + extra
        self.status_label.config(text=text)

    def _on_mode_change(self):
        current_mode = self.mode_var.get()
        if current_mode != "auto":
            self._stop_auto(silent=True)
        self._update_manual_controls_state(enabled=(current_mode == "manual"))

    def _update_manual_controls_state(self, enabled: bool):
        state = ["!disabled"] if enabled else ["disabled"]
        for frame in self.board_frame_container.winfo_children():
            if not isinstance(frame, ttk.LabelFrame):
                continue
            for child in frame.winfo_children():
                if isinstance(child, (ttk.Checkbutton, ttk.Button)):
                    child.state(state)
                elif isinstance(child, ttk.Frame):
                    for subchild in child.winfo_children():
                        if isinstance(subchild, (ttk.Checkbutton, ttk.Button)):
                            subchild.state(state)

    def _load_csv(self):
        path = filedialog.askopenfilename(
            title="Select mapped RTD CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                header = reader.fieldnames or []
        except Exception as e:
            messagebox.showerror("CSV error", f"Failed to read CSV:\n{e}")
            return

        if not rows:
            messagebox.showwarning("CSV empty", "The selected CSV has no data rows.")
            return

        tcols = detect_t_columns(header)
        if not tcols:
            messagebox.showwarning("No T* columns", "CSV does not contain any T1..Tn columns.")
            return

        self.csv_rows = rows
        self.csv_header = header
        self.csv_tcols = tcols
        self.csv_row_index = 0

        csv_board_count = len(tcols)
        print(f"[CSV Load] Detected {csv_board_count} T columns")

        first_ts = rows[0].get("Timestamp", "row1")
        last_ts = rows[-1].get("Timestamp", f"row{len(rows)}")

        info = (
            f"CSV loaded: {os.path.basename(path)} — "
            f"{len(rows)} rows, {csv_board_count} T* columns, "
            f"time {first_ts} → {last_ts}"
        )
        self.csv_info_label.config(text=info, foreground="black")

        self.var_boards.set(csv_board_count)
        self._apply_top_config()

        if rows:
            print(f"[CSV Load] Applying first row as preview...")
            self._apply_csv_row(rows[0], 0)
            messagebox.showinfo("CSV Loaded",
                               f"Loaded {len(rows)} rows with {csv_board_count} boards.\n"
                               f"First row applied to hardware.\n"
                               f"Click 'Start Auto' to begin playback.")

    def _toggle_auto(self):
        if self.auto_after_id is None:
            self._start_auto()
        else:
            self._stop_auto()

    def _start_auto(self):
        if not self.csv_rows:
            messagebox.showwarning("No CSV", "Load a CSV file first.")
            return
        if self.mode_var.get() != "auto":
            self.mode_var.set("auto")
            self._on_mode_change()

        if self.driver.n_boards < 1:
            messagebox.showerror("No boards", "Number of boards must be at least 1.")
            return

        try:
            interval = int(self.auto_interval_ms.get())
        except Exception:
            interval = 1000
            self.auto_interval_ms.set(interval)
        if interval < 50:
            interval = 50
            self.auto_interval_ms.set(interval)

        self.auto_btn.config(text="Stop Auto")
        self._schedule_next_step()

    def _stop_auto(self, silent: bool = False):
        if self.auto_after_id is not None:
            try:
                self.after_cancel(self.auto_after_id)
            except Exception:
                pass
            self.auto_after_id = None
        self.auto_btn.config(text="Start Auto")
        if (not silent) and self.csv_rows:
            self._update_status(extra=f"Auto stopped at row {self.csv_row_index+1}/{len(self.csv_rows)}")

    def _schedule_next_step(self):
        # Check if we should be in real-time mode (any valve ramping)
        should_be_realtime = self.io_controller.is_realtime_mode()

        if should_be_realtime:
            if not self.realtime_mode:
                print("[CSV Playback] Switching to SLOW (Real-time) mode - valves ramping")
                self.realtime_mode = True
            # Real-time: 1 CSV minute = 60 seconds
            interval = 60000  # 60 seconds in ms
        else:
            if self.realtime_mode:
                print("[CSV Playback] Switching to FAST mode - all valves stable")
                self.realtime_mode = False
            # Fast mode: use configured interval
            interval = max(50, int(self.auto_interval_ms.get()))

        self.auto_after_id = self.after(interval, self._auto_step)

    def _auto_step(self):
        if not self.csv_rows:
            self._stop_auto()
            return

        if self.csv_row_index >= len(self.csv_rows):
            if self.auto_loop.get():
                self.csv_row_index = 0
            else:
                self._stop_auto()
                return

        row = self.csv_rows[self.csv_row_index]
        self._apply_csv_row(row, self.csv_row_index)
        self.csv_row_index += 1
        self._schedule_next_step()

    def _apply_csv_row(self, row: Dict[str, Any], idx: int):
        if idx == 0:
            print(f"[CSV Parse] Sample T column values:")
            for i, tcol in enumerate(self.csv_tcols[:5]):
                val = row.get(tcol, "")
                print(f"  {tcol} = '{val}'")

        frame_bytes = row_to_bytes(
            row=row,
            fieldnames=self.csv_header,
            boards_hint=self.driver.n_boards,
            invert_bits=self.var_invert.get(),
        )
        if not frame_bytes:
            frame_bytes = [0] * self.driver.n_boards

        if len(frame_bytes) > 10:
            hex_preview = [hex(b) for b in frame_bytes[:5]] + ['...'] + [hex(b) for b in frame_bytes[-3:]]
            mode_str = "SLOW" if self.realtime_mode else "FAST"
            print(f"[Auto Mode/{mode_str}] Row {idx+1}: {len(frame_bytes)} boards, bytes={hex_preview}")
        else:
            mode_str = "SLOW" if self.realtime_mode else "FAST"
            print(f"[Auto Mode/{mode_str}] Row {idx+1}: frame_bytes={[hex(b) for b in frame_bytes]}")

        self.driver.set_frame_raw(frame_bytes, apply_inversion=False)
        self._sync_gui_from_driver()

        extra = f"row {idx+1}/{len(self.csv_rows)}" if len(self.csv_rows) > 0 else "CSV preview"
        if self.realtime_mode:
            extra += " [SLOW/REAL-TIME]"
        else:
            extra += " [FAST]"
        ts = row.get("Timestamp")
        if ts:
            extra += f" @ {ts}"
        self._update_status(extra=extra)

    def _poll_io(self):
        """Poll voltage inputs and update status."""
        if self.io_controller.enabled:
            activity = self.io_controller.poll_inputs()

            # Update timer mode display
            if self.io_controller.is_realtime_mode():
                self.timer_mode_var.set("SLOW (Real-time)")
                self.timer_label.config(foreground="red")
                self.io_status_var.set("I/O active - Valves ramping (CSV in REAL-TIME mode)")
            else:
                self.timer_mode_var.set("FAST")
                self.timer_label.config(foreground="green")
                self.io_status_var.set("I/O enabled - All valves stable (CSV in FAST mode)")

            # Update valve display
            self._update_valve_display()

        self._update_relay_display()

        # Always refresh user output display (enabled/disabled + current values)
        self._update_user_vout_display()
        self._refresh_manual_override_controls(preserve_entry=True)

        # Schedule next poll
        self.after(int(POLL_PERIOD * 1000), self._poll_io)

    def _update_relay_display(self):
        """Update MCP23017 relay-detect tiles (CHxx + mapped Vxx)."""
        if not self.relay_channel_labels:
            return

        if not self.relay_detector.enabled:
            reason = self.relay_detector.error or "disabled"
            self.relay_status_var.set(f"Relay detector disabled: {reason}")
            for entry in self.relay_channel_labels.values():
                entry["label"].config(text=f"{entry['title']}\nN/A", bg="#8a8a8a", fg="white")
            return

        data = self.relay_detector.poll()
        connected = 0
        total = len(RELAY_STACK_BOARDS)
        errors = []

        for board in RELAY_STACK_BOARDS:
            stack = int(board["stack"])
            channels = int(board["channels"])
            info = data.get(stack, {})
            if info.get("connected"):
                connected += 1
            elif info.get("error"):
                errors.append(f"stack {stack}: {info['error']}")

            states = info.get("states", [None] * channels)
            for ch in range(1, channels + 1):
                entry = self.relay_channel_labels.get((stack, ch))
                if not entry:
                    continue
                state = states[ch - 1] if (ch - 1) < len(states) else None
                if state is None:
                    entry["label"].config(text=f"{entry['title']}\nERR", bg="#8a8a8a", fg="white")
                elif int(state) == 1:
                    entry["label"].config(text=f"{entry['title']}\nON", bg="#2e7d32", fg="white")
                else:
                    entry["label"].config(text=f"{entry['title']}\nOFF", bg="#c62828", fg="white")

        if errors:
            self.relay_status_var.set(f"Relay stacks: {connected}/{total} connected | {errors[0]}")
        else:
            self.relay_status_var.set(f"Relay stacks: {connected}/{total} connected")

    def _update_valve_display(self):
        """Update valve status labels."""
        if not self.io_controller.enabled:
            # Show all as disconnected if I/O not available
            for labels in self.valve_labels:
                labels['status'].config(text="DISABLED", foreground="gray")
                labels['vin'].config(text="---", foreground="gray")
                labels['vout'].config(text="---", foreground="gray")
            return

        valves = self.io_controller.get_valve_states()

        for i, valve in enumerate(valves):
            if i >= len(self.valve_labels):
                break

            labels = self.valve_labels[i]

            if not valve['connected']:
                labels['status'].config(text="NO BOARD", foreground="gray")
                labels['vin'].config(text="---", foreground="gray")
                labels['vout'].config(text="---", foreground="gray")
            else:
                # Color code by mode
                mode = valve['mode']
                if mode == 'RAMP_UP':
                    color = "orange"
                    status_text = "RAMP ↑"
                elif mode == 'RAMP_DOWN':
                    color = "blue"
                    status_text = "RAMP ↓"
                elif mode == 'HIGH':
                    color = "green"
                    status_text = "HIGH"
                elif mode == 'MANUAL':
                    color = "darkorange"
                    status_text = "MANUAL"
                elif mode == 'LOW':
                    color = "black"
                    status_text = "LOW"
                else:
                    color = "gray"
                    status_text = mode

                labels['status'].config(text=status_text, foreground=color)
                labels['vin'].config(text=f"{valve['vin']:.1f}V", foreground="black")
                labels['vout'].config(text=f"{valve['vout']:.1f}V", foreground=color)

    def _on_close(self):
        self._stop_auto(silent=True)
        self.io_controller.cleanup()
        self.relay_detector.close()
        self.driver.close()
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
