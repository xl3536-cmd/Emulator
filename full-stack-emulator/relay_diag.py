#!/usr/bin/env python3
"""SM16relind feedback relay control + OV live monitor for the emulator.

Usage:
    python3 relay_diag.py read [--stack 0]
    python3 relay_diag.py set STACK CHANNEL {on|off}
    python3 relay_diag.py test [--stack 0] [--start 1] [--end 16]
    python3 relay_diag.py zero [--stack 0]
    python3 relay_diag.py monitor [--config PATH] [--interval 0.2] [--threshold 1.0]
    python3 relay_diag.py probe   [--addresses 0x20-0x27] [--interval 0.2]

Examples:
    python3 relay_diag.py read                    # see all 16 relay states on stack 0
    python3 relay_diag.py set 0 2 on              # turn on channel 2 (OV1 open feedback)
    python3 relay_diag.py set 0 2 off             # turn off channel 2
    python3 relay_diag.py set 0 10 on             # turn on channel 10 (OV5 open feedback)
    python3 relay_diag.py test                    # test all 16 channels one by one
    python3 relay_diag.py test --start 9 --end 16 # test just channels 9-16
    python3 relay_diag.py zero                    # turn all relays off
    python3 relay_diag.py monitor                 # OV live feed: prints when any OV signal flips
    python3 relay_diag.py probe                   # scan 0x20-0x27 inputs, log any bit change
    python3 relay_diag.py probe --addresses 0x20,0x21,0x27,0x41,0x58
"""

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

OV_CHANNEL_MAP = {
    1: "OV1 close",  2: "OV1 open",
    3: "OV2 close",  4: "OV2 open",
    5: "OV3 close",  6: "OV3 open",
    7: "OV4 close",  8: "OV4 open",
    9: "OV5 close", 10: "OV5 open",
   11: "OV6 close", 12: "OV6 open",
   13: "OV7 close", 14: "OV7 open",
   15: "OV8 close", 16: "OV8 open",
}


def get_board(stack, i2c_bus=1):
    try:
        import SM16relind
    except ImportError:
        print("ERROR: SM16relind not installed. Run: sudo pip3 install SM16relind")
        sys.exit(1)
    try:
        return SM16relind.SM16relind(stack=stack, i2c=i2c_bus)
    except Exception as exc:
        print(f"ERROR: No relay board at stack {stack}: {exc}")
        sys.exit(1)


def cmd_read(args):
    board = get_board(args.stack, args.i2c)
    bitmap = board.get_all()
    print(f"\n  SM16relind  Stack {args.stack}  Bitmap: 0x{bitmap:04X}\n")
    print(f"  {'Ch':>4}  {'State':>6}  {'Label'}")
    print(f"  {'--':>4}  {'-----':>6}  {'-----'}")
    for ch in range(1, 17):
        try:
            val = board.get(ch)
            state = "ON" if val else "OFF"
        except Exception as exc:
            state = f"ERR"
        print(f"  {ch:>4}  {state:>6}  {OV_CHANNEL_MAP.get(ch, '')}")
    print()


def cmd_set(args):
    board = get_board(args.stack, args.i2c)
    val = 1 if args.state.lower() in ("on", "1") else 0
    ch = args.channel
    try:
        board.set(ch, val)
        label = "ON" if val else "OFF"
        name = OV_CHANNEL_MAP.get(ch, f"ch {ch}")
        print(f"OK: stack {args.stack}, channel {ch} -> {label}  ({name})")
    except Exception as exc:
        print(f"FAIL: stack {args.stack}, channel {ch}: {exc}")
        sys.exit(1)


def cmd_test(args):
    board = get_board(args.stack, args.i2c)
    start, end, delay = args.start, args.end, args.delay

    print(f"\n  Relay test: stack {args.stack}, channels {start}-{end}\n")
    print(f"  {'Ch':>4}  {'Label':<12}  {'Readback':>8}  {'Result':>8}")
    print(f"  {'--':>4}  {'-----':<12}  {'--------':>8}  {'------':>8}")

    failures = []
    for ch in range(start, end + 1):
        name = OV_CHANNEL_MAP.get(ch, "")
        try:
            board.set(ch, 1)
            time.sleep(delay)
            readback = board.get(ch)
            result = "OK" if readback == 1 else "FAIL"
            if readback != 1:
                failures.append(ch)
            print(f"  {ch:>4}  {name:<12}  {readback:>8}  {result:>8}")
        except Exception as exc:
            failures.append(ch)
            print(f"  {ch:>4}  {name:<12}  {'ERROR':>8}  {exc}")
        finally:
            try:
                board.set(ch, 0)
            except Exception:
                pass

    print()
    if failures:
        print(f"  FAILED channels: {failures}")
    else:
        print(f"  All channels {start}-{end} passed.")
    print()


def cmd_zero(args):
    board = get_board(args.stack, args.i2c)
    board.set_all(0x0000)
    bitmap = board.get_all()
    print(f"All relays OFF on stack {args.stack}. Readback: 0x{bitmap:04X}")


MCP_IODIRA = 0x00
MCP_IODIRB = 0x01
MCP_GPPUA = 0x0C
MCP_GPPUB = 0x0D
MCP_GPIOA = 0x12
MCP_GPIOB = 0x13

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "backend" / "emulator_config.json"


def _try_import_smbus():
    try:
        from smbus2 import SMBus  # type: ignore
        return SMBus
    except ImportError:
        try:
            from smbus import SMBus  # type: ignore
            return SMBus
        except ImportError:
            return None


def _fallback_ov_valves():
    items = []
    for i in range(8):
        n = i + 1
        close_ch = 2 * i + 1
        open_ch = 2 * i + 2
        items.append({
            "id": f"OV{n}",
            "name": f"OV Valve {n}",
            "enabled": True,
            "open_det_addr": 0x20,
            "open_det_ch": open_ch,
            "close_det_addr": 0x20,
            "close_det_ch": close_ch,
            "open_fb_stack": 0,
            "open_fb_ch": open_ch,
            "close_fb_stack": 0,
            "close_fb_ch": close_ch,
        })
    return items


def _load_ov_valves(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f"WARNING: config file not found at {config_path}; using fallback OV1-OV8 layout.")
        return _fallback_ov_valves()
    except Exception as exc:
        print(f"WARNING: failed to read {config_path}: {exc}; using fallback OV1-OV8 layout.")
        return _fallback_ov_valves()

    raw_valves = (data.get("valves") or {}).get("ball_valves") or []
    ov_list = []
    for valve in raw_valves:
        if (valve.get("profile_type") or "").lower() != "ov":
            continue
        try:
            ov_list.append({
                "id": valve["id"],
                "name": valve.get("name", valve["id"]),
                "enabled": bool(valve.get("enabled", True)),
                "open_det_addr": valve["open_detector"]["i2c_address"],
                "open_det_ch": int(valve["open_detector"]["channel"]),
                "close_det_addr": valve["close_detector"]["i2c_address"],
                "close_det_ch": int(valve["close_detector"]["channel"]),
                "open_fb_stack": int(valve["open_feedback"]["stack"]),
                "open_fb_ch": int(valve["open_feedback"]["channel"]),
                "close_fb_stack": int(valve["close_feedback"]["stack"]),
                "close_fb_ch": int(valve["close_feedback"]["channel"]),
            })
        except (KeyError, TypeError, ValueError) as exc:
            vid = valve.get("id", "<unknown>")
            print(f"WARNING: skipping malformed OV valve {vid}: {exc}")
    return ov_list


def _init_mcp(bus, addr):
    try:
        bus.write_byte_data(addr, MCP_IODIRA, 0xFF)
        bus.write_byte_data(addr, MCP_IODIRB, 0xFF)
        bus.write_byte_data(addr, MCP_GPPUA, 0x00)
        bus.write_byte_data(addr, MCP_GPPUB, 0x00)
        return None
    except Exception as exc:
        return str(exc)


def _read_mcp_word(bus, addr):
    try:
        gpio_a = bus.read_byte_data(addr, MCP_GPIOA)
        gpio_b = bus.read_byte_data(addr, MCP_GPIOB)
        return gpio_a | (gpio_b << 8), None
    except Exception as exc:
        return None, str(exc)


def _bit_for_channel(word, channel):
    if word is None or channel is None:
        return None
    if channel < 1 or channel > 16:
        return None
    return (word >> (channel - 1)) & 1


def _nominal_voltage(bit):
    if bit is None:
        return None
    return 5.0 if bit else 0.0


def _build_signal_voltages(ov_valves, mcp_words, relind_states):
    """Return a flat dict of {signal_id: nominal_voltage_or_None}."""
    signals = {}
    for valve in ov_valves:
        if not valve["enabled"]:
            continue
        for side in ("open", "close"):
            addr = valve[f"{side}_det_addr"]
            ch = valve[f"{side}_det_ch"]
            bit = _bit_for_channel(mcp_words.get(addr), ch) if addr is not None else None
            signals[f"{valve['id']}_{side}_det"] = _nominal_voltage(bit)

            stack = valve[f"{side}_fb_stack"]
            fch = valve[f"{side}_fb_ch"]
            state = relind_states.get((stack, fch))
            signals[f"{valve['id']}_{side}_fb"] = _nominal_voltage(state)
    return signals


def _significant_change(prev, curr, threshold):
    if not prev:
        return True
    for key, curr_val in curr.items():
        prev_val = prev.get(key, "missing")
        if curr_val is None and prev_val is None:
            continue
        if curr_val is None or prev_val is None or prev_val == "missing":
            return True
        if abs(curr_val - prev_val) >= threshold:
            return True
    for key in prev.keys():
        if key not in curr:
            return True
    return False


def _format_voltage(volt):
    if volt is None:
        return " n/a "
    return f"{volt:>4.1f}V"


def _det_cell(addr, ch, word):
    if addr is None:
        return f"ch {ch:>2} (no addr)"
    bit = _bit_for_channel(word, ch)
    bit_str = "?" if bit is None else str(bit)
    return f"0x{int(addr):02X} ch{ch:>2} bit={bit_str} {_format_voltage(_nominal_voltage(bit))}"


def _fb_cell(stack, ch, state):
    if state is None:
        label = "?  "
    elif state:
        label = "ON "
    else:
        label = "OFF"
    return f"stk{stack} ch{ch:>2} {label} {_format_voltage(_nominal_voltage(state))}"


def _print_snapshot(ov_valves, mcp_words, mcp_errors, relind_states, relind_errors, threshold):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"\n=== {timestamp}  (snapshot on >= {threshold}V change) ===")

    for addr in sorted(mcp_words.keys()):
        word = mcp_words[addr]
        err = mcp_errors.get(addr)
        if word is None:
            print(f"  MCP 0x{addr:02X}: READ ERROR  {err}")
        else:
            gpio_a = word & 0xFF
            gpio_b = (word >> 8) & 0xFF
            print(f"  MCP 0x{addr:02X}: word=0x{word:04X}  GPIOA=0x{gpio_a:02X}  GPIOB=0x{gpio_b:02X}")

    stacks_seen = sorted({stack for (stack, _) in relind_states.keys()})
    for stack in stacks_seen:
        bitmap = 0
        any_known = False
        for ch in range(1, 17):
            state = relind_states.get((stack, ch))
            if state is None:
                continue
            any_known = True
            if state:
                bitmap |= 1 << (ch - 1)
        err = relind_errors.get(stack)
        if any_known:
            print(f"  SM16relind stack {stack}: bitmap=0x{bitmap:04X}")
        elif err:
            print(f"  SM16relind stack {stack}: READ ERROR  {err}")
        else:
            print(f"  SM16relind stack {stack}: (no readings)")
        if any_known and err:
            print(f"    (latest error: {err})")

    print()
    header = f"  {'Valve':<6}  {'Open Det':<22}  {'Close Det':<22}  {'Open FB (to ctrl ADin)':<26}  {'Close FB (to ctrl ADin)':<27}"
    print(header)
    print(f"  {'-' * 6}  {'-' * 22}  {'-' * 22}  {'-' * 26}  {'-' * 27}")

    for valve in ov_valves:
        if not valve["enabled"]:
            continue
        open_det = _det_cell(valve["open_det_addr"], valve["open_det_ch"], mcp_words.get(valve["open_det_addr"]))
        close_det = _det_cell(valve["close_det_addr"], valve["close_det_ch"], mcp_words.get(valve["close_det_addr"]))
        open_fb = _fb_cell(valve["open_fb_stack"], valve["open_fb_ch"], relind_states.get((valve["open_fb_stack"], valve["open_fb_ch"])))
        close_fb = _fb_cell(valve["close_fb_stack"], valve["close_fb_ch"], relind_states.get((valve["close_fb_stack"], valve["close_fb_ch"])))
        print(f"  {valve['id']:<6}  {open_det:<22}  {close_det:<22}  {open_fb:<26}  {close_fb:<27}")

    print()


def _parse_address_list(spec):
    """Parse a string like '0x20-0x27' or '0x20,0x21,0x27' into a sorted list of ints."""
    if spec is None or not spec.strip():
        return list(range(0x20, 0x28))
    result = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            lo, hi = token.split("-", 1)
            lo_i = int(lo, 0)
            hi_i = int(hi, 0)
            if lo_i > hi_i:
                lo_i, hi_i = hi_i, lo_i
            for addr in range(lo_i, hi_i + 1):
                result.add(addr)
        else:
            result.add(int(token, 0))
    return sorted(addr for addr in result if 0x03 <= addr <= 0x77)


def _describe_bits(word):
    """Return a comma-separated 1-based channel list for set bits in a 16-bit word."""
    if not word:
        return "none"
    return ", ".join(str(ch) for ch in range(1, 17) if (word >> (ch - 1)) & 1)


def cmd_probe(args):
    """Scan a range of I2C addresses for MCP23017-style chips and log any bit change.

    Use this to discover where (if anywhere) a controller-side relay command
    is actually landing on the emulator's I2C bus. Hold the controller frontend
    on a single valve command and watch which address+channel changes.
    """
    SMBus = _try_import_smbus()
    if SMBus is None:
        print("ERROR: smbus2/smbus not installed; cannot probe I2C bus.")
        sys.exit(1)

    addresses = _parse_address_list(args.addresses)
    if not addresses:
        print("ERROR: no valid I2C addresses to probe (use --addresses 0xNN[-0xMM][,...]).")
        sys.exit(1)

    try:
        bus = SMBus(args.i2c)
    except Exception as exc:
        print(f"ERROR: could not open I2C bus {args.i2c}: {exc}")
        sys.exit(1)

    print(f"\nProbing I2C bus {args.i2c} addresses {', '.join(f'0x{a:02X}' for a in addresses)}")
    print(f"  poll interval: {args.interval:.2f}s")
    print(f"  press Ctrl+C to stop\n")

    responsive = []
    for addr in addresses:
        try:
            bus.read_byte_data(addr, 0x00)
            responsive.append(addr)
        except Exception:
            continue

    if not responsive:
        print("  No I2C devices responded in that address range.")
        print("  Try `sudo i2cdetect -y 1` to confirm what's on the bus.")
        try:
            bus.close()
        except Exception:
            pass
        return

    print(f"  Responsive devices: {', '.join(f'0x{a:02X}' for a in responsive)}\n")

    # Only ever init chips whose I2C addresses fall in the MCP23017 range
    # (0x20-0x27). Writing IODIR/GPPU bytes to non-MCP chips (e.g. Sequent
    # SM16uout at 0x41 or SM16univin at 0x58) can clobber their internal
    # control registers. We still passively READ 0x12/0x13 on out-of-range
    # addresses below, just to see if anything happens to look like GPIO
    # state, but we never write to them.
    mcp_addresses = [a for a in responsive if 0x20 <= a <= 0x27]
    non_mcp_addresses = [a for a in responsive if not (0x20 <= a <= 0x27)]

    initialized = []
    init_failed = []
    for addr in mcp_addresses:
        try:
            bus.write_byte_data(addr, MCP_IODIRA, 0xFF)
            bus.write_byte_data(addr, MCP_IODIRB, 0xFF)
            bus.write_byte_data(addr, MCP_GPPUA, 0x00)
            bus.write_byte_data(addr, MCP_GPPUB, 0x00)
            initialized.append(addr)
        except Exception as exc:
            init_failed.append((addr, str(exc)))

    if initialized:
        print(f"  Initialized as MCP23017 inputs: {', '.join(f'0x{a:02X}' for a in initialized)}")
    for addr, err in init_failed:
        print(f"  WARNING: 0x{addr:02X} did not accept MCP23017 init ({err}); will still try to read GPIOA/GPIOB.")
    if non_mcp_addresses:
        print(
            f"  Skipping MCP-style init for {', '.join(f'0x{a:02X}' for a in non_mcp_addresses)} "
            f"(outside 0x20-0x27, likely Sequent analog HATs); will only passively read 0x12/0x13."
        )
    print()

    prev_state = {}
    try:
        first_pass = True
        while True:
            for addr in responsive:
                word, err = _read_mcp_word(bus, addr)
                if word is None:
                    if first_pass:
                        print(f"  0x{addr:02X}: read ERROR ({err})")
                    continue
                previous = prev_state.get(addr)
                if first_pass:
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    print(
                        f"  {timestamp}  0x{addr:02X}  word=0x{word:04X}  "
                        f"GPIOA=0x{word & 0xFF:02X}  GPIOB=0x{(word >> 8) & 0xFF:02X}  "
                        f"high_channels: {_describe_bits(word)}"
                    )
                    prev_state[addr] = word
                elif previous != word:
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    rose = word & ~(previous or 0)
                    fell = (previous or 0) & ~word
                    print(
                        f"  {timestamp}  0x{addr:02X}  word=0x{word:04X}  "
                        f"GPIOA=0x{word & 0xFF:02X}  GPIOB=0x{(word >> 8) & 0xFF:02X}"
                    )
                    if rose:
                        print(f"      ↑ rose:   channels {_describe_bits(rose)}")
                    if fell:
                        print(f"      ↓ fell:   channels {_describe_bits(fell)}")
                    prev_state[addr] = word
            first_pass = False
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        try:
            bus.close()
        except Exception:
            pass


def cmd_monitor(args):
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    ov_valves = _load_ov_valves(config_path)
    if not ov_valves:
        print("ERROR: no OV valves discovered (empty fallback?). Aborting.")
        sys.exit(1)

    enabled_valves = [valve for valve in ov_valves if valve["enabled"]]
    print(f"\nLoaded {len(ov_valves)} OV valves from {config_path}")
    print(f"  enabled: {len(enabled_valves)}  ({', '.join(valve['id'] for valve in enabled_valves) or 'none'})")
    print(f"  polling interval: {args.interval:.2f}s")
    print(f"  snapshot trigger: any tracked signal moves >= {args.threshold:.2f}V")
    print(f"  press Ctrl+C to stop\n")

    detector_addrs = sorted({
        valve[key]
        for valve in enabled_valves
        for key in ("open_det_addr", "close_det_addr")
        if valve[key] is not None
    })
    feedback_stacks = sorted({
        valve[key]
        for valve in enabled_valves
        for key in ("open_fb_stack", "close_fb_stack")
    })

    SMBus = _try_import_smbus()
    bus = None
    mcp_init_errors = {}
    if SMBus is None:
        print("WARNING: smbus2/smbus not installed; MCP23017 detector reads disabled.")
    else:
        try:
            bus = SMBus(args.i2c)
        except Exception as exc:
            print(f"WARNING: could not open I2C bus {args.i2c}: {exc}; detector reads disabled.")
            bus = None
        if bus is not None:
            for addr in detector_addrs:
                err = _init_mcp(bus, addr)
                mcp_init_errors[addr] = err
                if err is None:
                    print(f"  Initialized MCP23017 0x{addr:02X} on I2C bus {args.i2c}")
                else:
                    print(f"  WARNING: MCP23017 0x{addr:02X} init failed: {err}")

    relind_boards = {}
    relind_open_errors = {}
    try:
        import SM16relind  # type: ignore
    except ImportError:
        SM16relind = None  # type: ignore
        print("WARNING: SM16relind not installed; feedback relay reads disabled.")
    if SM16relind is not None:
        for stack in feedback_stacks:
            try:
                relind_boards[stack] = SM16relind.SM16relind(stack=stack, i2c=args.i2c)
                print(f"  Initialized SM16relind stack {stack} on I2C bus {args.i2c}")
            except Exception as exc:
                relind_open_errors[stack] = str(exc)
                print(f"  WARNING: SM16relind stack {stack} init failed: {exc}")

    prev_signals = {}
    try:
        while True:
            mcp_words = {}
            mcp_errors = dict(mcp_init_errors)
            if bus is not None:
                for addr in detector_addrs:
                    word, err = _read_mcp_word(bus, addr)
                    mcp_words[addr] = word
                    if err is not None:
                        mcp_errors[addr] = err
                    elif word is not None:
                        mcp_errors.pop(addr, None)
            else:
                for addr in detector_addrs:
                    mcp_words[addr] = None

            relind_states = {}
            relind_errors = dict(relind_open_errors)
            for stack in feedback_stacks:
                board = relind_boards.get(stack)
                if board is None:
                    for ch in range(1, 17):
                        relind_states[(stack, ch)] = None
                    continue
                try:
                    bitmap = int(board.get_all())
                    for ch in range(1, 17):
                        relind_states[(stack, ch)] = (bitmap >> (ch - 1)) & 1
                    relind_errors.pop(stack, None)
                except Exception as exc:
                    relind_errors[stack] = str(exc)
                    for ch in range(1, 17):
                        relind_states[(stack, ch)] = None

            signals = _build_signal_voltages(enabled_valves, mcp_words, relind_states)
            if _significant_change(prev_signals, signals, args.threshold):
                _print_snapshot(enabled_valves, mcp_words, mcp_errors, relind_states, relind_errors, args.threshold)
                prev_signals = signals

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="SM16relind feedback relay control")
    parser.add_argument("--i2c", type=int, default=1)

    sub = parser.add_subparsers(dest="command")

    p_read = sub.add_parser("read", help="Read all relay states")
    p_read.add_argument("--stack", type=int, default=0)

    p_set = sub.add_parser("set", help="Set a relay channel on or off")
    p_set.add_argument("stack", type=int)
    p_set.add_argument("channel", type=int)
    p_set.add_argument("state", choices=["on", "off"])

    p_test = sub.add_parser("test", help="Test channels one by one (set, readback, clear)")
    p_test.add_argument("--stack", type=int, default=0)
    p_test.add_argument("--start", type=int, default=1)
    p_test.add_argument("--end", type=int, default=16)
    p_test.add_argument("--delay", type=float, default=0.3)

    p_zero = sub.add_parser("zero", help="Turn all relays off")
    p_zero.add_argument("--stack", type=int, default=0)

    p_monitor = sub.add_parser(
        "monitor",
        help="OV live monitor: prints a snapshot whenever any detector or feedback signal flips",
    )
    p_monitor.add_argument(
        "--config",
        type=str,
        default=None,
        help=f"Path to emulator_config.json (default: {DEFAULT_CONFIG_PATH})",
    )
    p_monitor.add_argument(
        "--interval",
        type=float,
        default=0.2,
        help="Poll interval in seconds (default: 0.2)",
    )
    p_monitor.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="Voltage delta that triggers a new snapshot (default: 1.0)",
    )

    p_probe = sub.add_parser(
        "probe",
        help="Scan I2C addresses, treat each responsive chip as MCP23017 inputs, and log bit changes.",
    )
    p_probe.add_argument(
        "--addresses",
        type=str,
        default="0x20-0x27",
        help="Address list/range to probe, e.g. '0x20-0x27' or '0x20,0x21,0x27'. Default: 0x20-0x27.",
    )
    p_probe.add_argument(
        "--interval",
        type=float,
        default=0.2,
        help="Poll interval in seconds (default: 0.2)",
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    {
        "read": cmd_read,
        "set": cmd_set,
        "test": cmd_test,
        "zero": cmd_zero,
        "monitor": cmd_monitor,
        "probe": cmd_probe,
    }[args.command](args)


if __name__ == "__main__":
    main()
