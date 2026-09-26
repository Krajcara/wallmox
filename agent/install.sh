#!/usr/bin/env bash
# Install or update the Wallmox temperature agent on a Proxmox node.
#
# The admin panel shows this command with your key filled in:
#   WALLMOX_AGENT_KEY=... bash -c "$(curl -fsSL https://raw.githubusercontent.com/krajcara/wallmox/main/agent/install.sh)"
#
# Optional: WALLMOX_AGENT_PORT (default 9105), WALLMOX_AGENT_ALLOW (IP of the
# Wallmox container; adds a Proxmox firewall rule for it when the firewall is on),
# WALLMOX_AGENT_UNINSTALL=1 to remove the agent.
# Running it again updates the agent and keeps the existing key.
set -Eeuo pipefail

REPO_RAW="${WALLMOX_REPO_RAW:-https://raw.githubusercontent.com/krajcara/wallmox}"
REF="${WALLMOX_AGENT_REF:-main}"
DIR="/opt/wallmox-agent"
CONF_DIR="/etc/wallmox-agent"
CONF="$CONF_DIR/agent.conf"
UNIT="/etc/systemd/system/wallmox-agent.service"
USER_NAME="wallmox-agent"

if [[ -t 1 ]]; then C_OK=$'\e[32m'; C_ERR=$'\e[31m'; C_B=$'\e[1m'; C_0=$'\e[0m'; else C_OK=""; C_ERR=""; C_B=""; C_0=""; fi
ok()  { printf '  %s✓%s %s\n' "$C_OK" "$C_0" "$*"; }
die() { printf '%sError:%s %s\n' "$C_ERR" "$C_0" "$*" >&2; exit 1; }
trap 'die "stopped at line $LINENO"' ERR

[[ $EUID -eq 0 ]] || die "Run this as root on the Proxmox node."
command -v python3 >/dev/null || die "python3 not found."
command -v systemctl >/dev/null || die "systemd not found."

if [[ "${WALLMOX_AGENT_UNINSTALL:-0}" == "1" ]]; then
  systemctl disable --now wallmox-agent >/dev/null 2>&1 || true
  rm -f "$UNIT"; systemctl daemon-reload
  rm -rf "$DIR" "$CONF_DIR"
  userdel "$USER_NAME" >/dev/null 2>&1 || true
  ok "Wallmox agent removed."
  exit 0
fi

# key: from the command, else keep the one already installed
KEY="${WALLMOX_AGENT_KEY:-}"
if [[ -z "$KEY" && -f "$CONF" ]]; then
  KEY="$(sed -n 's/^KEY=//p' "$CONF" | head -n1)"
fi
[[ ${#KEY} -ge 16 ]] || die "Set WALLMOX_AGENT_KEY (copy the full command from the Wallmox admin panel)."
[[ "$KEY" =~ ^[A-Za-z0-9_-]+$ ]] || die "The key may only contain letters, digits, - and _."

PORT="${WALLMOX_AGENT_PORT:-}"
if [[ -z "$PORT" && -f "$CONF" ]]; then PORT="$(sed -n 's/^PORT=//p' "$CONF" | head -n1)"; fi
PORT="${PORT:-9105}"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "WALLMOX_AGENT_PORT must be a number."

echo "${C_B}Wallmox agent${C_0}"

id "$USER_NAME" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$USER_NAME"

install -d -m 755 "$DIR"
TMP="$(mktemp)"
curl -fsSL "$REPO_RAW/$REF/agent/wallmox-agent.py" -o "$TMP" || die "Could not download the agent."
python3 -m py_compile "$TMP" || die "The downloaded agent is not valid Python."
install -m 755 "$TMP" "$DIR/wallmox-agent.py"
rm -f "$TMP"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$DIR/wallmox-agent.py")"
ok "Agent $VERSION in $DIR"

install -d -m 750 -o root -g "$USER_NAME" "$CONF_DIR"
umask 027
cat > "$CONF" <<EOF
# Wallmox agent settings. Restart after changes: systemctl restart wallmox-agent
KEY=$KEY
PORT=$PORT
LISTEN=0.0.0.0
EOF
chown root:"$USER_NAME" "$CONF"; chmod 640 "$CONF"
ok "Settings in $CONF"

cat > "$UNIT" <<EOF
[Unit]
Description=Wallmox temperature agent
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
Group=$USER_NAME
ExecStart=/usr/bin/python3 $DIR/wallmox-agent.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
MemoryMax=64M

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable wallmox-agent >/dev/null 2>&1
systemctl restart wallmox-agent

for _ in $(seq 1 10); do
  if python3 - "$PORT" "$KEY" <<'PY' 2>/dev/null
import json, sys, urllib.request
req = urllib.request.Request(f"http://127.0.0.1:{sys.argv[1]}/temps",
                             headers={"Authorization": "Bearer " + sys.argv[2]})
d = json.load(urllib.request.urlopen(req, timeout=3))
cpu = d.get("cpu")
print(f"  CPU {cpu} °C" if cpu is not None else "  no CPU sensor found", end="")
print(f", disks: {', '.join(x['name'] + ' ' + str(x['temp']) + ' °C' for x in d['disks'])}" if d["disks"] else "")
PY
  then
    ok "Agent is running on port $PORT"
    break
  fi
  sleep 1
done
systemctl is-active --quiet wallmox-agent || die "The agent did not start. See: journalctl -u wallmox-agent -n 30"

# Proxmox firewall: open the port for the Wallmox container if asked to
if [[ -n "${WALLMOX_AGENT_ALLOW:-}" ]] && command -v pve-firewall >/dev/null; then
  NODE="$(hostname)"
  RULES="$(pvesh get "/nodes/$NODE/firewall/rules" --output-format json 2>/dev/null || echo '[]')"
  if ! grep -q "wallmox-agent" <<<"$RULES"; then
    pvesh create "/nodes/$NODE/firewall/rules" --action ACCEPT --type in --enable 1 \
      --proto tcp --dport "$PORT" --source "$WALLMOX_AGENT_ALLOW" --comment "wallmox-agent" >/dev/null
    ok "Firewall rule: $WALLMOX_AGENT_ALLOW may reach port $PORT"
  fi
fi

echo
echo "Done. Wallmox will pick up the temperatures of $(hostname) within a few seconds."
