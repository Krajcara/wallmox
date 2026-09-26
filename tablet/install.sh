#!/usr/bin/env bash
# Install the Wallmox screen helper on a Linux kiosk tablet (run with sudo).
# The admin panel shows this command with your address filled in:
#   sudo WALLMOX_URL=https://wallmox.example.com bash -c "$(curl -fsSL https://raw.githubusercontent.com/krajcara/wallmox/main/tablet/install.sh)"
# Optional: WALLMOX_KEY (status page key), WALLMOX_SCREEN_UNINSTALL=1 to remove.
set -Eeuo pipefail

REPO_RAW="${WALLMOX_REPO_RAW:-https://raw.githubusercontent.com/krajcara/wallmox}"
REF="${WALLMOX_REF:-main}"
BIN="/usr/local/bin/wallmox-screen"
CONF="/etc/wallmox-screen.conf"
UNIT="/etc/systemd/system/wallmox-screen.service"

ok()  { printf '  \e[32m✓\e[0m %s\n' "$*"; }
die() { printf '\e[31mError:\e[0m %s\n' "$*" >&2; exit 1; }
trap 'die "stopped at line $LINENO"' ERR

[[ $EUID -eq 0 ]] || die "Run with sudo."

if [[ "${WALLMOX_SCREEN_UNINSTALL:-0}" == "1" ]]; then
  systemctl disable --now wallmox-screen >/dev/null 2>&1 || true
  rm -f "$UNIT" "$BIN" "$CONF"; systemctl daemon-reload
  ok "Wallmox screen helper removed."; exit 0
fi

URL="${WALLMOX_URL:-}"
[[ -n "$URL" ]] || die "Set WALLMOX_URL (copy the full command from the Wallmox admin panel)."
URL="${URL%/}"
compgen -G "/sys/class/backlight/*" >/dev/null || die "This device has no backlight control (/sys/class/backlight is empty)."

command -v curl >/dev/null || { apt-get update -qq && apt-get install -y -qq curl >/dev/null; }

TMP="$(mktemp)"
curl -fsSL "$REPO_RAW/$REF/tablet/wallmox-screen.sh" -o "$TMP" || die "Could not download the helper."
bash -n "$TMP" || die "The downloaded helper is not a valid script."
install -m 755 "$TMP" "$BIN"; rm -f "$TMP"
ok "Helper in $BIN"

umask 077
cat > "$CONF" <<CONFEOF
# Wallmox screen helper. Restart after changes: systemctl restart wallmox-screen
URL=$URL
KEY=${WALLMOX_KEY:-}
DEVICE=
INTERVAL=60
CONFEOF
ok "Settings in $CONF"

cat > "$UNIT" <<UNITEOF
[Unit]
Description=Wallmox screen helper (night mode backlight)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$BIN
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNITEOF
systemctl daemon-reload
systemctl enable --now wallmox-screen >/dev/null 2>&1
systemctl restart wallmox-screen

# earlier setups used cron lines to switch the backlight; they would fight the helper
if crontab -l 2>/dev/null | grep -q '/sys/class/backlight/'; then
  { crontab -l | grep -v '/sys/class/backlight/' || true; } | crontab -
  ok "Removed old backlight lines from root's crontab"
fi

sleep 2
systemctl is-active --quiet wallmox-screen || die "The helper did not start. See: journalctl -u wallmox-screen -n 20"
ok "Helper is running. Night mode now follows the Wallmox admin panel."
