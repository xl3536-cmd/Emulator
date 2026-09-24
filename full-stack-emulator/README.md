# Full Stack Emulator

A modular full-stack emulator built from the Tkinter CV/OV emulator logic and the controller-style backend layering.

It covers four emulator domains:
- RTD ladder-resistor emulation through 74HC595 chain logic
- Ball valve emulation with separate `cv` and `ov` behaviors
- Leak-sensor 0-10V analog output emulation
- Arctic heat pump Modbus RTU register emulation

The backend is structured so bad UI config, missing HAT boards, or missing Python hardware libraries do not crash the app. Those conditions are surfaced in runtime state and the frontend instead.

## Architecture

### Backend layout

`backend/app.py`
- FastAPI entrypoint
- mounts config and runtime routes
- starts/stops the emulator runtime loop

`backend/README.md`
- backend architecture and module documentation map

`backend/src/models`
- `config.py`: Pydantic config models persisted to disk
- `state.py`: Pydantic runtime/state models returned to frontend

`backend/src/config`
- `defaults.py`: default RTD, valve, leak-sensor, and Arctic HP config
- `store.py`: JSON config persistence in `backend/emulator_config.json`

`backend/src/sensors`
- `rtd/`
  - `chain_driver.py`: 74HC595 chain driver with graceful hardware fallback, hardware status, and live frame transmission
  - `frame_utils.py`: RTD frame math, CSV `T1..Tn` parsing, bit-width handling, and temperature/resistance/code conversion
  - `sensor.py`: RTD emulator state, manual/CSV/override output ownership, and board bit control
- `ball_valve/`
  - `cv/sensor.py`: optional VIN/VOUT HAT adapter and continuous target-tracking valve logic
  - `ov/sensor.py`: discrete open/close valve logic
  - `relay_hardware.py`: shared relay detector input and feedback relay output hardware
- `leak_sensor/`
  - `sensor.py`: leak-sensor analog output writes and hardware status
- `arctic_hp/`
  - `register_map.py`: register definitions, bitfields, defaults
  - `emulator.py`: Arctic device state and optional Modbus RTU server

`backend/src/managers`
- `rtd_manager.py`: RTD orchestration and playback timing
- `valve_manager.py`: valve polling, CV/OV state updates, shared relay detector use, and feedback writes
- `leak_sensor_manager.py`: leak-sensor analog output orchestration
- `arctic_hp_manager.py`: Arctic device and server lifecycle
- `emulator_manager.py`: top-level runtime loop and config refresh

`backend/src/services`
- service boundary for config and runtime operations

`backend/src/controllers`
- controller layer between routes and services

`backend/src/routes`
- `config_routes.py`: config read/write endpoints
- `emulator_routes.py`: top-level runtime snapshot endpoint
- `rtd_routes.py`: RTD runtime and playback endpoints
- `valve_routes.py`: valve override endpoint
- `leak_sensor_routes.py`: leak-sensor voltage endpoint
- `arctic_routes.py`: Arctic runtime endpoints

### Frontend layout

`frontend/src/App.jsx`
- app shell, polling, tab switching, API wiring

`frontend/src/components`
- `layout/Shell.jsx`: top shell and tab UI
- `common/Card.jsx`: reusable content card

`frontend/src/features`
- `dashboard/`: live summary page
- `rtd/`: CSV playback + RTD board bit controls
- `valves/`: grouped CV/OV valve status grid
- `leakSensor/`: leak-sensor output controls
- `arcticHp/`: Arctic register editor and server controls
- `config/`: immediate-save config editor

`frontend/src/api/client.js`
- backend HTTP client

## Functionality

### RTD emulator
- editable RTD board count
- editable RTD sensor names
- editable per-board frame position
- editable 5-bit or 8-bit RTD board width
- editable logical stack/channel mapping kept as metadata for naming/layout
- editable resistance range, temperature range, resistance step, and equation override
- optional output temperature override converted into board bits
- invert bits support
- reverse byte order support, defaulted to match the known-good Pi script behavior
- CSV upload from frontend
- CSV only takes over RTD output when a file is loaded and the user presses `Start`
- fast/slow playback modes
- direct manual board control from the card checkboxes
- manual checkbox edits immediately take ownership of the outgoing shift-register frame and stop CSV playback
- per-card estimated resistance and temperature from the current board code
- RTD runtime exposes hardware connection status, hardware error text, output source, board bits, and frame bytes
- runtime frame-byte display

### Ball valve emulator
- valve config saved immediately to JSON
- each valve has separate input stack/channel and output stack/channel
- `cv` and `ov` logic are implemented in separate modules
- `cv` is the primary/default profile
- configurable ramp time, thresholds, and behavior parameters
- software VIN override from frontend for testing without hardware
- bulk config and per-type set-count controls for both `cv` and `ov`
- new valve creation fills the lowest missing valve number instead of always jumping to the historical max
- when a `cv` detector is off, analog feedback is forced to 0V while the card still shows VIN and target/open metrics without stored wording
- missing board / invalid assignment surfaced in UI instead of crashing

### Leak sensor emulator
- configurable leak sensor cards
- each leak sensor drives a configured 0-10V analog output channel
- user-editable voltage commands from frontend
- works in degraded mode if the analog output board is missing

### Arctic HP emulator
- configurable serial port settings
- configurable device metadata and unit IDs
- editable register table from frontend
- bitfield registers included in model/state
- Modbus RTU server attempts to start only if `pymodbus` is available
- offline editing mode still works if `pymodbus` is missing

### Config behavior
- config is persisted to `backend/emulator_config.json`
- frontend config edits save immediately
- runtime managers hot-apply updated config
- invalid hardware conditions should degrade gracefully, not crash backend

## Build And Start

## Backend

From the repository root, open a terminal in the backend directory:

```bash
cd full-stack-emulator/backend
```

Create and activate a virtual environment if needed:

```bash
python3 -m venv .venv
```

Linux/macOS / Raspberry Pi:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip3 install -r requirements.txt
```

If you moved or copied this project from another machine, do not reuse that machine's virtual environment. Create `.venv` on the current machine and install dependencies again.

Start the backend:

```powershell
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Backend URLs:
- API root: `http://localhost:8000/`
- Config API: `http://localhost:8000/api/config`
- Runtime API: `http://localhost:8000/api/runtime`

## Frontend

From the repository root, open another terminal in the frontend directory:

```bash
cd full-stack-emulator/frontend
```

Install dependencies:

```powershell
sudo apt install -y nodejs npm
npm install
```

If this project was copied from Windows to Linux or Raspberry Pi, delete `frontend/node_modules` first and reinstall on the target machine. Reusing a copied `node_modules` directory can leave tools like `vite` without the correct executable permissions.

Start the frontend dev server:

```powershell
npm run dev
```

Default frontend URL:
- `http://localhost:5173`

## Typical startup order

1. Start backend on port `8000`
2. Start frontend on port `5173`
3. Open the frontend in a browser
4. Adjust config if needed
5. Load an RTD CSV, test valve behavior, or start the Arctic server

## Runtime notes

### Hardware libraries
The backend tries to use optional hardware libraries when present:
- `spidev`
- `RPi.GPIO`
- `lib16univin`
- `SM16uout`
- `smbus2` or `smbus`
- `SM16relind`
- `pymodbus`

If those are missing, the backend should still run in degraded mode.

For RTD hardware output on Raspberry Pi, `spidev` and `RPi.GPIO` must be installed in the backend environment. If they are missing, the frontend can still show changing RTD frame bytes while the physical 74HC595 chain remains offline.

### RTD output ownership
- `Manual Bits`: user checkbox edits on the RTD cards directly drive the outgoing shift-register frame
- `CSV Playback`: RTD CSV rows only drive the frame after a CSV has been loaded and the user presses `Start`
- `Config Override`: per-board temperature overrides can generate RTD codes when playback is not active

The RTD page shows which source currently owns the outgoing frame, whether RTD hardware is connected, and whether byte order matches the Pi script-style reversed transmission.

### Generated config file
The backend creates this file automatically on first run if it does not exist:

```text
backend/emulator_config.json
```


## Troubleshooting

### `npm run dev` shows `vite: Permission denied`

This usually means `frontend/node_modules` was copied from a different machine or OS.

From `full-stack-emulator/frontend`, run:

```bash
rm -rf node_modules
npm install
npm run dev
```
