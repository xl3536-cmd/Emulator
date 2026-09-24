# Backend

This backend is a FastAPI runtime for the full-stack hardware emulator. It owns persisted configuration, live runtime state, CSV scheduling, and hardware-facing adapter code for RTD, ball valve, leak sensor, and Arctic heat pump emulator domains.

## Entry Point

`app.py` creates the FastAPI app, installs CORS middleware, mounts all API routers, and starts the emulator runtime loop through `emulator_manager` during application lifespan startup.

Main route groups:

- `/api/config`: read and replace persisted emulator configuration.
- `/api/runtime`: get the complete live runtime snapshot.
- `/api/runtime/rtd`: load/clear CSV data, start/stop playback, and manually set RTD board bits.
- `/api/runtime/valves`: set or clear CV valve input voltage overrides.
- `/api/runtime/leak-sensors`: write configured leak sensor output voltage.
- `/api/runtime/arctic-hp`: start/stop the Arctic Modbus server and edit device registers.

## Runtime Flow

The backend has a deliberately layered request path:

```text
routes -> controllers -> services -> managers -> sensors/hardware adapters
```

The runtime loop is owned by `src/managers/emulator_manager.py`. Every 0.5 seconds it:

1. Ticks ball valve logic so CV and OV states follow detector inputs and feedback timing.
2. Saves persisted CV runtime state when needed.
3. Ticks CSV scheduling so RTD output advances at fast or slow playback speed.

Configuration updates go through `ConfigService`, are validated by Pydantic models, are persisted to `emulator_config.json`, and are hot-applied to managers.

## Persistence

- `emulator_config.json`: full user-editable configuration.
- `emulator_runtime.json`: small persisted runtime state, currently used for CV valve state continuity.

Both files are handled by `src/config`.

## Hardware Boundary

Hardware-specific code lives under `src/sensors`. Managers use those adapters but keep business logic and snapshots centralized. Missing Python hardware libraries or missing boards should degrade into runtime error/status fields instead of crashing the backend.

Ball valve relay detector hardware is shared by CV and OV valves through `src/sensors/ball_valve/relay_hardware.py`. The relay detector data remains part of the valve runtime/config block because the frontend card needs detector status together with valve control state.

## Documentation Map

Each backend package has a local README:

- `src/config/README.md`
- `src/controllers/README.md`
- `src/managers/README.md`
- `src/models/README.md`
- `src/routes/README.md`
- `src/scheduling data/README.md`
- `src/sensors/README.md`
- `src/services/README.md`
- `src/utils/README.md`
