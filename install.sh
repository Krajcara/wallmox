#!/usr/bin/env bash
# Wallmox installer for Proxmox VE.
#
# Run in the shell of a Proxmox node, as root:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/krajcara/wallmox/main/install.sh)"
#
# It creates an unprivileged Debian LXC, a read-only API token (PVEAuditor),
# installs Wallmox in the container and prints the addresses to open.
#
# Every question has a default. For unattended installs set WALLMOX_DEFAULTS=1
# and override any of: CTID CT_HOSTNAME STORAGE BRIDGE NET DISK RAM CORES LANGUAGE
# CT_PASSWORD DNS SEARCHDOMAIN
# (NET is "dhcp" or "192.168.0.50/24,gw=192.168.0.1", DNS is "1.1.1.1 9.9.9.9").
#
# Installs the newest release. WALLMOX_BRANCH=main installs the latest code instead.
# Later updates: run "update" inside the container.
set -Eeuo pipefail

REPO="${WALLMOX_REPO:-https://github.com/krajcara/wallmox.git}"
BRANCH="${WALLMOX_BRANCH:-}"      # empty = newest release tag, or main if there is none
PVE_USER="wallmox@pve"
APP_DIR="/opt/wallmox"

# ------------------------------------------------------------------ output

if [[ -t 1 ]]; then
  C_OK=$'\e[32m'; C_WARN=$'\e[33m'; C_ERR=$'\e[31m'; C_DIM=$'\e[2m'; C_B=$'\e[1m'; C_0=$'\e[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_B=""; C_0=""
fi
step() { printf '%s==>%s %s\n' "$C_B" "$C_0" "$*"; }
ok()   { printf '    %s✓%s %s\n' "$C_OK" "$C_0" "$*"; }
warn() { printf '    %s!%s %s\n' "$C_WARN" "$C_0" "$*"; }
die()  { printf '%sError:%s %s\n' "$C_ERR" "$C_0" "$*" >&2; exit 1; }

CREATED_CT=""
on_error() {
  local line=$1
  printf '\n%sThe installer stopped at line %s.%s\n' "$C_ERR" "$line" "$C_0" >&2
  if [[ -n "$CREATED_CT" ]]; then
    printf 'Container %s was created. Remove it with:  pct stop %s; pct destroy %s\n' \
      "$CREATED_CT" "$CREATED_CT" "$CREATED_CT" >&2
  fi
}
trap 'on_error $LINENO' ERR

# ------------------------------------------------------------------ checks

[[ $EUID -eq 0 ]] || die "Run this as root."
for cmd in pct pveam pvesh pveum pvesm python3; do
  command -v "$cmd" >/dev/null || die "'$cmd' not found. Run this on a Proxmox VE node."
done

INTERACTIVE=1
if [[ "${WALLMOX_DEFAULTS:-0}" == "1" ]] || ! command -v whiptail >/dev/null || [[ ! -t 0 ]]; then
  INTERACTIVE=0
fi

TITLE="Wallmox installer"
ask_input() {   # ask_input "question" "default" -> prints answer
  whiptail --title "$TITLE" --inputbox "$1" 10 64 "$2" 3>&1 1>&2 2>&3
}
ask_password() {  # ask_password "question" -> prints answer
  whiptail --title "$TITLE" --passwordbox "$1" 10 64 3>&1 1>&2 2>&3
}
ask_menu() {    # ask_menu "question" "default" tag desc tag desc ...
  local q=$1 def=$2; shift 2
  whiptail --title "$TITLE" --default-item "$def" --menu "$q" 18 64 8 "$@" 3>&1 1>&2 2>&3
}

# ------------------------------------------------------------------ defaults

first_word() { awk 'NR>1 && $3=="active" {print $1; exit}'; }

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
CT_NAME="${CT_HOSTNAME:-wallmox}"   # not $HOSTNAME: bash sets that to the node name
DISK="${DISK:-4}"
RAM="${RAM:-512}"
CORES="${CORES:-1}"
BRIDGE="${BRIDGE:-vmbr0}"
NET="${NET:-dhcp}"
LANGUAGE="${LANGUAGE:-en}"
CT_PASSWORD="${CT_PASSWORD:-}"
DNS="${DNS:-}"
SEARCHDOMAIN="${SEARCHDOMAIN:-}"

mapfile -t ROOT_STORAGES < <(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')
[[ ${#ROOT_STORAGES[@]} -gt 0 ]] || die "No active storage can hold containers (content 'rootdir')."
STORAGE="${STORAGE:-}"
if [[ -z "$STORAGE" ]]; then
  STORAGE="${ROOT_STORAGES[0]}"
  for s in "${ROOT_STORAGES[@]}"; do [[ "$s" == "local-lvm" || "$s" == "local-zfs" ]] && STORAGE="$s"; done
fi

TPL_STORAGE="$(pvesm status -content vztmpl 2>/dev/null | first_word || true)"
[[ -n "$TPL_STORAGE" ]] || die "No active storage can hold templates (content 'vztmpl')."

# ------------------------------------------------------------------ questions

if [[ $INTERACTIVE -eq 1 ]]; then
  if ! whiptail --title "$TITLE" --yesno \
"This creates a small Debian container that runs Wallmox.

  Container ID: $CTID
  Hostname:     $CT_NAME
  Storage:      $STORAGE (${DISK} GB)
  Memory:       ${RAM} MB, ${CORES} core
  Network:      $BRIDGE, $NET

Use these settings? Choose No to change them.
Root password and DNS are asked next either way." 18 64; then

    CTID=$(ask_input "Container ID" "$CTID") || die "Cancelled."
    CT_NAME=$(ask_input "Hostname" "$CT_NAME") || die "Cancelled."
    menu=(); for s in "${ROOT_STORAGES[@]}"; do menu+=("$s" ""); done
    STORAGE=$(ask_menu "Storage for the container disk" "$STORAGE" "${menu[@]}") || die "Cancelled."
    DISK=$(ask_input "Disk size in GB" "$DISK") || die "Cancelled."
    RAM=$(ask_input "Memory in MB" "$RAM") || die "Cancelled."
    mapfile -t BRIDGES < <(ip -o link show type bridge | awk -F': ' '{print $2}' | cut -d@ -f1)
    menu=(); for b in "${BRIDGES[@]}"; do menu+=("$b" ""); done
    if [[ ${#menu[@]} -gt 0 ]]; then
      BRIDGE=$(ask_menu "Network bridge" "$BRIDGE" "${menu[@]}") || die "Cancelled."
    fi
    NET=$(ask_input "IP address: 'dhcp' or static like 192.168.0.50/24,gw=192.168.0.1" "$NET") || die "Cancelled."
  fi

  while :; do
    CT_PASSWORD=$(ask_password "Root password for the container.

Leave empty for no password (you can still get in with: pct enter $CTID).") || die "Cancelled."
    [[ -z "$CT_PASSWORD" ]] && break
    if [[ ${#CT_PASSWORD} -lt 5 ]]; then
      whiptail --title "$TITLE" --msgbox "The password needs at least 5 characters." 8 50; continue
    fi
    again=$(ask_password "Repeat the root password") || die "Cancelled."
    [[ "$again" == "$CT_PASSWORD" ]] && break
    whiptail --title "$TITLE" --msgbox "The passwords do not match. Try again." 8 50
  done

  DNS=$(ask_input "DNS servers, separated by spaces (e.g. 192.168.0.1 1.1.1.1).

Leave empty to use the same DNS as this Proxmox node." "$DNS") || die "Cancelled."
  SEARCHDOMAIN=$(ask_input "DNS search domain (e.g. home.lan).

Leave empty to use the same as this Proxmox node." "$SEARCHDOMAIN") || die "Cancelled."

  LANGUAGE=$(ask_menu "Language of the status page" "$LANGUAGE" en "English" sr "Srpski") || die "Cancelled."
fi

[[ "$CTID" =~ ^[0-9]+$ ]] || die "Container ID must be a number."
USED_IDS="$(pvesh get /cluster/resources --type vm --output-format json \
  | python3 -c 'import json,sys; print(" ".join(str(r.get("vmid")) for r in json.load(sys.stdin)))')"
[[ " $USED_IDS " == *" $CTID "* ]] && die "ID $CTID is already used by another VM or container."
[[ "$DISK" =~ ^[0-9]+$ && "$RAM" =~ ^[0-9]+$ ]] || die "Disk and memory must be numbers."

if [[ "$NET" == "dhcp" ]]; then
  NET0="name=eth0,bridge=$BRIDGE,ip=dhcp"
elif [[ "$NET" =~ ^[0-9.]+/[0-9]+(,gw=[0-9.]+)?$ ]]; then
  NET0="name=eth0,bridge=$BRIDGE,ip=$NET"
else
  die "Network must be 'dhcp' or like 192.168.0.50/24,gw=192.168.0.1"
fi

DNS="$(echo "$DNS" | tr ',' ' ' | xargs)"
for ip in $DNS; do
  [[ "$ip" =~ ^[0-9.]+$ || "$ip" =~ ^[0-9a-fA-F:]+$ ]] || die "Not a DNS server address: $ip"
done
[[ -z "$SEARCHDOMAIN" || "$SEARCHDOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "Not a valid search domain: $SEARCHDOMAIN"
DNS_OPTS=()
[[ -n "$DNS" ]] && DNS_OPTS+=(--nameserver "$DNS")
[[ -n "$SEARCHDOMAIN" ]] && DNS_OPTS+=(--searchdomain "$SEARCHDOMAIN")

# Address Wallmox uses to reach this node's API.
PVE_HOST="$(ip -4 -o addr show "$BRIDGE" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1 || true)"
[[ -n "$PVE_HOST" ]] || PVE_HOST="$(hostname -I | awk '{print $1}')"
[[ -n "$PVE_HOST" ]] || die "Could not find this node's IP address."

# ------------------------------------------------------------------ template

step "Debian template"
pveam update >/dev/null 2>&1 || warn "Could not refresh the template list, using the cached one."
TEMPLATE="$(pveam available --section system | awk '{print $2}' | grep -E '^debian-13-standard_.*amd64' | sort -V | tail -n1 || true)"
[[ -n "$TEMPLATE" ]] || TEMPLATE="$(pveam available --section system | awk '{print $2}' | grep -E '^debian-12-standard_.*amd64' | sort -V | tail -n1 || true)"
[[ -n "$TEMPLATE" ]] || die "No Debian 12 or 13 template found in 'pveam available'."
if pveam list "$TPL_STORAGE" | grep -F -- "/$TEMPLATE" >/dev/null; then
  ok "$TEMPLATE already downloaded"
else
  pveam download "$TPL_STORAGE" "$TEMPLATE" >/dev/null
  ok "Downloaded $TEMPLATE"
fi

# ------------------------------------------------------------------ API token

step "Read-only API token"
if ! pvesh get "/access/users/$PVE_USER" >/dev/null 2>&1; then
  pveum user add "$PVE_USER" --comment "Wallmox dashboard (read-only)"
  ok "Created user $PVE_USER"
fi
pveum acl modify / --users "$PVE_USER" --roles PVEAuditor
TOKEN_NAME="ct$CTID"
if pvesh get "/access/users/$PVE_USER/token/$TOKEN_NAME" >/dev/null 2>&1; then
  pveum user token remove "$PVE_USER" "$TOKEN_NAME"
fi
TOKEN_JSON="$(pveum user token add "$PVE_USER" "$TOKEN_NAME" --privsep 0 \
  --comment "Wallmox in CT $CTID" --output-format json)"
TOKEN_SECRET="$(python3 -c '
import json, re, sys
raw = sys.stdin.read()
try:
    print(json.loads(raw)["value"])
except Exception:
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", raw)
    print(m.group(0) if m else "")
' <<<"$TOKEN_JSON")"
[[ -n "$TOKEN_SECRET" ]] || die "Could not read the new API token."
ok "Token $PVE_USER!$TOKEN_NAME with role PVEAuditor"

# ------------------------------------------------------------------ container

step "Container $CTID"
pct create "$CTID" "$TPL_STORAGE:vztmpl/$TEMPLATE" \
  --hostname "$CT_NAME" --cores "$CORES" --memory "$RAM" --swap 256 \
  --rootfs "$STORAGE:$DISK" --net0 "$NET0" \
  --unprivileged 1 --features nesting=1 --onboot 1 "${DNS_OPTS[@]}" \
  --tags wallmox --description "Wallmox status dashboard - https://github.com/krajcara/wallmox" \
  >/dev/null
CREATED_CT="$CTID"
pct start "$CTID"
ok "Created and started"
if [[ -n "$CT_PASSWORD" ]]; then
  printf 'root:%s\n' "$CT_PASSWORD" | pct exec "$CTID" -- chpasswd
  ok "Root password set"
fi

printf '    waiting for network'
for _ in $(seq 1 45); do
  if pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1; then break; fi
  printf '.'; sleep 2
done
echo
pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 \
  || die "The container has no internet access. Check the bridge and IP settings."
ok "Network is up"

# ------------------------------------------------------------------ install

step "Installing Wallmox"
pct exec "$CTID" -- bash -c "export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq git ca-certificates python3 python3-venv >/dev/null"
pct exec "$CTID" -- git clone -q "$REPO" "$APP_DIR"
# shellcheck disable=SC2016  # expanded inside the container
pct exec "$CTID" -- bash -c '
  cd "$1" || exit 1
  ref="$2"
  [ -n "$ref" ] || ref=$(git tag -l "v*" --sort=-v:refname | head -n1)
  [ -n "$ref" ] || ref=main
  git -c advice.detachedHead=false checkout -q --detach "$ref" 2>/dev/null \
    || git -c advice.detachedHead=false checkout -q --detach "origin/$ref"
' _ "$APP_DIR" "$BRANCH"
INSTALLED_VER="$(pct exec "$CTID" -- sed -n 's/^__version__ = "\(.*\)"/\1/p' "$APP_DIR/wallmox/__init__.py")"
ok "Wallmox ${INSTALLED_VER:-} installed in $APP_DIR"

CONF_TMP="$(mktemp)"
chmod 600 "$CONF_TMP"
cat > "$CONF_TMP" <<EOF
# Written by the Wallmox installer. Most settings can be changed in the admin panel.
language = "$LANGUAGE"
listen = "0.0.0.0"
port = 8080

[proxmox]
host = "$PVE_HOST"
port = 8006
token_id = "$PVE_USER!$TOKEN_NAME"
token_secret = "$TOKEN_SECRET"
verify_ssl = false
EOF
pct push "$CTID" "$CONF_TMP" /etc/wallmox/config.toml --user 0 --group 0 --perms 640
rm -f "$CONF_TMP"
pct exec "$CTID" -- chgrp wallmox /etc/wallmox/config.toml

ADMIN_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
printf '%s\n' "$ADMIN_PASS" | pct exec "$CTID" -- runuser -u wallmox -- \
  env WALLMOX_CONFIG=/etc/wallmox/config.toml WALLMOX_DATA=/var/lib/wallmox \
  "$APP_DIR/venv/bin/python" -m wallmox set-password --stdin >/dev/null
pct exec "$CTID" -- systemctl restart wallmox
ok "Service started"

# ------------------------------------------------------------------ check

step "Checking"
CT_IP=""
for _ in $(seq 1 20); do
  CT_IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -n "$CT_IP" ]] && pct exec "$CTID" -- bash -c "exec 3<>/dev/tcp/127.0.0.1/8080" 2>/dev/null; then
    break
  fi
  sleep 2
done
HEALTH="$(pct exec "$CTID" -- python3 -c '
import urllib.request, time
for _ in range(10):
    try:
        print(urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=3).read().decode()); break
    except Exception:
        time.sleep(2)
else:
    print("no answer")' 2>/dev/null || true)"
if [[ "$HEALTH" == *'"ok":true'* ]]; then
  ok "Wallmox reads data from Proxmox"
else
  warn "Wallmox runs, but has no Proxmox data yet. Check the connection in the admin panel."
fi
CREATED_CT=""

cat <<EOF

${C_OK}${C_B}Wallmox is installed.${C_0}

  Status page (tablet):   ${C_B}http://$CT_IP:8080/status${C_0}
  Admin panel:            ${C_B}http://$CT_IP:8080/admin${C_0}
  Admin password:         ${C_B}$ADMIN_PASS${C_0}

${C_DIM}Save the admin password now, it is not shown again. Change it in the admin
panel under Access. Container: $CTID ($CT_NAME). Token: $PVE_USER!$TOKEN_NAME.${C_0}

To update later, open the container console (or: pct enter $CTID) and run:  ${C_B}update${C_0}
EOF
