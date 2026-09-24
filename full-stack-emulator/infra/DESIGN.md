# DESIGN — Full Stack Emulator deployment (nginx + systemd)

End state this `infra/` directory produces, and the reasoning behind each
choice. Operational instructions live in [README.md](README.md).

## 1. End state

One Raspberry Pi, one nginx site, one systemd unit.

```
                        Pi :80
   browser ────────────► nginx ──┬─► /              → /var/www/emulator (SPA, try_files → index.html)
                                 ├─► /assets/       → same, immutable 7d cache
                                 ├─► /api/*         → proxy 127.0.0.1:8000
                                 ├─► /nginx-health  → 200 literal
                                 └─► /backend-health→ proxy 127.0.0.1:8000/
                                                          │
                              systemd: emulator-backend   │
                              run-emulator-backend.sh ────┘
                                 └─ exec uvicorn app:app --host 0.0.0.0 --port 8000
                                        │
                                        ├─ /dev/ttyACM0   Arctic HP Modbus RTU
                                        ├─ /dev/i2c-1     relay detectors
                                        └─ SPI/GPIO       Sequent RTD / analog boards
```

Single environment, not the dev/prod split P5-2 carries. The emulator is bench
instrumentation: there is no production tenant to protect from a bad deploy, and
a second nginx root plus a second unit would be maintenance with no consumer.

## 2. Component responsibilities

| Component | Owns | Explicitly does not own |
|---|---|---|
| `nginx/emulator.conf` | TLS-less HTTP termination, static serving, SPA fallback, cache policy, `/api/` proxy, health probes | Any knowledge of Python, venvs, or build steps |
| `systemd/emulator-backend.service` | Process lifecycle, restart policy, env file loading, journal identity, hardware-access posture | Any logic — it delegates entirely to the runner |
| `run-emulator-backend.sh` | Preflight, config seeding, optional frontend build+deploy, `exec uvicorn` | Privileged operations; nginx configuration |
| `install-emulator-service.sh` | All one-time privileged setup: directories, ownership, nginx site, unit installation, npm discovery | Anything on the per-start path |
| `deploy-frontend.sh` | Build + deploy the SPA independently of the backend | Backend lifecycle |
| `emulator.env` | Every tunable, in one place | Secrets — there are none in this deployment |

## 3. Load-bearing decisions

**D1 — nginx serves static files; uvicorn never does.**
FastAPI can mount `StaticFiles`, which would remove nginx entirely. Rejected:
nginx gives the SPA history fallback, gzip, and immutable asset caching for free,
and it decouples UI redeploys from backend restarts. Restarting the backend
destroys live emulator state (valve travel in progress, RTD CSV playback
position, the running Arctic HP Modbus server); a UI fix must not cost that.

**D2 — `VITE_API_BASE` stays empty.**
`frontend/src/api/client.js` already falls back to `''`, so the bundle requests
same-origin relative paths and nginx proxies them. This keeps the Pi's IP out of
the built artifact — the same `dist/` works on any emulator Pi — and makes the
permissive `allow_origins=["*"]` CORS middleware in `backend/app.py` irrelevant
in the deployed path rather than load-bearing.

**D3 — no `--reload` under systemd.**
The backend persists `emulator_config.json` and `emulator_runtime.json` during
normal operation. Under `--reload` those writes trip uvicorn's file watcher,
which kills and restarts the worker, producing rolling 502s through nginx. P5-2
hit this and documented it; the runner omits `--reload` and the README says why.
The existing `full-stack-emulator/emulator-backend.sh` keeps `--reload` and
remains the right tool for interactive development — it is not the service path.

**D4 — no `sudo` on the per-start path.**
P5-2's runner `sudo cp`s the build into `/var/www` and `sudo systemctl reload
nginx` on every start, which silently requires passwordless sudo for the service
user; without it a systemd start hangs on a password prompt until
`TimeoutStartSec`. Instead the installer chowns `FRONTEND_DEST` to
`SERVICE_USER:www-data` once, and the runner writes there as itself. Privilege is
confined to the installer, where an interactive prompt is fine.

**D5 — no nginx reload after a static deploy.**
nginx resolves static files per request. Reloading after replacing files is
cargo cult. Reload is needed only when the *config* changes, which happens only
in the installer, where it is gated behind `nginx -t`.

**D6 — the installer rewrites the unit's paths.**
systemd units cannot compute paths, so `ExecStart`, `WorkingDirectory` and both
`EnvironmentFile=` lines are absolute. A moved or renamed checkout would fail
with a bare `203/EXEC`. The installer derives the real root from its own
location and `sed`s the installed copy, and derives `User=`/`Group=` from the
checkout's owner rather than assuming `pi` — this Pi's service user is
`saxifrage`.

**D7 — config is seeded, never overwritten.**
See README. `SEED_CONFIG=1` copies `emulator_config.example.json` only when no
config exists. The alternative — un-ignoring `backend/emulator_config.json` —
was rejected because the UI rewrites that file continuously, so tracking it
would leave a permanently dirty working tree and generate merge conflicts on
every pull.

**D8 — numeric exit codes, one per failure mode.**
`systemctl status` surfaces `status=NN`, and every code maps to a row in the
README's table. A generic exit 1 makes the operator read the journal and guess;
`status=11` says "no virtualenv" with no interpretation required. Codes are
stable API: append, never renumber.

**D9 — a health probe pair, not one.**
`/nginx-health` returns a literal, so it succeeds even when the backend is dead.
`/backend-health` proxies to the backend's `/` route. Which one fails localises
the fault to nginx or to uvicorn in a single curl. Adding a real `/health`
endpoint to `backend/app.py` would be cleaner, but that is an application change
and out of scope for this directory.

**D10 — `BUILD_FRONTEND` is a switch, not a fork.**
The chosen default (`1`) is P5-2's dev-env behaviour: `git pull` + restart ships
everything. Setting it to `0` gives P5-2's prod-env behaviour with
`deploy-frontend.sh`. One runner covers both, so the two paths cannot drift.

## 4. Failure modes and how they surface

| Failure | Detection | Surface |
|---|---|---|
| Missing venv / uvicorn | Runner preflight before any work | `FAIL:11` / `FAIL:12` + the exact create command |
| npm invisible to systemd | Runner npm search (`NPM` → nvm → `PATH`) | `FAIL:13`, pointing at `.node-path.env` |
| Vite build breaks | Non-zero npm exit, plus a `dist/index.html` existence assert | `FAIL:14`, npm output in the journal |
| Serving dir not writable | Explicit `-d` / `-w` tests before deleting anything | `FAIL:15` + the `chown` command |
| Checkout moved | Installer compares unit `ExecStart` to the real root | Warning, then automatic rewrite |
| Port drift between env and nginx | Installer greps `proxy_pass` and `root` from the conf | `FAIL:23` + the `sed` to fix it |
| Config would be regenerated | Runner checks for the file before start | Seeded from the example, or a loud `WARN` |
| Permanent misconfiguration | `StartLimitBurst=5` / `StartLimitIntervalSec=600` | Unit stops retrying instead of thrashing hardware |

## 5. Deliberately out of scope

- **TLS.** Lab LAN, HTTP only. Adding it means a cert story and a redirect block.
- **Auth.** Anyone who can reach the Pi can drive the emulator. Same posture as
  P5-2 dev-env.
- **systemd hardening** (`ProtectSystem`, `PrivateDevices`, `DynamicUser`). This
  unit needs `/dev/ttyACM0`, `/dev/i2c-*`, `/dev/spidev*` and `/dev/gpiomem`;
  the sandboxing options interact badly with all four and each would need
  per-device re-testing. The unit carries a comment saying so.
- **Application changes.** No `/health` endpoint, no environment-variable
  support inside the FastAPI app, no change to the `.gitignore` rule for
  `backend/emulator_config.json`. Each is a separate decision.
- **Log rotation for the backend.** Output goes to journald, which rotates
  itself. nginx's own logs use the distro's logrotate.
