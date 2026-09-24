# DESIGN — emulator config generation

## End state

`emulator_config.json` is **generated, not authored**. The P5-2 bench wiring lives in one
reviewable spreadsheet; a deterministic script turns it into the config. Changing the
config means editing the spreadsheet (or the measured slot map) and re-running the
generator — never hand-editing JSON.

```
docs/IO Estimates and Assignments P5-2 only smb.xlsx     <- authoritative wiring record (tracked)
        |
        |   tools/build_config_from_excel.py             <- deterministic generator (tracked)
        |   tools/rtd_slot_map.csv                       <- measured frame-slot mapping (tracked)
        v
backend/emulator_config.json                             <- generated; live runtime state
        |
        |   tools/emulator_config.generated.json         <- last generated output, for review (tracked)
        |   tools/emulator_config.generated.review.csv   <- flat diffable summary (tracked)
```

### Why generation rather than the UI

The previous config was hand-entered through the frontend, gitignored, and existed in
exactly one place. When a schema change made `ConfigStore.load()` normalize and re-save
it, the hand-entered calibration data was destroyed with no backup. The spreadsheet was
the only surviving record of the wiring.

Generation fixes the class of problem, not the instance:

- the input is a tracked artifact that survives branch switches and machine loss
- the output is reproducible — regenerating recovers from any config loss in seconds
- the mapping is code-reviewable as a diff (`emulator_config.generated.review.csv`)
- the generator refuses to emit a config that the backend would silently rewrite

## What the generator derives

| config area | source | rule |
|---|---|---|
| 44 RTD sensors | `RTD Channel Assignments` | `emulator RTD # = stack × 8 + channel`, validated on every row |
| `sensor_name` | column C | the system tag (`T1`…`T40`, `T37C`…`T40C`) that must match the P5-22 GUI |
| `board_index` | derived | `emulator # − 1` |
| `position` | `tools/rtd_slot_map.csv` | measured frame slot; identity map when absent |
| 16 CV valves | `Ball Valve…` | `input_channel` / `output_channel` from Emulator AD in / AD out |
| 34 OV valves | `Ball Valve…` | detectors and feedback relays from the paired open/closed rows |
| `relay_detectors` | detector column | address = `0x20 + group`; enabled only for addresses on the bus |

RTD scaling (resistance range, temperature range, step) is **not** in the spreadsheet and
is hard-coded in `RTD_DEFAULTS`. See open questions.

## Design decisions

**Standard library only.** The `.xlsx` reader in `build_config_from_excel.py` is a ~70-line
zip + XML parser rather than an `openpyxl` dependency, so the generator runs on the Pi
without adding anything to `requirements.txt`. Its output was verified cell-for-cell
against `openpyxl` across 5,486 cells of both sheets: zero mismatches.

**Post-migration shape is emitted directly.** `ConfigStore.load()` re-saves the file
whenever `model_dump(mode="json")` differs from what was on disk. Emitting the already-
normalized shape is what stops the config churning on every boot — the same mechanism
that destroyed the original. Verified: loading the generated config through the real
`ConfigStore` leaves the file byte-identical.

**Detectors are declared, then disabled.** Every detector address the spreadsheet names
appears in `relay_detectors`; only addresses that answer on the bus have `enabled: true`.
Two reasons over the alternative of setting `i2c_address: null`:

1. the spreadsheet's wiring stays documented in the config, so re-enabling a board as it
   gets wired is a one-boolean edit
2. an *omitted* address is worse than a disabled one — the hardware adapter fabricates an
   **enabled** config for any address a valve references, then retries a failing init
   twice a second forever with no backoff

`relay_detectors: []` therefore does not silence anything. This is the single most
counter-intuitive property of the config format.

**Self-check before writing.** The generator refuses to emit a config with duplicate
`position` or `board_index` values, unclaimed frame slots (which transmit `0x00`), a
`board_count` inconsistent with the sensor list, or a detector address referenced by a
valve but missing from `relay_detectors`.

**Backup on write.** Any existing output is copied to `<name>.<timestamp>.bak` first. The
backend has no such guard; the tool does.

## Calibration

`position` is the frame slot a sensor occupies, and it is the only field that cannot be
derived from the spreadsheet — the physical daisy-chain order is a property of the wiring.
`rtd_slot_calibration.py` measures it: all boards are parked cold, one slot at a time is
driven hot, and the operator records which GUI sensor moved.

Previously observed mapping data should not be reused. It was measured with
`board_count: 24` against a 44-board chain, so every slot past 24 was reading stale
shifted data. Slots 1–8 decoded as stack 2 in exact descending channel order — a plain
frame reversal — and the apparent randomness began exactly where the 24-byte frame ran
out. Re-measure with a 44-board config before trusting any of it.

## Trap: never import the managers to validate a config

`emulator_manager.py` instantiates `EmulatorManager()` at **module scope**, so importing
anything under `src.services` or `src.managers` runs `ConfigStore.load()` against the
default path and can rewrite the live `emulator_config.json` as an import side effect.
This was observed in practice during development of these tools.

Validate with the models only:

```python
import sys; sys.path.insert(0, ".")
from src.config.store import ConfigStore          # safe
from src.models.config import EmulatorConfig      # safe
# from src.services.config_service import ...     # NOT safe: rewrites the live config
```

## Open questions

**RTD scaling is an assumption.** `RTD_DEFAULTS` uses 95–150 Ω over −10–80 °C with a 2 Ω
step. The spreadsheet contains no calibration data. This yields 28 usable codes and about
2 °C of resolution.

**The linear equation is not a PT100 curve.** `frame_utils.default_equation` fits
`T = a·R + b` through the range endpoints. A real PT100 reads ~100 Ω at 0 °C and ~131 Ω at
80 °C, so mapping 95–150 Ω linearly onto −10–80 °C will be wrong by tens of degrees
mid-range **if the P5-22 converts resistance with a standard RTD curve**. Confirm what the
controller expects before trusting emulated temperatures. If a curve is needed, the
`use_custom_equation` / `custom_equation_a` / `custom_equation_b` fields only provide
another linear fit — a true curve needs a code change.

**`bit_width: 8` buys no resolution on its own.** Reachable resistance is
`max_res − code × step`, so with a 2 Ω step only codes 0–27 land inside a 55 Ω span; codes
28–255 all clamp. An 8-bit board needs `res_step_ohms` cut by roughly 8× to be worth
anything. Nothing in the backend derives or validates this coupling.

**Fluid level sensors are not emulatable.** LD1/LD2 and SW1–SW11 have no emulator AD-out
assignment in the spreadsheet.

**Leak sensors are out of scope** and emitted as `{"sensors": []}`, which also means the
leak-sensor adapter opens no hardware boards.

**Disabled OV valves still perform relay-output I/O.** `ValveManager._tick_ov_valve`
writes both feedback relays on the first tick and no config field prevents it, so
`SM16relind` errors may appear for OV valves whose HAT is absent. Suppressing that
requires a backend change.
