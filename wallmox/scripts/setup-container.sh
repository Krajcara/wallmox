#!/usr/bin/env bash
# Wallmox: set up the app inside a Debian container (or any Debian 12+ machine).
# Run as root from the cloned repo: bash /opt/wallmox/scripts/setup-container.sh
# The installer calls this; it is also safe to run again after "git pull".
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/wallmox}"
DATA_DIR="/var/lib/wallmox"
CONF_DIR="/etc/wallmox"

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
[[ -f "$APP_DIR/requirements.txt" ]] || { echo "Wallmox not found in $APP_DIR" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
if ! command -v python3 >/dev/null || ! python3 -c "import venv, ensurepip" 2>/dev/null; then
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv >/dev/null
fi

id wallmox >/dev/null 2>&1 || \
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin wallmox

install -d -o wallmox -g wallmox -m 750 "$DATA_DIR"
install -d -o root -g wallmox -m 750 "$CONF_DIR"
if [[ ! -f "$CONF_DIR/config.toml" ]]; then
  install -o root -g wallmox -m 640 "$APP_DIR/config.example.toml" "$CONF_DIR/config.toml"
fi

[[ -x "$APP_DIR/venv/bin/python" ]] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

install -m 644 "$APP_DIR/systemd/wallmox.service" /etc/systemd/system/wallmox.service
systemctl daemon-reload
systemctl enable wallmox >/dev/null 2>&1

echo "Wallmox is set up in $APP_DIR."
