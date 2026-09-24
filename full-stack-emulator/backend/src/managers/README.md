# Managers

Managers own runtime orchestration. They hold live state, coordinate hardware adapters, apply config changes, and produce snapshots for the frontend.

## Files

- `emulator_manager.py`: top-level runtime owner. Loads config, creates domain managers, starts/stops the loop, applies config refreshes, and assembles the full runtime snapshot.
- `rtd_manager.py`: wraps the RTD emulator sensor, applies manual board writes, CSV rows, and snapshot generation.
- `scheduling_manager.py`: owns CSV playback state, column matching, row timing, RTD code application, and valve-transition slow-mode detection.
- `valve_manager.py`: owns CV/OV valve state machines, reads shared relay detectors, writes analog/relay outputs, validates runtime hardware status, and persists CV runtime state.
- `leak_sensor_manager.py`: owns leak sensor output channel state and writes configured voltages to analog output hardware.
- `arctic_hp_manager.py`: owns Arctic device register state and optional Modbus server lifecycle.

## Runtime Loop

`EmulatorManager._run_loop()` is the central tick:

1. `valve_manager.tick()` polls relay detector and analog input state, updates CV/OV state, and writes outputs.
2. Runtime state is persisted when CV valve state changes.
3. `scheduling_manager.tick()` advances CSV playback. It slows playback when valve transitions are pending or when valve runtime logic is actively moving.

## Config Refresh

`EmulatorManager.refresh_config()` saves the new config and hot-applies domain slices to managers:

- RTD config goes to `RTDManager`.
- Valve config goes to `ValveManager` and `SchedulingManager`.
- Leak sensor config goes to `LeakSensorManager`.
- Arctic config goes to `ArcticHPManager`.

The goal is that frontend config edits take effect without restarting the backend.

## Hardware Separation

Managers should call sensor/hardware adapters; they should not import low-level board libraries directly. This keeps hardware failures local to sensor adapters and makes runtime snapshots the place where errors are surfaced.
