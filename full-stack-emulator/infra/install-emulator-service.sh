#!/usr/bin/env bash
# =============================================================================
# Full Stack Emulator — one-time installer
# =============================================================================
# Run ONCE on the emulator Pi after cloning the repo. Idempotent: safe to re-run
# after a git pull, and re-run it whenever you change nginx/emulator.conf,
# systemd/emulator-backend.service, or the Node version.
#
#   sudo ./infra/install-emulator-service.sh
#   sudo ./infra/install-emulator-service.sh --force   # allow non-ARM host
#
# What it does:
#   1. Creates infra/emulator.env from the example, if absent
#   2. Creates frontend/.env.production from the example, if absent
#   3. Detects npm for the service user -> infra/.node-path.env
#   4. Creates FRONTEND_DEST and hands it to the service user (no sudo at
#      deploy time)
#   5. Cross-checks nginx/emulator.conf against emulator.env, installs and
#      enables the site, disables nginx's stock default site
#   6. Installs the systemd unit and reloads the daemon
#
# It does NOT create the python virtualenv or start anything — it prints the
# commands for that so you run them as your own user.
#
# EXIT CODES:
#    2  bad usage
#    3  not run as root
#    4  not an ARM host (override with --force)
#   10  project layout wrong
#   20  nginx not installed
#   21  nginx config test failed
#   22  systemd unit install failed
#   23  emulator.env and nginx/emulator.conf disagree
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail() { local code="$1"; shift; echo -e "${RED}[FAIL:${code}]${NC} $*"; exit "$code"; }

FORCE=0
case "${1:-}" in
    "") ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,34p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) fail 2 "unknown argument '$1'" ;;
esac

# --- Host and privilege checks -----------------------------------------------
ARCH="$(uname -m)"
if [[ "$ARCH" != arm* && "$ARCH" != aarch64 ]]; then
    if [[ "$FORCE" == "1" ]]; then
        warn "Host arch is $ARCH, not ARM. Continuing because --force was given."
        warn "The Pi-only wheels in backend/requirements.txt (RPi.GPIO, spidev, SM*) will not install here."
    else
        fail 4 "This installer targets a Raspberry Pi. Detected arch: $ARCH. Re-run with --force to override."
    fi
fi

[[ "$EUID" -eq 0 ]] || fail 3 "Run with sudo: sudo ./infra/install-emulator-service.sh"

echo ""
echo "  +------------------------------------------------------+"
echo "  |   Full Stack Emulator — Service & Nginx Installer    |"
echo "  +------------------------------------------------------+"
echo ""

# --- Paths -------------------------------------------------------------------
INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
UNIT_SRC="$INFRA_DIR/systemd/emulator-backend.service"
NGINX_SRC="$INFRA_DIR/nginx/emulator.conf"
SERVICE_NAME="emulator-backend"

[[ -d "$BACKEND_DIR" ]]  || fail 10 "backend dir not found at $BACKEND_DIR"
[[ -d "$FRONTEND_DIR" ]] || fail 10 "frontend dir not found at $FRONTEND_DIR"
[[ -f "$UNIT_SRC" ]]     || fail 10 "unit file not found at $UNIT_SRC"
[[ -f "$NGINX_SRC" ]]    || fail 10 "nginx config not found at $NGINX_SRC"

# The service user is whoever owns the checkout — not root, and not necessarily
# the person running sudo. Deriving it from the repo avoids a unit that runs as
# a user with no access to its own code.
SERVICE_USER="$(stat -c '%U' "$PROJECT_ROOT")"
SERVICE_GROUP="$(stat -c '%G' "$PROJECT_ROOT")"
SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
info "Project root:  $PROJECT_ROOT"
info "Service user:  $SERVICE_USER:$SERVICE_GROUP (home $SERVICE_HOME)"

# --- Cross-check the unit's hard-coded paths ---------------------------------
# systemd units cannot compute paths, so emulator-backend.service contains
# absolute paths. If the checkout moved, the unit is wrong and the service would
# fail with a confusing 203/EXEC.
UNIT_ROOT="$(grep -m1 '^ExecStart=' "$UNIT_SRC" | sed 's|.*/bin/bash ||; s|/infra/run-emulator-backend.sh.*||')"
if [[ "$UNIT_ROOT" != "$PROJECT_ROOT" ]]; then
    warn "Unit file paths do not match this checkout:"
    warn "  unit expects:  $UNIT_ROOT"
    warn "  actual:        $PROJECT_ROOT"
    warn "Rewriting paths and the User= line in the INSTALLED copy (source file untouched)."
fi

# --- Step 1: emulator.env ----------------------------------------------------
info "Step 1/6: service environment file..."
if [[ ! -f "$INFRA_DIR/emulator.env" ]]; then
    cp "$INFRA_DIR/emulator.env.example" "$INFRA_DIR/emulator.env"
    chown "$SERVICE_USER:$SERVICE_GROUP" "$INFRA_DIR/emulator.env"
    chmod 600 "$INFRA_DIR/emulator.env"
    ok "Created $INFRA_DIR/emulator.env from the example"
else
    ok "$INFRA_DIR/emulator.env already exists — leaving it alone"
fi

# shellcheck source=/dev/null
set -a; . "$INFRA_DIR/emulator.env"; set +a
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_DEST="${FRONTEND_DEST:-/var/www/emulator}"
info "  BACKEND_PORT=$BACKEND_PORT  FRONTEND_DEST=$FRONTEND_DEST"

# --- Step 2: frontend/.env.production ----------------------------------------
info "Step 2/6: frontend build environment..."
if [[ ! -f "$FRONTEND_DIR/.env.production" ]]; then
    cp "$INFRA_DIR/frontend.env.example" "$FRONTEND_DIR/.env.production"
    chown "$SERVICE_USER:$SERVICE_GROUP" "$FRONTEND_DIR/.env.production"
    ok "Created $FRONTEND_DIR/.env.production (VITE_API_BASE empty = same-origin)"
else
    ok "$FRONTEND_DIR/.env.production already exists — leaving it alone"
fi

# --- Step 3: npm detection ---------------------------------------------------
# systemd gives the unit a minimal PATH, so an nvm-installed npm is invisible to
# it. Resolve npm the way the service user's login shell would, and record it.
info "Step 3/6: locating npm for $SERVICE_USER..."
NODE_ENV_FILE="$INFRA_DIR/.node-path.env"

detect_npm() {
    local p
    p="$(sudo -u "$SERVICE_USER" -H bash -lc 'command -v npm' 2>/dev/null || true)"
    if [[ -z "$p" ]]; then
        p="$(sudo -u "$SERVICE_USER" -H bash -c '
            export HOME="'"$SERVICE_HOME"'"
            for nvm in "$HOME/.config/nvm" "$HOME/.nvm"; do
                [ -s "$nvm/nvm.sh" ] && . "$nvm/nvm.sh" 2>/dev/null
                if [ -d "$nvm/versions/node" ]; then
                    found=$(find "$nvm/versions/node" -maxdepth 3 -name npm -type f 2>/dev/null | sort -V | tail -1)
                    [ -n "$found" ] && echo "$found" && exit 0
                fi
            done
            for c in "$HOME/.volta/bin/npm" "$HOME/.local/bin/npm" /usr/local/bin/npm /usr/bin/npm; do
                [ -x "$c" ] && echo "$c" && exit 0
            done
            command -v npm
        ' 2>/dev/null || true)"
    fi
    echo "$p"
}

NPM_PATH="$(detect_npm)"
if [[ -n "$NPM_PATH" && -x "$NPM_PATH" ]]; then
    NPM_DIR="$(dirname "$NPM_PATH")"
    cat > "$NODE_ENV_FILE" <<EOF
# Auto-generated by install-emulator-service.sh — do not commit, do not edit.
# Regenerate by re-running the installer after a Node version change.
PATH=$NPM_DIR:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
NPM=$NPM_PATH
NVM_DIR=$SERVICE_HOME/.config/nvm
EOF
    chown "$SERVICE_USER:$SERVICE_GROUP" "$NODE_ENV_FILE"
    chmod 644 "$NODE_ENV_FILE"
    ok "npm: $NPM_PATH  ->  wrote $NODE_ENV_FILE"
else
    warn "Could not find npm for $SERVICE_USER."
    warn "With BUILD_FRONTEND=1 the service will fail at startup with exit code 13."
    warn "Fix: in a $SERVICE_USER login shell run 'which npm', then set NPM= in infra/emulator.env,"
    warn "     or set BUILD_FRONTEND=0 and run ./infra/deploy-frontend.sh by hand."
fi

# --- Step 4: nginx serving directory -----------------------------------------
# Owned by the service user, group www-data. This is what lets the runner deploy
# the SPA with no sudo — important, because a sudo password prompt inside a
# systemd unit hangs until TimeoutStartSec expires.
info "Step 4/6: nginx serving directory $FRONTEND_DEST..."
mkdir -p "$FRONTEND_DEST"
NGINX_GROUP="www-data"
getent group "$NGINX_GROUP" >/dev/null || NGINX_GROUP="$SERVICE_GROUP"
chown -R "$SERVICE_USER:$NGINX_GROUP" "$FRONTEND_DEST"
chmod 755 "$FRONTEND_DEST"
ok "$FRONTEND_DEST owned by $SERVICE_USER:$NGINX_GROUP, mode 755"

# --- Step 5: nginx site ------------------------------------------------------
info "Step 5/6: nginx site..."
command -v nginx >/dev/null || fail 20 "nginx is not installed. Run: sudo apt install nginx"

# Consistency check: the conf is a literal file (nginx cannot read env vars), so
# a changed BACKEND_PORT or FRONTEND_DEST silently breaks the proxy or the root.
CONF_PORT="$(grep -oE 'proxy_pass +http://127\.0\.0\.1:[0-9]+' "$NGINX_SRC" | head -1 | grep -oE '[0-9]+$')"
CONF_ROOT="$(grep -m1 -E '^\s*root\s' "$NGINX_SRC" | sed 's/.*root\s*//; s/;.*//; s/"//g')"
if [[ "$CONF_PORT" != "$BACKEND_PORT" ]]; then
    fail 23 "nginx/emulator.conf proxies to :$CONF_PORT but emulator.env sets BACKEND_PORT=$BACKEND_PORT.
       Fix one of them, e.g.: sed -i 's|127.0.0.1:$CONF_PORT|127.0.0.1:$BACKEND_PORT|' $NGINX_SRC"
fi
if [[ "$CONF_ROOT" != "$FRONTEND_DEST" ]]; then
    fail 23 "nginx/emulator.conf root is $CONF_ROOT but emulator.env sets FRONTEND_DEST=$FRONTEND_DEST.
       Fix one of them, e.g.: sed -i 's|root $CONF_ROOT;|root $FRONTEND_DEST;|' $NGINX_SRC"
fi
ok "nginx conf agrees with emulator.env (port $BACKEND_PORT, root $FRONTEND_DEST)"

install -m 644 "$NGINX_SRC" /etc/nginx/sites-available/emulator
ln -sfn /etc/nginx/sites-available/emulator /etc/nginx/sites-enabled/emulator
ok "Installed /etc/nginx/sites-available/emulator and enabled it"

# Debian's stock site is also `listen 80 default_server`. Two default servers on
# one port makes `nginx -t` fail, so the stock one has to go. Only the symlink is
# removed; /etc/nginx/sites-available/default is untouched and can be relinked.
if [[ -e /etc/nginx/sites-enabled/default ]]; then
    rm -f /etc/nginx/sites-enabled/default
    warn "Disabled nginx's stock default site (removed /etc/nginx/sites-enabled/default)."
    warn "It conflicts on port 80. Restore with:"
    warn "  sudo ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default"
fi

info "Testing nginx configuration..."
nginx -t || fail 21 "nginx -t failed — see the output above. The site is installed but nginx was NOT reloaded."
systemctl reload nginx || systemctl restart nginx
ok "nginx configuration valid and reloaded"

# --- Step 6: systemd unit ----------------------------------------------------
info "Step 6/6: systemd unit..."
UNIT_DEST="/etc/systemd/system/$SERVICE_NAME.service"

# Rewrite the absolute paths and the user so the installed unit always matches
# this checkout, whatever the source file says.
sed -e "s|^User=.*|User=$SERVICE_USER|" \
    -e "s|^Group=.*|Group=$SERVICE_GROUP|" \
    -e "s|^Environment=HOME=.*|Environment=HOME=$SERVICE_HOME|" \
    -e "s|$UNIT_ROOT|$PROJECT_ROOT|g" \
    "$UNIT_SRC" > "$UNIT_DEST" || fail 22 "could not write $UNIT_DEST"
chmod 644 "$UNIT_DEST"
ok "Installed $UNIT_DEST"

systemctl daemon-reload || fail 22 "systemctl daemon-reload failed"
ok "systemd daemon reloaded"

# --- Virtualenv reminder -----------------------------------------------------
VENV_PYTHON="$BACKEND_DIR/venv/bin/python3"
VENV_UVICORN="$BACKEND_DIR/venv/bin/uvicorn"
echo ""
if [[ ! -x "$VENV_PYTHON" ]]; then
    warn "No virtualenv at $BACKEND_DIR/venv — the service will fail with exit code 11."
    warn "Create it as $SERVICE_USER (NOT as root, or the files will be root-owned):"
    warn "  cd $BACKEND_DIR && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
elif [[ ! -x "$VENV_UVICORN" ]]; then
    warn "Virtualenv exists but has no uvicorn — the service will fail with exit code 12."
    warn "  $VENV_PYTHON -m pip install -r $BACKEND_DIR/requirements.txt"
else
    ok "Virtualenv looks good: $VENV_UVICORN"
fi

# --- Next steps --------------------------------------------------------------
echo ""
echo "  ──────────────────────────────────────────────────────"
echo -e "  ${GREEN}Installation complete.${NC} Next steps:"
echo "  ──────────────────────────────────────────────────────"
echo ""
echo -e "  ${CYAN}Enable at boot and start now:${NC}"
echo "    sudo systemctl enable --now $SERVICE_NAME"
echo ""
echo -e "  ${CYAN}Watch the first start (the frontend build takes a while):${NC}"
echo "    journalctl -u $SERVICE_NAME -f"
echo ""
echo -e "  ${CYAN}Verify end to end:${NC}"
echo "    curl -s http://localhost/nginx-health"
echo "    curl -s http://localhost/backend-health"
echo "    curl -s http://localhost/api/config | head -c 200"
echo ""
echo -e "  ${CYAN}Then browse to:${NC}  http://\$(hostname -I | awk '{print \$1}')/"
echo ""
