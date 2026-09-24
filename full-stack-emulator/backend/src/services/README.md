# Services

Services are the application operation layer. They are called by controllers and delegate to `emulator_manager` or a domain manager.

## Files

- `config_service.py`: returns current config and validates/saves/hot-applies updated config.
- `emulator_service.py`: returns the complete runtime snapshot.
- `rtd_service.py`: handles CSV load/clear, playback toggles, and manual RTD board writes.
- `valve_service.py`: handles CV valve input override commands.
- `leak_sensor_service.py`: handles leak sensor voltage commands.
- `arctic_service.py`: handles Arctic server lifecycle and register/device changes.

## Validation Boundary

HTTP payload structure is validated in routes. Domain validation belongs in services or models.

Example: `config_service.py` validates `ValveConfig.validate_runtime_constraints()` before accepting a full config update. This catches duplicate relay detector assignments and invalid feedback reuse before managers apply the config.

## Result Shape

Services return small dictionaries for mutation endpoints and full model-derived data for snapshot/config endpoints. Runtime details that the UI needs should come from manager snapshots, not from direct hardware calls in the service layer.
