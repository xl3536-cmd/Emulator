# Controllers

Controllers are a thin layer between FastAPI routes and services.

## Purpose

The controller layer keeps route files focused on HTTP concerns and keeps services focused on application operations. A controller usually exposes one method for each route action and delegates directly to the matching service.

Current controllers:

- `config_controller.py`: get and update full emulator config.
- `emulator_controller.py`: return the complete runtime snapshot.
- `rtd_controller.py`: CSV load/clear, playback control, and manual RTD board writes.
- `valve_controller.py`: set or clear CV valve VIN override.
- `leak_sensor_controller.py`: set leak sensor output voltage.
- `arctic_controller.py`: start/stop Arctic server and mutate Arctic registers/devices.

## Logic Boundary

Controllers should not own hardware logic, config migration, or runtime state. Those responsibilities stay in services, managers, config stores, and sensors.

If a future endpoint needs validation that is not HTTP-schema validation, prefer putting it in the service or model layer so non-HTTP callers get the same behavior.
