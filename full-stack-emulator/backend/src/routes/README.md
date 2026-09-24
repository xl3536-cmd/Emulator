# Routes

Routes define the HTTP API surface using FastAPI `APIRouter` objects. They parse request payloads, bind URL parameters, and delegate to controllers.

## Route Groups

- `config_routes.py`
  - `GET /api/config`
  - `PUT /api/config`
- `emulator_routes.py`
  - `GET /api/runtime`
- `rtd_routes.py`
  - `POST /api/runtime/rtd/csv`
  - `POST /api/runtime/rtd/csv/clear`
  - `POST /api/runtime/rtd/playback`
  - `POST /api/runtime/rtd/boards/{board_index}`
- `valve_routes.py`
  - `POST /api/runtime/valves/{valve_id}/input-override`
- `leak_sensor_routes.py`
  - `POST /api/runtime/leak-sensors/{sensor_id}/voltage`
- `arctic_routes.py`
  - `POST /api/runtime/arctic-hp/server/start`
  - `POST /api/runtime/arctic-hp/server/stop`
  - `POST /api/runtime/arctic-hp/{device_id}/registers/{address}`
  - `POST /api/runtime/arctic-hp/{device_id}/reset`

## Boundary

Routes should stay small. They should not own scheduling, hardware behavior, config migration, or manager state.

When adding a route, add the payload model in the route file if it is HTTP-specific. Add shared domain models under `models` when the shape is also part of config or runtime state.
