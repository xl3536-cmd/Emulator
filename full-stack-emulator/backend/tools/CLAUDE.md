# CLAUDE.md — backend/tools

Config generation and RTD calibration for the P5-2 full-stack emulator.
Standard library only; nothing here imports the backend's managers or services.

See `DESIGN.md` for why the config is generated rather than authored, and for the
open questions on RTD scaling.

## Files

| file | purpose |
|---|---|
| `build_config_from_excel.py` | spreadsheet (+ optional slot map) → `emulator_config.json` |
| `rtd_slot_calibration.py` | measures which GUI sensor each frame slot drives |
| `rtd_slot_map.csv` | calibration output; `slot,system_sensor` |
| `emulator_config.generated.json` | last generated config, kept for review |
| `emulator_config.generated.review.csv` | flat diffable summary of the above |

## build_config_from_excel.py

Reads `docs/IO Estimates and Assignments P5-2 only smb.xlsx` and emits a complete
`EmulatorConfig`: 44 RTD sensors, 16 CV + 34 OV valves, declared relay detectors,
empty leak sensors, and `arctic_hp` / `ui` inherited from an existing config.

```bash
# preview without writing
python3 tools/build_config_from_excel.py --dry-run

# write the live config (backs up any existing file first)
python3 tools/build_config_from_excel.py

# write elsewhere, inheriting arctic_hp from the live config
python3 tools/build_config_from_excel.py --out tools/emulator_config.generated.json

# apply a measured slot map
python3 tools/build_config_from_excel.py --slot-map tools/rtd_slot_map.csv
```

Options: `--xlsx`, `--slot-map`, `--out`, `--carry-forward`, `--review-csv`,
`--no-backup`, `--dry-run`, `-v`.

Behaviour worth knowing:

- **Validates the spreadsheet, not just parses it.** Every RTD row must satisfy
  `emulator # = stack × 8 + channel`; emulator numbers must be unique and contiguous;
  every OV valve must have exactly one `open` and one `closed` row. Any violation aborts
  with the offending row numbers and exit code 4.
- **Self-checks the output** for duplicate `position`/`board_index`, unclaimed frame slots,
  `board_count` mismatch, and detector addresses referenced by a valve but absent from
  `relay_detectors`.
- **Backs up** the existing `--out` to `<name>.<timestamp>.bak` unless `--no-backup`.
- **Never writes on failure**, and never writes at all under `--dry-run`.
- `arctic_hp` and `ui` are not described by the spreadsheet, so they are inherited from
  `--carry-forward` (default: the live `emulator_config.json`). Only `port.serial_file` is
  overridden, to `/dev/ttyACM0`.

Detector enablement is driven by `ENABLED_DETECTOR_ADDRS` at the top of the script,
currently `{0x23, 0x24, 0x25}` — the addresses `i2cdetect -y 1` finds on this bench. Every
address the spreadsheet names is still written into `relay_detectors`; the others carry
`enabled: false`. **Do not "clean up" by deleting disabled entries**: an address that a
valve references but `relay_detectors` omits gets an implicit *enabled* config and retries
a failing I²C init twice a second forever.

## rtd_slot_calibration.py

Interactive. Requires the backend running and a config whose positions are the identity
map (i.e. generated with no `--slot-map`).

```bash
# spot-check the reversal hypothesis first
python3 tools/rtd_slot_calibration.py --slots 1,44

# full sweep
python3 tools/rtd_slot_calibration.py

# continue an interrupted sweep
python3 tools/rtd_slot_calibration.py --resume
```

Parks every board at its cold end, drives one slot to its hot end, and prompts. At the
prompt: a sensor name records it; `?` marks it unresolved; `r` re-drives; `s` skips;
`q` saves and quits. Rejects names that aren't in the config and names already assigned to
another slot. Saves partial results on interrupt, backend error, or `q`.

Options: `--base-url`, `--config`, `--out`, `--slots`, `--resume`, `-v`.

It warns rather than fails when the backend reports `hardware_available: false` — frame
bytes still change but no board moves, which is useful for testing the script and useless
for calibration.

## Exit codes

`build_config_from_excel.py`: 0 ok, 2 bad arguments, 3 spreadsheet unreadable,
4 spreadsheet or output failed validation, 5 slot map invalid, 6 write failed.

`rtd_slot_calibration.py`: 0 ok, 2 bad arguments, 3 backend unreachable or refused,
4 config unusable for calibration, 6 write failed.

## Do not import the backend's managers or services

`emulator_manager.py` constructs `EmulatorManager()` at module scope, so importing
`src.services.*` or `src.managers.*` triggers `ConfigStore.load()` on the default path and
can rewrite the live `emulator_config.json` as a side effect of the import. When
validating a config by hand, import only `src.config.store` and `src.models.*`.
