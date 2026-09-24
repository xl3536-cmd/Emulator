#!/usr/bin/env python3
"""
Generate emulator_config.json from the P5-2 IO Estimates spreadsheet.

The spreadsheet is the authoritative record of the bench wiring; this script is
the only supported way to produce emulator_config.json from it. Regenerating is
how the config changes -- do not hand-edit the output, edit the spreadsheet (or
the slot map) and re-run.

Sources
-------
docs/IO Estimates and Assignments P5-2 only smb.xlsx
  "RTD Channel Assignments"          -> 44 RTD boards
  "Ball Valve, Fluid Level Stack C"  -> 34 OV + 16 CV valves, relay detectors

tools/rtd_slot_map.csv (optional)
  slot,system_sensor -- measured mapping from shift-register frame slot to the
  sensor that actually responds on the P5-22 GUI. Sets each sensor's `position`.
  Without it, positions are the identity map (position = emulator RTD number),
  which is what you want for the first calibration run.

Dependencies
------------
Standard library only. The .xlsx reader below is deliberately minimal so this
runs on the Pi without adding openpyxl to the backend environment.

Exit codes
----------
0 success   2 bad arguments   3 spreadsheet unreadable
4 spreadsheet data failed validation   5 slot map invalid   6 write failed
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

LOG = logging.getLogger("build_config_from_excel")

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

RTD_SHEET = "RTD Channel Assignments"
VALVE_SHEET = "Ball Valve, Fluid Level Stack C"

# 1-based spreadsheet columns. Both sheets put the record name in column C.
RTD_COL = {"tag": 3, "channel_name": 5, "stack": 6, "channel": 7, "emulator": 8}
RTD_ROWS = (6, 70)

VALVE_COL = {
    "tag": 3,
    "open_closed": 4,
    "emu_adin_stack": 12,
    "emu_adin_channel": 13,
    "emu_adout_stack": 14,
    "emu_adout_channel": 15,
    "emu_fb_ssr_stack": 16,
    "emu_fb_ssr_channel": 17,
    "detector_group": 18,
    "detector_channel": 19,
    "unique_id": 20,
}
VALVE_ROWS = (17, 110)

# MCP23017 base address. The spreadsheet's detector column is written as an
# offset from this ("0x20" for the first block, then bare 1..5).
DETECTOR_BASE_ADDR = 0x20

# Detector addresses whose MCP23017 answers on the bus. Everything else is
# written into the config but left disabled, so no I2C traffic is attempted.
# Verified with `i2cdetect -y 1`: 0x23/0x24/0x25 present, 0x20/0x21/0x22 absent.
ENABLED_DETECTOR_ADDRS = {0x23, 0x24, 0x25}

# RTD scaling. Not in the spreadsheet -- see tools/DESIGN.md "Open questions".
RTD_DEFAULTS = {
    "bit_width": 5,
    "min_res_ohms": 95.0,
    "max_res_ohms": 150.0,
    "temp_min_c": -10.0,
    "temp_max_c": 80.0,
    "res_step_ohms": 2.0,
}

ARCTIC_SERIAL_FILE = "/dev/ttyACM0"


class SpreadsheetError(RuntimeError):
    """Raised when the workbook cannot be read at all."""


class ValidationError(RuntimeError):
    """Raised when the workbook parses but its contents fail a sanity check."""


# --------------------------------------------------------------------------
# Minimal .xlsx reader
# --------------------------------------------------------------------------

def _column_index(ref: str) -> int:
    """'AB12' -> 28. Letters are base-26 with A=1."""
    index = 0
    for char in ref:
        if not char.isalpha():
            break
        index = index * 26 + (ord(char.upper()) - ord("A") + 1)
    return index


def _row_index(ref: str) -> int:
    digits = "".join(char for char in ref if char.isdigit())
    return int(digits) if digits else 0


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    strings: list[str] = []
    for item in ET.fromstring(raw).findall(f"{NS_MAIN}si"):
        # A shared string may be split across several runs; concatenate them.
        strings.append("".join(node.text or "" for node in item.iter(f"{NS_MAIN}t")))
    return strings


def _worksheet_path(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rel_id = None
    available = []
    for sheet in workbook.iter(f"{NS_MAIN}sheet"):
        name = sheet.get("name", "")
        available.append(name)
        if name == sheet_name:
            rel_id = sheet.get(f"{NS_DOC_REL}id")
    if rel_id is None:
        raise SpreadsheetError(
            f"sheet {sheet_name!r} not found; workbook contains {available}"
        )

    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.iter(f"{NS_PKG_REL}Relationship"):
        if rel.get("Id") == rel_id:
            target = rel.get("Target", "")
            return target[1:] if target.startswith("/") else f"xl/{target}"
    raise SpreadsheetError(f"relationship {rel_id!r} for sheet {sheet_name!r} is missing")


def read_sheet(xlsx_path: Path, sheet_name: str) -> dict[tuple[int, int], object]:
    """Return {(row, column): value} for one worksheet, 1-based indices.

    Cached formula results are used, matching openpyxl's data_only=True.
    """
    try:
        with zipfile.ZipFile(xlsx_path) as archive:
            strings = _shared_strings(archive)
            sheet_xml = archive.read(_worksheet_path(archive, sheet_name))
    except SpreadsheetError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise SpreadsheetError(f"cannot read {xlsx_path}: {exc}") from exc

    grid: dict[tuple[int, int], object] = {}
    for cell in ET.fromstring(sheet_xml).iter(f"{NS_MAIN}c"):
        ref = cell.get("r") or ""
        row, column = _row_index(ref), _column_index(ref)
        if not row or not column:
            continue
        cell_type = cell.get("t")
        if cell_type == "inlineStr":
            node = cell.find(f"{NS_MAIN}is")
            value = "".join(t.text or "" for t in node.iter(f"{NS_MAIN}t")) if node is not None else None
        else:
            value_node = cell.find(f"{NS_MAIN}v")
            raw = value_node.text if value_node is not None else None
            if raw is None:
                value = None
            elif cell_type == "s":
                try:
                    value = strings[int(raw)]
                except (ValueError, IndexError):
                    LOG.warning("cell %s references unknown shared string %r", ref, raw)
                    value = None
            elif cell_type == "b":
                value = raw == "1"
            else:
                value = raw
        if value is not None and str(value).strip() != "":
            grid[(row, column)] = value
    LOG.debug("read %d populated cells from %r", len(grid), sheet_name)
    return grid


def _text(grid, row: int, column: int) -> str:
    value = grid.get((row, column))
    return "" if value is None else str(value).strip()


def _int(grid, row: int, column: int):
    """Ints tolerant of Excel's float storage ('4.0') and hex ('0x20')."""
    raw = _text(grid, row, column)
    if not raw:
        return None
    if raw.lower().startswith("0x"):
        try:
            return int(raw, 16)
        except ValueError:
            return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _detector_group(grid, row: int, column: int):
    """Normalise the detector column to an offset from DETECTOR_BASE_ADDR."""
    raw = _text(grid, row, column)
    if not raw:
        return None
    value = _int(grid, row, column)
    if value is None:
        LOG.warning("row %d: unparseable detector value %r", row, raw)
        return None
    # Written either as a full address (0x20..0x27) or as a bare group number.
    return value - DETECTOR_BASE_ADDR if value >= DETECTOR_BASE_ADDR else value


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def extract_rtd(xlsx_path: Path) -> list[dict]:
    grid = read_sheet(xlsx_path, RTD_SHEET)
    sensors: list[dict] = []
    first, last = RTD_ROWS
    for row in range(first, last + 1):
        tag = _text(grid, row, RTD_COL["tag"])
        if not re.fullmatch(r"T\d+C?", tag):
            continue
        emulator = _int(grid, row, RTD_COL["emulator"])
        if emulator is None:
            LOG.debug("row %d: sensor %s has no emulator number, skipping", row, tag)
            continue
        sensors.append(
            {
                "row": row,
                "tag": tag,
                "stack": _int(grid, row, RTD_COL["stack"]),
                "channel": _int(grid, row, RTD_COL["channel"]),
                "emulator": emulator,
                "channel_name": _text(grid, row, RTD_COL["channel_name"]),
            }
        )

    if not sensors:
        raise ValidationError(f"no RTD rows matched in {RTD_SHEET!r}")

    problems: list[str] = []
    for sensor in sensors:
        stack, channel, emulator = sensor["stack"], sensor["channel"], sensor["emulator"]
        if stack is None or channel is None:
            problems.append(f"row {sensor['row']} ({sensor['tag']}): missing stack/channel")
        elif emulator != stack * 8 + channel:
            problems.append(
                f"row {sensor['row']} ({sensor['tag']}): emulator #{emulator} "
                f"!= stack {stack} * 8 + channel {channel}"
            )

    for field in ("tag", "emulator"):
        seen: dict[object, int] = {}
        for sensor in sensors:
            if sensor[field] in seen:
                problems.append(
                    f"duplicate {field} {sensor[field]!r} on rows "
                    f"{seen[sensor[field]]} and {sensor['row']}"
                )
            seen[sensor[field]] = sensor["row"]

    expected = set(range(1, len(sensors) + 1))
    missing = sorted(expected - {s["emulator"] for s in sensors})
    if missing:
        problems.append(f"emulator numbers are not contiguous; missing {missing}")

    if problems:
        raise ValidationError("RTD sheet failed validation:\n  - " + "\n  - ".join(problems))

    sensors.sort(key=lambda s: s["emulator"])
    LOG.info("extracted %d RTD sensors (emulator #%d..#%d)",
             len(sensors), sensors[0]["emulator"], sensors[-1]["emulator"])
    return sensors


def extract_valves(xlsx_path: Path) -> tuple[list[dict], list[dict]]:
    grid = read_sheet(xlsx_path, VALVE_SHEET)
    records: list[dict] = []
    first, last = VALVE_ROWS
    for row in range(first, last + 1):
        tag = _text(grid, row, VALVE_COL["tag"])
        if not re.fullmatch(r"(OV|CV)\d+", tag):
            continue
        records.append(
            {
                "row": row,
                "tag": tag,
                "kind": tag[:2],
                "number": int(tag[2:]),
                "open_closed": _text(grid, row, VALVE_COL["open_closed"]).lower(),
                "adin_stack": _int(grid, row, VALVE_COL["emu_adin_stack"]),
                "adin_channel": _int(grid, row, VALVE_COL["emu_adin_channel"]),
                "adout_stack": _int(grid, row, VALVE_COL["emu_adout_stack"]),
                "adout_channel": _int(grid, row, VALVE_COL["emu_adout_channel"]),
                "fb_stack": _int(grid, row, VALVE_COL["emu_fb_ssr_stack"]),
                "fb_channel": _int(grid, row, VALVE_COL["emu_fb_ssr_channel"]),
                "detector_group": _detector_group(grid, row, VALVE_COL["detector_group"]),
                "detector_channel": _int(grid, row, VALVE_COL["detector_channel"]),
                "unique_id": _text(grid, row, VALVE_COL["unique_id"]),
            }
        )

    if not records:
        raise ValidationError(f"no valve rows matched in {VALVE_SHEET!r}")

    problems: list[str] = []
    cv_records: list[dict] = []
    ov_by_tag: dict[str, dict[str, dict]] = {}

    for record in records:
        if record["kind"] == "CV":
            cv_records.append(record)
            continue
        slot = record["open_closed"]
        if slot not in ("open", "closed"):
            problems.append(
                f"row {record['row']} ({record['tag']}): expected 'open' or 'closed' "
                f"in column D, found {record['open_closed']!r}"
            )
            continue
        bucket = ov_by_tag.setdefault(record["tag"], {})
        if slot in bucket:
            problems.append(f"{record['tag']}: duplicate '{slot}' row {record['row']}")
        bucket[slot] = record

    for tag, bucket in ov_by_tag.items():
        for slot in ("open", "closed"):
            if slot not in bucket:
                problems.append(f"{tag}: missing '{slot}' row")

    seen_cv: dict[str, int] = {}
    for record in cv_records:
        if record["tag"] in seen_cv:
            problems.append(
                f"duplicate {record['tag']} on rows {seen_cv[record['tag']]} and {record['row']}"
            )
        seen_cv[record["tag"]] = record["row"]

    if problems:
        raise ValidationError("valve sheet failed validation:\n  - " + "\n  - ".join(problems))

    cv_records.sort(key=lambda r: r["number"])
    ov_records = [ov_by_tag[tag] for tag in sorted(ov_by_tag, key=lambda t: int(t[2:]))]
    LOG.info("extracted %d CV and %d OV valves", len(cv_records), len(ov_records))
    return cv_records, ov_records


# --------------------------------------------------------------------------
# Slot map
# --------------------------------------------------------------------------

def load_slot_map(path: Path, sensors: list[dict]) -> dict[str, int]:
    """Read slot,system_sensor CSV -> {sensor_tag: frame_slot}."""
    known = {sensor["tag"] for sensor in sensors}
    mapping: dict[str, int] = {}
    slots_seen: dict[int, str] = {}
    problems: list[str] = []

    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for line_no, row in enumerate(csv.DictReader(handle), start=2):
                raw_slot = (row.get("slot") or "").strip()
                sensor = (row.get("system_sensor") or "").strip()
                if not raw_slot and not sensor:
                    continue
                try:
                    slot = int(float(raw_slot))
                except ValueError:
                    problems.append(f"line {line_no}: slot {raw_slot!r} is not a number")
                    continue
                if not 1 <= slot <= len(sensors):
                    problems.append(f"line {line_no}: slot {slot} outside 1..{len(sensors)}")
                    continue
                if sensor not in known:
                    problems.append(f"line {line_no}: {sensor!r} is not a sensor in the spreadsheet")
                    continue
                if slot in slots_seen:
                    problems.append(f"line {line_no}: slot {slot} already assigned to {slots_seen[slot]}")
                    continue
                if sensor in mapping:
                    problems.append(f"line {line_no}: {sensor} already assigned to slot {mapping[sensor]}")
                    continue
                slots_seen[slot] = sensor
                mapping[sensor] = slot
    except OSError as exc:
        raise ValidationError(f"cannot read slot map {path}: {exc}") from exc

    unmapped = sorted(known - set(mapping), key=lambda t: (len(t), t))
    if unmapped:
        problems.append(f"{len(unmapped)} sensors have no slot: {unmapped}")

    if problems:
        raise ValidationError("slot map failed validation:\n  - " + "\n  - ".join(problems))

    LOG.info("loaded slot map for %d sensors from %s", len(mapping), path)
    return mapping


# --------------------------------------------------------------------------
# Config assembly
# --------------------------------------------------------------------------

def build_rtd(sensors: list[dict], slot_map: dict[str, int] | None) -> dict:
    entries = []
    for sensor in sensors:
        position = slot_map[sensor["tag"]] if slot_map else sensor["emulator"]
        entries.append(
            {
                "sensor_name": sensor["tag"],
                "board_index": sensor["emulator"] - 1,
                "position": position,
                "bit_width": RTD_DEFAULTS["bit_width"],
                "logical_stack": sensor["stack"],
                "logical_channel": sensor["channel"],
                "min_res_ohms": RTD_DEFAULTS["min_res_ohms"],
                "max_res_ohms": RTD_DEFAULTS["max_res_ohms"],
                "temp_min_c": RTD_DEFAULTS["temp_min_c"],
                "temp_max_c": RTD_DEFAULTS["temp_max_c"],
                "res_step_ohms": RTD_DEFAULTS["res_step_ohms"],
                "use_custom_equation": False,
                "custom_equation_a": None,
                "custom_equation_b": None,
                "output_temp_c": None,
            }
        )
    return {
        "board_count": len(entries),
        "invert_bits": False,
        # True is the model default and matches the known-good standalone Pi
        # script: the last-positioned board is clocked out first.
        "reverse_byte_order": True,
        "playback": {
            "fast_interval_seconds": 1.0,
            "slow_interval_seconds": 60.0,
            "loop": True,
        },
        "sensors": entries,
    }


def _detector_ref(group, channel):
    """A DetectorChannelConfig. i2c_address None means 'never touch the bus'."""
    address = None if group is None else DETECTOR_BASE_ADDR + group
    return {"i2c_address": address, "channel": channel if channel else 1}


def build_valves(cv_records: list[dict], ov_records: list[dict]) -> dict:
    ball_valves: list[dict] = []
    groups_used: set[int] = set()

    for record in cv_records:
        if record["detector_group"] is not None:
            groups_used.add(record["detector_group"])
        name = record["unique_id"] or f"CV Valve {record['number']}"
        ball_valves.append(
            {
                "id": record["tag"],
                "name": name,
                "enabled": True,
                "profile_type": "cv",
                # Written explicitly on every CV valve: the model's
                # default_factory for this field cannot succeed, because
                # DetectorChannelConfig.channel has no default.
                "relay_detector": _detector_ref(record["detector_group"], record["detector_channel"]),
                "input_channel": {
                    "stack": record["adin_stack"] or 0,
                    "channel": record["adin_channel"] or 0,
                },
                "output_channel": {
                    "stack": record["adout_stack"] or 0,
                    "channel": record["adout_channel"] or 0,
                },
                "behavior": {
                    "ramp_seconds": 90.0,
                    "v_min": 2.0,
                    "v_max": 10.0,
                    "cmd_threshold": 1.9,
                    "target_deadband": 0.05,
                },
            }
        )

    for bucket in ov_records:
        opened, closed = bucket["open"], bucket["closed"]
        for record in (opened, closed):
            if record["detector_group"] is not None:
                groups_used.add(record["detector_group"])
        name = closed["unique_id"] or opened["unique_id"] or f"OV Valve {opened['number']}"
        ball_valves.append(
            {
                "id": opened["tag"],
                "name": name,
                "enabled": True,
                "profile_type": "ov",
                "open_detector": _detector_ref(opened["detector_group"], opened["detector_channel"]),
                "close_detector": _detector_ref(closed["detector_group"], closed["detector_channel"]),
                # Feedback rows are crossed relative to the spreadsheet labels.
                # Measured on the bench 2026-09-04: with open_feedback taken from
                # the "open" row, every valve the emulator reported open showed
                # closed on the controller GUI, and vice versa. The emulator's
                # open relay is physically wired to the controller's confirm-closed
                # input, so open_feedback takes the "closed" row's channel.
                # `feedback_open_active` is asserted when position == "open"
                # (ov/sensor.py), so the inversion is purely in this assignment.
                "open_feedback": {
                    "stack": closed["fb_stack"] or 0,
                    "channel": closed["fb_channel"] or 1,
                },
                "close_feedback": {
                    "stack": opened["fb_stack"] or 0,
                    "channel": opened["fb_channel"] or 1,
                },
                "behavior": {
                    "detector_delay_seconds": 3.0,
                    "feedback_hold_seconds": 1.0,
                    "default_position": "open",
                },
            }
        )

    # An explicit entry per address is what suppresses I2C traffic. An empty
    # relay_detectors list does NOT work: the hardware adapter fabricates an
    # *enabled* config for any address a valve names, then retries a failing
    # init twice a second forever.
    relay_detectors = []
    for group in sorted(groups_used):
        address = DETECTOR_BASE_ADDR + group
        relay_detectors.append(
            {
                "i2c_address": address,
                "i2c_bus": 1,
                # Measured 2026-09-04 with both flags false: 0x23 and 0x24 both
                # read GPIOA=0x00, GPIOB=0x0E, byte-identical across two chips
                # and unchanged while valves were commanded. Undriven inputs.
                # Pull-ups give every pin a defined idle high; active_low then
                # reads the controller's contact-closure-to-ground as asserted,
                # which the rising-edge detection in ov/sensor.py needs to fire.
                # If idle instead reads all-asserted, the SSRs source rather
                # than sink -- set active_low False and keep the pull-ups on.
                "active_low": True,
                "use_internal_pullups": True,
                "enabled": address in ENABLED_DETECTOR_ADDRS,
            }
        )

    return {
        "ball_valves": ball_valves,
        "relay_detectors": relay_detectors,
        "relay_output_i2c_bus": 1,
    }


def build_arctic(previous: dict | None) -> dict:
    """Carry the Arctic block forward; only the serial port is corrected."""
    if previous and previous.get("devices"):
        arctic = json.loads(json.dumps(previous))
        arctic.setdefault("port", {})
        arctic["port"]["serial_file"] = ARCTIC_SERIAL_FILE
        LOG.info("carried %d Arctic device(s) forward from the existing config",
                 len(arctic["devices"]))
        return arctic
    LOG.warning("no existing Arctic devices found; emitting an empty device list")
    return {
        "port": {
            "serial_file": ARCTIC_SERIAL_FILE,
            "timeout": 1.5,
            "baudrate": 2400,
            "bytesize": 8,
            "parity": "E",
            "stopbits": 1,
        },
        "devices": [],
    }


def build_config(xlsx_path: Path, slot_map_path: Path | None, previous: dict | None) -> dict:
    sensors = extract_rtd(xlsx_path)
    cv_records, ov_records = extract_valves(xlsx_path)
    slot_map = load_slot_map(slot_map_path, sensors) if slot_map_path else None
    if slot_map is None:
        LOG.warning("no slot map supplied: positions are the identity map "
                    "(position = emulator RTD number). Calibrate before trusting "
                    "which GUI sensor a board drives.")

    previous_arctic = (previous or {}).get("arctic_hp")
    previous_ui = (previous or {}).get("ui")

    return {
        "rtd": build_rtd(sensors, slot_map),
        "valves": build_valves(cv_records, ov_records),
        # Out of scope. An empty list also means the leak-sensor adapter opens
        # no hardware boards, but the key itself is required by the model.
        "leak_sensors": {"sensors": []},
        "arctic_hp": build_arctic(previous_arctic),
        "ui": previous_ui if isinstance(previous_ui, dict) else {},
    }


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def self_check(config: dict) -> list[str]:
    """Catch the mistakes that make the backend silently rewrite or misdrive."""
    problems: list[str] = []
    rtd = config["rtd"]
    sensors = rtd["sensors"]

    positions = [s["position"] for s in sensors]
    indices = [s["board_index"] for s in sensors]
    if len(set(positions)) != len(positions):
        problems.append("duplicate `position` values (the model rejects these)")
    if len(set(indices)) != len(indices):
        problems.append("duplicate `board_index` values (the model rejects these)")
    unclaimed = sorted(set(range(1, rtd["board_count"] + 1)) - set(positions))
    if unclaimed:
        problems.append(f"frame slots claimed by no sensor (they transmit 0x00): {unclaimed}")
    if rtd["board_count"] != len(sensors):
        problems.append(f"board_count {rtd['board_count']} != {len(sensors)} sensors")

    referenced = set()
    for valve in config["valves"]["ball_valves"]:
        keys = ("relay_detector",) if valve["profile_type"] == "cv" else ("open_detector", "close_detector")
        for key in keys:
            address = valve[key]["i2c_address"]
            if address is not None:
                referenced.add(address)
    declared = {d["i2c_address"] for d in config["valves"]["relay_detectors"]}
    orphans = sorted(referenced - declared)
    if orphans:
        problems.append(
            "detector addresses referenced by valves but absent from relay_detectors "
            f"(they get implicit ENABLED configs and will retry forever): {[hex(a) for a in orphans]}"
        )
    return problems


def write_review_csv(path: Path, config: dict) -> None:
    """Human-reviewable flat dump of what went into the config."""
    rows = [
        {
            "kind": "rtd",
            "id": s["sensor_name"],
            "board_index": s["board_index"],
            "position": s["position"],
            "stack": s["logical_stack"],
            "channel": s["logical_channel"],
            "detail": f"{s['min_res_ohms']}-{s['max_res_ohms']}ohm "
                      f"{s['temp_min_c']}-{s['temp_max_c']}C step {s['res_step_ohms']} "
                      f"{s['bit_width']}-bit",
            "detector": "",
            "enabled": "",
        }
        for s in config["rtd"]["sensors"]
    ]
    enabled_addrs = {d["i2c_address"] for d in config["valves"]["relay_detectors"] if d["enabled"]}
    for valve in config["valves"]["ball_valves"]:
        if valve["profile_type"] == "cv":
            detectors = [valve["relay_detector"]]
            detail = (f"in stack {valve['input_channel']['stack']} ch {valve['input_channel']['channel']} / "
                      f"out stack {valve['output_channel']['stack']} ch {valve['output_channel']['channel']}")
        else:
            detectors = [valve["open_detector"], valve["close_detector"]]
            detail = (f"open fb stack {valve['open_feedback']['stack']} ch {valve['open_feedback']['channel']} / "
                      f"close fb stack {valve['close_feedback']['stack']} ch {valve['close_feedback']['channel']}")
        addresses = {d["i2c_address"] for d in detectors if d["i2c_address"] is not None}
        rows.append(
            {
                "kind": valve["profile_type"],
                "id": valve["id"],
                "board_index": "",
                "position": "",
                "stack": "",
                "channel": "",
                "detail": detail,
                "detector": " ".join(
                    f"{hex(d['i2c_address']) if d['i2c_address'] is not None else 'none'}:{d['channel']}"
                    for d in detectors
                ),
                "enabled": "yes" if addresses and addresses <= enabled_addrs else "no",
            }
        )

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    LOG.info("wrote review table %s (%d rows)", path, len(rows))


def main(argv: list[str] | None = None) -> int:
    repo_backend = Path(__file__).resolve().parents[1]
    repo_root = repo_backend.parents[1]

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xlsx", type=Path,
                        default=repo_root / "docs" / "IO Estimates and Assignments P5-2 only smb.xlsx",
                        help="source spreadsheet")
    parser.add_argument("--slot-map", type=Path, default=None,
                        help="calibration CSV (slot,system_sensor); omit for the identity map")
    parser.add_argument("--out", type=Path, default=repo_backend / "emulator_config.json",
                        help="config to write")
    parser.add_argument("--carry-forward", type=Path, default=repo_backend / "emulator_config.json",
                        help="existing config to inherit arctic_hp and ui from "
                             "(the spreadsheet does not describe either); falls back to --out")
    parser.add_argument("--review-csv", type=Path, default=None,
                        help="also write a flat review table (default: alongside --out)")
    parser.add_argument("--no-backup", action="store_true",
                        help="skip the timestamped .bak copy of an existing --out")
    parser.add_argument("--dry-run", action="store_true", help="validate and report, write nothing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    if not args.xlsx.is_file():
        LOG.error("spreadsheet not found: %s", args.xlsx)
        return 2
    if args.slot_map is not None and not args.slot_map.is_file():
        LOG.error("slot map not found: %s", args.slot_map)
        return 2

    previous = None
    carry_source = args.carry_forward if args.carry_forward.is_file() else args.out
    if carry_source.is_file():
        try:
            previous = json.loads(carry_source.read_text(encoding="utf-8"))
            LOG.info("inheriting arctic_hp and ui from %s", carry_source)
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning("%s is unreadable (%s); Arctic devices will be empty", carry_source, exc)
    else:
        LOG.warning("no config found at %s or %s to inherit arctic_hp from",
                    args.carry_forward, args.out)

    try:
        config = build_config(args.xlsx, args.slot_map, previous)
    except SpreadsheetError as exc:
        LOG.error("%s", exc)
        return 3
    except ValidationError as exc:
        LOG.error("%s", exc)
        return 5 if args.slot_map and "slot map" in str(exc) else 4

    problems = self_check(config)
    if problems:
        LOG.error("generated config failed self-check:\n  - %s", "\n  - ".join(problems))
        return 4

    rtd_count = len(config["rtd"]["sensors"])
    valves = config["valves"]["ball_valves"]
    cv_count = sum(1 for v in valves if v["profile_type"] == "cv")
    enabled = [hex(d["i2c_address"]) for d in config["valves"]["relay_detectors"] if d["enabled"]]
    disabled = [hex(d["i2c_address"]) for d in config["valves"]["relay_detectors"] if not d["enabled"]]
    LOG.info("built config: %d RTD boards, %d CV + %d OV valves", rtd_count, cv_count, len(valves) - cv_count)
    LOG.info("detectors enabled %s / disabled %s", enabled or "none", disabled or "none")

    if args.dry_run:
        LOG.info("dry run: nothing written")
        return 0

    try:
        if args.out.is_file() and not args.no_backup:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = args.out.with_suffix(f".{stamp}.bak")
            shutil.copy2(args.out, backup)
            LOG.info("backed up existing config to %s", backup)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        LOG.info("wrote %s", args.out)
        write_review_csv(args.review_csv or args.out.with_suffix(".review.csv"), config)
    except OSError as exc:
        LOG.error("write failed: %s", exc)
        return 6

    return 0


if __name__ == "__main__":
    sys.exit(main())
