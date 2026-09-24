# Sensors

The `sensors` package contains hardware adapters and domain behavior functions. This is the lowest backend layer before physical board libraries or protocol emulators.

## RTD

`rtd/`

- `chain_driver.py`: drives the 74HC595 output chain and reports hardware availability.
- `frame_utils.py`: converts between RTD temperature, resistance, board codes, bit widths, and frame bytes.
- `sensor.py`: owns RTD output state and applies config/manual/CSV output sources.

The RTD path is designed so missing hardware does not crash the backend. The manager snapshot reports availability and errors.

## Ball Valve

`ball_valve/cv/sensor.py`

- `BallValveHardwareAdapter`: analog VIN/VOUT board access.
- `update_cv_state()`: CV ramp and detector-gated analog feedback behavior.

`ball_valve/ov/sensor.py`

- `update_ov_state()`: OV open/close detector edge detection, pending action timing, feedback pulse timing, and position state.

`ball_valve/relay_hardware.py`

- `BallValveRelayHardwareAdapter`: shared MCP23017 relay detector input reading and relay feedback output writing.

Relay hardware is shared because CV and OV both use detector channels. The implementation is separate from OV behavior so CV does not depend on an OV-specific sensor module for common hardware.

## Leak Sensor

`leak_sensor/sensor.py` writes configured 0-10V leak sensor voltages to analog output channels and reports channel availability/errors.

## Arctic HP

`arctic_hp/register_map.py` defines register addresses, defaults, and bitfields.

`arctic_hp/emulator.py` owns per-device register state and optional Modbus RTU server behavior. If `pymodbus` is unavailable, offline register editing still works and runtime state reports the missing transport.
