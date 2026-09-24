#!/usr/bin/env bash
# =============================================================================
# Full Stack Emulator — service runner
# =============================================================================
# Called by systemd (ExecStart) in emulator-backend.service. Optionally seeds
# the config file, builds and deploys the frontend for nginx, then execs
# uvicorn in the FOREGROUND so systemd owns the real process.
#
# Can also be run by hand for debugging:
#   ./run-emulator-backend.sh                 # honour infra/emulator.env
#   BUILD_FRONTEND=0 ./run-emulator-backend.sh   # skip the npm build
#   ./run-emulator-backend.sh --help
#
# Every tunable is documented in emulator.env.example.
#
# EXIT CODES (visible in `systemctl status emulator-backend`; each maps to a row
# in the troubleshooting table in README.md):
#    2  bad usage / unknown argument
#   10  project layout wrong (backend or frontend dir missing, app.py missing)
#   11  python virtualenv missing or not executable
#   12  uvicorn missing from the virtualenv
#   13  npm required for the frontend build but not found
#   14  frontend build failed (npm ci / npm run build)
#   15  frontend deploy failed (cannot write FRONTEND_DEST, or dist/ empty)
#   16  config seeding failed
# =============================================================================

set -euo pipefail

# --- Logging -----------------------------------------------------------------
# Plain prefixed lines: journald already timestamps every record, so adding our
# own would double up in `journalctl`. When run from a terminal the prefixes are
# still enough to scan.
log()  { printf '[emulator] %s\n' "$*"; }
warn() { printf '[emulator][WARN] %s\n' "$*" >&2; }
fail() {
    local code="$1"; shift
    printf '[emulator][FAIL:%s] %s\n' "$code" "$*" >&2
    exit "$code"
}

# Report the failing line for any unhandled error, so a `set -e` abort is not
# an anonymous non-zero exit in the journal.
trap 'rc=$?; [[ $rc -ne 0 ]] && printf "[emulator][FAIL:%s] aborted at line %s: %s\n" "$rc" "$LINENO" "$BASH_COMMAND" >&2' ERR

# --- Path resolution ---------------------------------------------------------
_resolve_script_dir() {
    local src="${BASH_SOURCE[0]}"
    while [[ -h "$src" ]]; do
        local dir
        dir="$(cd -P "$(dirname "$src")" && pwd)"
        src="$(readlink "$src")"
        case "$src" in
            /*) ;;
            *) src="$dir/$src" ;;
        esac
    done
    cd -P "$(dirname "$src")" && pwd
}

INFRA_DIR="$(_resolve_script_dir)"
PROJECT_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
VENV_DIR="$BACKEND_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python3"
VENV_UVICORN="$VENV_DIR/bin/uvicorn"

# --- Settings (emulator.env overrides these) ---------------------------------
APP_ENV="${APP_ENV:-lab}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_LOG_LEVEL="${BACKEND_LOG_LEVEL:-info}"
FRONTEND_DEST="${FRONTEND_DEST:-/var/www/emulator}"
BUILD_FRONTEND="${BUILD_FRONTEND:-1}"
INSTALL_FRONTEND_DEPS="${INSTALL_FRONTEND_DEPS:-1}"
SEED_CONFIG="${SEED_CONFIG:-1}"

case "${1:-}" in
    ""|run) ;;
    -h|--help|help)
        sed -n '2,26p' "${BASH_SOURCE[0]}"
        exit 0
        ;;
    *) fail 2 "unknown argument '$1'. Usage: $0 [run|--help]" ;;
esac

log "============================================"
log "Full Stack Emulator startup"
log "============================================"
log "Project root:    $PROJECT_ROOT"
log "Backend:         $BACKEND_HOST:$BACKEND_PORT (log level $BACKEND_LOG_LEVEL)"
log "Frontend dest:   $FRONTEND_DEST (build=$BUILD_FRONTEND)"
log "App env:         $APP_ENV"
log "============================================"

# --- Step 0: layout preflight ------------------------------------------------
[[ -d "$BACKEND_DIR" ]]         || fail 10 "backend dir not found at $BACKEND_DIR"
[[ -f "$PROJECT_ROOT/app.py" ]] || fail 10 "app.py not found at $PROJECT_ROOT/app.py (uvicorn target is app:app)"
[[ -f "$BACKEND_DIR/app.py" ]]  || fail 10 "backend/app.py not found at $BACKEND_DIR/app.py"

# --- Step 1: seed the config file --------------------------------------------
# backend/emulator_config.json is git-ignored because the UI rewrites it via
# PUT /api/config. A fresh clone therefore has no config, and the backend would
# fall back to build_default_config() — generic boards, no real valve wiring, no
# Arctic HP ESP32 addresses. Copying the tracked example first avoids that.
CONFIG_FILE="$BACKEND_DIR/emulator_config.json"
CONFIG_EXAMPLE="$INFRA_DIR/emulator_config.example.json"

if [[ "$SEED_CONFIG" == "1" ]]; then
    if [[ -f "$CONFIG_FILE" ]]; then
        log "[1/3] Config present, leaving it alone: $CONFIG_FILE"
    elif [[ -f "$CONFIG_EXAMPLE" ]]; then
        log "[1/3] No config found — seeding from $CONFIG_EXAMPLE"
        cp "$CONFIG_EXAMPLE" "$CONFIG_FILE" \
            || fail 16 "could not write $CONFIG_FILE (owner mismatch? run: sudo chown $(id -un) $BACKEND_DIR)"
    else
        warn "[1/3] No config and no example at $CONFIG_EXAMPLE — the backend will generate DEFAULTS."
        warn "      Board counts, valve channels and Arctic HP IPs will NOT match your rig."
    fi
else
    log "[1/3] Config seeding disabled (SEED_CONFIG=0)"
fi

# --- Step 2: build and deploy the frontend -----------------------------------
_find_npm() {
    if [[ -n "${NPM:-}" && -x "${NPM:-}" ]]; then
        echo "$NPM"; return 0
    fi
    export NVM_DIR="${NVM_DIR:-$HOME/.config/nvm}"
    if [[ -d "$NVM_DIR/versions/node" ]]; then
        local found
        found="$(find "$NVM_DIR/versions/node" -maxdepth 3 -name npm -type f 2>/dev/null | sort -V | tail -1)"
        [[ -n "$found" ]] && { echo "$found"; return 0; }
    fi
    command -v npm 2>/dev/null || return 1
}

if [[ "$BUILD_FRONTEND" == "1" ]]; then
    log "[2/3] Building and deploying frontend..."

    [[ -d "$FRONTEND_DIR" ]] || fail 10 "frontend dir not found at $FRONTEND_DIR"

    NPM_BIN="$(_find_npm || true)"
    if [[ -z "$NPM_BIN" ]]; then
        fail 13 "npm not found. Set NPM= in infra/emulator.env, or re-run \
sudo ./infra/install-emulator-service.sh to regenerate .node-path.env, \
or set BUILD_FRONTEND=0 and deploy the frontend manually."
    fi
    log "      npm: $NPM_BIN"

    cd "$FRONTEND_DIR"

    if [[ "$INSTALL_FRONTEND_DEPS" == "1" ]]; then
        if [[ ! -d node_modules ]] || [[ package-lock.json -nt node_modules ]]; then
            log "      Installing frontend dependencies (npm ci)..."
            "$NPM_BIN" ci || fail 14 "npm ci failed in $FRONTEND_DIR"
        else
            log "      node_modules up to date, skipping npm ci"
        fi
    fi

    log "      Running vite build..."
    "$NPM_BIN" run build || fail 14 "npm run build failed in $FRONTEND_DIR"

    [[ -d "$FRONTEND_DIR/dist" ]] || fail 14 "build reported success but $FRONTEND_DIR/dist does not exist"
    [[ -f "$FRONTEND_DIR/dist/index.html" ]] || fail 14 "build produced no dist/index.html"

    # Deploy WITHOUT sudo. install-emulator-service.sh chowns FRONTEND_DEST to
    # this service user precisely so the hot path needs no privilege. That
    # matters under systemd, where an interactive sudo password prompt would
    # hang the unit until TimeoutStartSec fires.
    if [[ ! -d "$FRONTEND_DEST" ]]; then
        fail 15 "$FRONTEND_DEST does not exist. Run: sudo ./infra/install-emulator-service.sh"
    fi
    if [[ ! -w "$FRONTEND_DEST" ]]; then
        fail 15 "$FRONTEND_DEST is not writable by $(id -un). Run: sudo chown -R $(id -un):www-data $FRONTEND_DEST"
    fi

    log "      Deploying to $FRONTEND_DEST..."
    # Replace contents, not the directory itself — the directory's ownership and
    # mode were set once at install time and should survive every deploy.
    find "$FRONTEND_DEST" -mindepth 1 -delete 2>/dev/null || true
    cp -r "$FRONTEND_DIR/dist/." "$FRONTEND_DEST/" || fail 15 "copy to $FRONTEND_DEST failed"
    chmod -R a+rX "$FRONTEND_DEST" || warn "could not relax permissions on $FRONTEND_DEST; nginx may 403"

    log "      Frontend deployed ($(find "$FRONTEND_DEST" -type f | wc -l | tr -d ' ') files)."
    # No `nginx -s reload` here: nginx reads static files off disk per request,
    # so replacing them needs no reload. Only a CHANGED nginx config does, and
    # that is install-emulator-service.sh's job.
else
    log "[2/3] Frontend build disabled (BUILD_FRONTEND=0)"
    if [[ ! -f "$FRONTEND_DEST/index.html" ]]; then
        warn "      $FRONTEND_DEST/index.html is missing — the UI will 404."
        warn "      Deploy it with: ./infra/deploy-frontend.sh"
    fi
fi

# --- Step 3: start the backend -----------------------------------------------
log "[3/3] Starting backend..."

if [[ ! -x "$VENV_PYTHON" ]]; then
    fail 11 "virtualenv python not found at $VENV_PYTHON. Create it with: \
cd $BACKEND_DIR && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
fi
if [[ ! -x "$VENV_UVICORN" ]]; then
    fail 12 "uvicorn not found at $VENV_UVICORN. Install it with: \
$VENV_PYTHON -m pip install -r $BACKEND_DIR/requirements.txt"
fi

export APP_ENV
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
# app.py at the project root imports `backend.app`, which itself imports `src.*`.
# Both roots must be importable regardless of cwd.
export PYTHONPATH="${PYTHONPATH:-}:$PROJECT_ROOT:$BACKEND_DIR"

cd "$PROJECT_ROOT"

log "      uvicorn app:app -> $BACKEND_HOST:$BACKEND_PORT"
log "      python: $VENV_PYTHON"

# --reload is deliberately absent. The backend writes emulator_config.json and
# emulator_runtime.json while running; under --reload those writes trip the file
# watcher, which kills and restarts the server and produces rolling 502s through
# nginx. Restart after a code change with:
#   sudo systemctl restart emulator-backend
#
# exec so systemd tracks uvicorn's PID directly and its signals reach the app.
exec "$VENV_UVICORN" app:app \
    --host "$BACKEND_HOST" \
    --port "$BACKEND_PORT" \
    --log-level "$BACKEND_LOG_LEVEL"
