# Config

The `config` package owns disk persistence and default construction for backend configuration and selected runtime state.

## Files

- `defaults.py`: builds a complete default `EmulatorConfig` for first startup.
- `store.py`: loads, migrates, validates, and saves `backend/emulator_config.json`.
- `runtime_store.py`: loads and saves `backend/emulator_runtime.json`.

## Config Goals

Configuration should describe user intent, not live hardware health. Examples include RTD board count, valve channel assignments, relay detector addresses, leak sensor output channels, and Arctic device metadata.

Managers apply this config to hardware adapters and runtime state. If a configured board or dependency is missing, the backend should report that condition in runtime status rather than rejecting otherwise valid saved config.

## Migration Logic

`store.py` keeps backward compatibility with older JSON shapes:

- Legacy `stack3_outputs` or `manual_analog_outputs` become `leak_sensors.sensors`.
- Legacy relay detector stack references become direct `i2c_address` references.
- Older ball valve entries are normalized into either `cv` or `ov` profiles.
- RTD sensor fields are normalized to current names and defaults.

After loading and migrating, the store writes the normalized model back to disk if the JSON changed.

## Runtime Store

`runtime_store.py` is intentionally smaller than config persistence. It stores runtime continuity data that should survive backend restarts but should not be user-edited as normal config. Currently this is used for CV valve state continuity.
