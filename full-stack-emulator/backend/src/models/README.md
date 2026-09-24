# Models

The `models` package defines Pydantic schemas for persisted config, runtime snapshots, and domain-specific state.

## Files

- `emulator.py`: top-level `EmulatorConfig` and `RuntimeSnapshot` composition.
- `config.py`: convenience exports for the main config models.
- `rtd.py`: RTD config and playback config.
- `valves.py`: CV/OV ball valve config, relay detector config, relay feedback config, valve runtime state, and detector runtime state.
- `leak_sensor.py`: leak sensor config and runtime state.
- `arctic.py`: Arctic heat pump port, device, register, and runtime models.
- `state.py`: convenience exports for runtime-state models.

## Model Goals

Models define the contract between backend, persisted JSON, and frontend. They should:

- Keep config validation close to the data shape.
- Make nullable or optional hardware assignments explicit.
- Preserve profile-specific valve fields through discriminated unions.
- Return runtime errors as structured fields instead of throwing during snapshot generation.

## Ball Valve Model Shape

Ball valves are stored in one `ValveConfig` block:

- `ball_valves`: list of `cv` and `ov` profile entries.
- `relay_detectors`: shared MCP23017 detector board config.
- `relay_output_i2c_bus`: shared bus for relay feedback boards.

CV valves reference one `relay_detector`, one analog input channel, and one analog output channel.

OV valves reference open/close detector channels and open/close feedback relay channels.

This keeps one card worth of control data together while allowing shared relay hardware to be implemented once in the sensor layer.
