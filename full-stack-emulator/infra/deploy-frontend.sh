#!/usr/bin/env bash
# =============================================================================
# Full Stack Emulator — frontend build + deploy
# =============================================================================
# Builds the Vite SPA and copies it into the nginx serving directory. Run this
# by hand when BUILD_FRONTEND=0, or any time you want to ship a UI change
# WITHOUT restarting the backend (the backend holds live emulator state — valve
# positions, RTD playback, the Arctic HP Modbus server — and restarting it
# throws that away).
#
# Usage:
#   ./deploy-frontend.sh            # npm ci if needed, build, deploy
#   ./deploy-frontend.sh --no-deps  # skip npm ci
#
# Reads the same infra/emulator.env as the service.
#
# EXIT CODES:
#    2  bad usage
#   10  project layout wrong
#   13  npm not found
#   14  build failed
#   15  deploy failed
# =============================================================================

set -euo pipefail

log()  { printf '[deploy-frontend] %s\n' "$*"; }
warn() { printf '[deploy-frontend][WARN] %s\n' "$*" >&2; }
fail() { local code="$1"; shift; printf '[deploy-frontend][FAIL:%s] %s\n' "$code" "$*" >&2; exit "$code"; }

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

INSTALL_DEPS=1

case "${1:-}" in
    "") ;;
    --no-deps) INSTALL_DEPS=0 ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) fail 2 "unknown argument '$1'" ;;
esac

# Load emulator.env so FRONTEND_DEST and NPM match what the service uses.
if [[ -f "$INFRA_DIR/emulator.env" ]]; then
    set -a; . "$INFRA_DIR/emulator.env"; set +a
    log "Loaded $INFRA_DIR/emulator.env"
else
    warn "No $INFRA_DIR/emulator.env — using defaults"
fi
if [[ -f "$INFRA_DIR/.node-path.env" ]]; then
    set -a; . "$INFRA_DIR/.node-path.env"; set +a
fi

FRONTEND_DEST="${FRONTEND_DEST:-/var/www/emulator}"

[[ -d "$FRONTEND_DIR" ]] || fail 10 "frontend dir not found at $FRONTEND_DIR"

_find_npm() {
    if [[ -n "${NPM:-}" && -x "${NPM:-}" ]]; then echo "$NPM"; return 0; fi
    export NVM_DIR="${NVM_DIR:-$HOME/.config/nvm}"
    if [[ -d "$NVM_DIR/versions/node" ]]; then
        local found
        found="$(find "$NVM_DIR/versions/node" -maxdepth 3 -name npm -type f 2>/dev/null | sort -V | tail -1)"
        [[ -n "$found" ]] && { echo "$found"; return 0; }
    fi
    command -v npm 2>/dev/null || return 1
}

NPM_BIN="$(_find_npm || true)"
[[ -n "$NPM_BIN" ]] || fail 13 "npm not found. Set NPM= in infra/emulator.env or install Node.js."
log "npm: $NPM_BIN"

# Warn if the production env file is absent. Without it VITE_API_BASE is
# undefined, which client.js already treats as '' (same-origin) — so the build
# is still correct. The file exists to make that explicit and to stop a stray
# laptop-oriented .env from leaking a hard-coded IP into the bundle.
if [[ ! -f "$FRONTEND_DIR/.env.production" ]]; then
    warn "No frontend/.env.production. Same-origin default applies (correct for nginx)."
    warn "To make it explicit: cp $INFRA_DIR/frontend.env.example $FRONTEND_DIR/.env.production"
fi

cd "$FRONTEND_DIR"

if [[ "$INSTALL_DEPS" == "1" ]]; then
    if [[ ! -d node_modules ]] || [[ package-lock.json -nt node_modules ]]; then
        log "Installing dependencies (npm ci)..."
        "$NPM_BIN" ci || fail 14 "npm ci failed"
    else
        log "node_modules up to date"
    fi
fi

log "Building..."
"$NPM_BIN" run build || fail 14 "npm run build failed"
[[ -f dist/index.html ]] || fail 14 "build produced no dist/index.html"

[[ -d "$FRONTEND_DEST" ]] || fail 15 "$FRONTEND_DEST does not exist. Run: sudo $INFRA_DIR/install-emulator-service.sh"
[[ -w "$FRONTEND_DEST" ]] || fail 15 "$FRONTEND_DEST not writable by $(id -un). Run: sudo chown -R $(id -un):www-data $FRONTEND_DEST"

log "Deploying to $FRONTEND_DEST..."
find "$FRONTEND_DEST" -mindepth 1 -delete 2>/dev/null || true
cp -r dist/. "$FRONTEND_DEST/" || fail 15 "copy failed"
chmod -R a+rX "$FRONTEND_DEST" || warn "chmod failed; nginx may return 403"

log "Done — $(find "$FRONTEND_DEST" -type f | wc -l | tr -d ' ') files deployed."
log "No nginx reload needed: static files are read per request."
log "Verify: curl -sI http://localhost/ | head -1"
