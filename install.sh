#!/usr/bin/env bash
# Wallmox installer for Proxmox VE.
#
# Run in the shell of a Proxmox node, as root:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/krajcara/wallmox/main/install.sh)"
#
# Creates an unprivileged Debian LXC, installs the newest Wallmox release in it
# and prints the addresses and the admin password. The Proxmox connection is
# set up afterwards in the admin panel.
#
# Every question has a default. For unattended installs set WALLMOX_DEFAULTS=1
# and override any of these variables:
#   CTID CT_HOSTNAME STORAGE TPL_STORAGE DISK RAM CORES BRIDGE
#   CT_IP (empty = DHCP, or 192.168.0.50/24)  CT_GW  DNS  SEARCHDOMAIN
#   CT_PASSWORD  SSH (none|password|key)  SSH_KEY  LANGUAGE (en|sr)
# WALLMOX_BRANCH=main installs the latest code instead of the newest release.
# Later updates: run "update" inside the container.
set -Eeuo pipefail

REPO="${WALLMOX_REPO:-https://github.com/krajcara/wallmox.git}"
BRANCH="${WALLMOX_BRANCH:-}"      # empty = newest release tag, or main if there is none
APP_DIR="/opt/wallmox"
PORT=8080

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
ERROR_SHOWN=0
on_error() {
  [[ $ERROR_SHOWN -eq 1 ]] && return
  ERROR_SHOWN=1
  printf '\n%sThe installer stopped at line %s.%s\n' "$C_ERR" "$1" "$C_0" >&2
  if [[ -n "$CREATED_CT" ]]; then
    printf 'Container %s was created. Remove it with:  pct stop %s; pct destroy %s\n' \
      "$CREATED_CT" "$CREATED_CT" "$CREATED_CT" >&2
  fi
}
trap 'on_error $LINENO' ERR

# ------------------------------------------------------------------ checks

[[ $EUID -eq 0 ]] || die "Run this as root."
for cmd in pct pveam pvesh pvesm python3; do
  command -v "$cmd" >/dev/null || die "'$cmd' not found. Run this on a Proxmox VE node."
done

INTERACTIVE=1
if [[ "${WALLMOX_DEFAULTS:-0}" == "1" ]] || ! command -v whiptail >/dev/null || [[ ! -t 0 ]]; then
  INTERACTIVE=0
fi

TITLE="Wallmox installer"
ask_input()    { whiptail --title "$TITLE" --inputbox "$1" 12 70 "$2" 3>&1 1>&2 2>&3; }
ask_password() { whiptail --title "$TITLE" --passwordbox "$1" 12 70 3>&1 1>&2 2>&3; }
ask_menu() {   # ask_menu "question" "default" tag desc tag desc ...
  local q=$1 def=$2; shift 2
  whiptail --title "$TITLE" --default-item "$def" --menu "$q" 18 70 8 "$@" 3>&1 1>&2 2>&3
}
say() { whiptail --title "$TITLE" --msgbox "$1" 10 64; }

# Run a command in the container with a locale that always exists.
ct() { pct exec "$CTID" -- env LANG=C.UTF-8 LC_ALL=C.UTF-8 "$@"; }

is_ipv4()      { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }
is_ipv4_cidr() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]]; }

# ------------------------------------------------------------------ defaults

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
CT_NAME="${CT_HOSTNAME:-wallmox}"   # not $HOSTNAME: bash sets that to the node name
DISK="${DISK:-4}"
RAM="${RAM:-512}"
CORES="${CORES:-1}"
BRIDGE="${BRIDGE:-vmbr0}"
CT_IP="${CT_IP:-}"
CT_GW="${CT_GW:-}"
DNS="${DNS:-}"
SEARCHDOMAIN="${SEARCHDOMAIN:-}"
CT_PASSWORD="${CT_PASSWORD:-}"
SSH="${SSH:-none}"
SSH_KEY="${SSH_KEY:-}"
LANGUAGE="${LANGUAGE:-en}"

mapfile -t ROOT_STORAGES < <(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')
[[ ${#ROOT_STORAGES[@]} -gt 0 ]] || die "No active storage can hold containers (content 'rootdir')."
STORAGE="${STORAGE:-}"
if [[ -z "$STORAGE" ]]; then
  STORAGE="${ROOT_STORAGES[0]}"
  for s in "${ROOT_STORAGES[@]}"; do [[ "$s" == "local-lvm" || "$s" == "local-zfs" ]] && STORAGE="$s"; done
fi

mapfile -t TPL_STORAGES < <(pvesm status -content vztmpl 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')
[[ ${#TPL_STORAGES[@]} -gt 0 ]] || die "No active storage can hold templates (content 'vztmpl')."

# ------------------------------------------------------------------ template

step "Looking for a Debian template"
pveam update >/dev/null 2>&1 || warn "Could not refresh the template list, using the cached one."
TEMPLATE="$(pveam available --section system | awk '{print $2}' | grep -E '^debian-13-standard_.*amd64' | sort -V | tail -n1 || true)"
[[ -n "$TEMPLATE" ]] || TEMPLATE="$(pveam available --section system | awk '{print $2}' | grep -E '^debian-12-standard_.*amd64' | sort -V | tail -n1 || true)"
[[ -n "$TEMPLATE" ]] || die "No Debian 12 or 13 template found in 'pveam available'."

TPL_STORAGE="${TPL_STORAGE:-}"
TPL_PRESENT=0
for s in "${TPL_STORAGES[@]}"; do
  if pveam list "$s" 2>/dev/null | grep -F -- "/$TEMPLATE" >/dev/null; then
    TPL_STORAGE="$s"; TPL_PRESENT=1; break
  fi
done
if [[ $TPL_PRESENT -eq 1 ]]; then
  ok "$TEMPLATE found on $TPL_STORAGE"
else
  ok "$TEMPLATE will be downloaded"
  [[ -n "$TPL_STORAGE" ]] || TPL_STORAGE="${TPL_STORAGES[0]}"
fi

# ------------------------------------------------------------------ questions

if [[ $INTERACTIVE -eq 1 ]]; then
  # Container resources
  if ! whiptail --title "$TITLE" --yesno \
"Container settings:

  Container ID:  $CTID
  Hostname:      $CT_NAME
  Disk:          $STORAGE, ${DISK} GB
  Memory:        ${RAM} MB, ${CORES} core
  Bridge:        $BRIDGE

Use these? Choose No to change them.
Network, DNS, root password and SSH are asked next." 18 64; then
    CTID=$(ask_input "Container ID" "$CTID") || die "Cancelled."
    CT_NAME=$(ask_input "Hostname" "$CT_NAME") || die "Cancelled."
    menu=(); for s in "${ROOT_STORAGES[@]}"; do menu+=("$s" ""); done
    STORAGE=$(ask_menu "Storage for the container disk" "$STORAGE" "${menu[@]}") || die "Cancelled."
    DISK=$(ask_input "Disk size in GB" "$DISK") || die "Cancelled."
    RAM=$(ask_input "Memory in MB" "$RAM") || die "Cancelled."
    CORES=$(ask_input "CPU cores" "$CORES") || die "Cancelled."
    mapfile -t BRIDGES < <(ip -o link show type bridge 2>/dev/null | awk -F': ' '{print $2}' | cut -d@ -f1 || true)
    menu=(); for b in "${BRIDGES[@]}"; do menu+=("$b" ""); done
    if [[ ${#menu[@]} -gt 0 ]]; then
      BRIDGE=$(ask_menu "Network bridge" "$BRIDGE" "${menu[@]}") || die "Cancelled."
    fi
  fi

  # Template storage, only when the template still has to be downloaded
  if [[ $TPL_PRESENT -eq 0 && ${#TPL_STORAGES[@]} -gt 1 ]]; then
    menu=(); for s in "${TPL_STORAGES[@]}"; do menu+=("$s" ""); done
    TPL_STORAGE=$(ask_menu "The Debian template is not downloaded yet.
Where should it be stored?" "$TPL_STORAGE" "${menu[@]}") || die "Cancelled."
  fi

  # Network
  mode=$(ask_menu "IP address of the container" "$([[ -n "$CT_IP" ]] && echo static || echo dhcp)" \
    dhcp "Automatic (DHCP)" static "Static IP address") || die "Cancelled."
  if [[ "$mode" == "static" ]]; then
    while :; do
      CT_IP=$(ask_input "IP address with prefix, e.g. 192.168.0.12/24" "${CT_IP:-}") || die "Cancelled."
      is_ipv4 "$CT_IP" && CT_IP="$CT_IP/24"
      is_ipv4_cidr "$CT_IP" && break
      say "That is not an IP address like 192.168.0.12/24."
    done
    while :; do
      guess="${CT_GW:-$(echo "${CT_IP%/*}" | awk -F. '{print $1"."$2"."$3".1"}')}"
      CT_GW=$(ask_input "Gateway, e.g. 192.168.0.1" "$guess") || die "Cancelled."
      is_ipv4 "$CT_GW" && break
      say "That is not a gateway address like 192.168.0.1."
    done
  else
    CT_IP=""; CT_GW=""
  fi

  # DNS
  DNS=$(ask_input "DNS servers, separated by spaces (e.g. 192.168.0.1 1.1.1.1).

Leave empty to use the same DNS as this Proxmox node." "$DNS") || die "Cancelled."
  SEARCHDOMAIN=$(ask_input "DNS search domain (e.g. home.lan).

Leave empty to use the same as this Proxmox node." "$SEARCHDOMAIN") || die "Cancelled."

  # SSH
  SSH=$(ask_menu "SSH access for root" "$SSH" \
    none     "No SSH (use the Proxmox console)" \
    password "Log in with the root password" \
    key      "Log in with an SSH key only") || die "Cancelled."
  if [[ "$SSH" == "key" ]]; then
    while :; do
      SSH_KEY=$(ask_input "Paste your public SSH key, or the path of a key file on this node
(e.g. /root/.ssh/authorized_keys)." "${SSH_KEY:-/root/.ssh/authorized_keys}") || die "Cancelled."
      [[ -f "$SSH_KEY" ]] && SSH_KEY="$(grep -E '^(ssh-|ecdsa-|sk-)' "$SSH_KEY" || true)"
      [[ "$SSH_KEY" =~ ^(ssh-|ecdsa-|sk-) ]] && break
      say "No public key found. A key starts with ssh-ed25519, ssh-rsa or ecdsa-."
    done
  fi

  # Root password (required when SSH uses passwords)
  while :; do
    if [[ "$SSH" == "password" ]]; then
      prompt="Root password for the container. You will use it for SSH."
    else
      prompt="Root password for the container.

Leave empty for no password (the Proxmox console still works: pct enter $CTID)."
    fi
    CT_PASSWORD=$(ask_password "$prompt") || die "Cancelled."
    if [[ -z "$CT_PASSWORD" ]]; then
      [[ "$SSH" != "password" ]] && break
      say "SSH with a password needs a root password."; continue
    fi
    if [[ ${#CT_PASSWORD} -lt 5 ]]; then say "The password needs at least 5 characters."; continue; fi
    again=$(ask_password "Repeat the root password") || die "Cancelled."
    [[ "$again" == "$CT_PASSWORD" ]] && break
    say "The passwords do not match. Try again."
  done

  LANGUAGE=$(ask_menu "Language of the status page and admin panel" "$LANGUAGE" \
    en "English" sr "Srpski") || die "Cancelled."
fi

# ------------------------------------------------------------------ validation

[[ "$CTID" =~ ^[0-9]+$ ]] || die "Container ID must be a number."
USED_IDS="$(pvesh get /cluster/resources --type vm --output-format json \
  | python3 -c 'import json,sys; print(" ".join(str(r.get("vmid")) for r in json.load(sys.stdin)))')"
[[ " $USED_IDS " == *" $CTID "* ]] && die "ID $CTID is already used by another VM or container."
[[ "$DISK" =~ ^[0-9]+$ && "$RAM" =~ ^[0-9]+$ && "$CORES" =~ ^[0-9]+$ ]] || die "Disk, memory and cores must be numbers."
[[ "$CT_NAME" =~ ^[A-Za-z0-9-]+$ ]] || die "Hostname may only contain letters, digits and dashes."

if [[ -z "$CT_IP" ]]; then
  NET0="name=eth0,bridge=$BRIDGE,ip=dhcp"
else
  is_ipv4 "$CT_IP" && CT_IP="$CT_IP/24"
  is_ipv4_cidr "$CT_IP" || die "CT_IP must look like 192.168.0.12/24"
  NET0="name=eth0,bridge=$BRIDGE,ip=$CT_IP"
  if [[ -n "$CT_GW" ]]; then
    is_ipv4 "$CT_GW" || die "CT_GW must look like 192.168.0.1"
    NET0="$NET0,gw=$CT_GW"
  fi
fi

DNS="$(echo "$DNS" | tr ',' ' ' | xargs)"
for ip in $DNS; do
  [[ "$ip" =~ ^[0-9.]+$ || "$ip" =~ ^[0-9a-fA-F:]+$ ]] || die "Not a DNS server address: $ip"
done
[[ -z "$SEARCHDOMAIN" || "$SEARCHDOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "Not a valid search domain: $SEARCHDOMAIN"
DNS_OPTS=()
[[ -n "$DNS" ]] && DNS_OPTS+=(--nameserver "$DNS")
[[ -n "$SEARCHDOMAIN" ]] && DNS_OPTS+=(--searchdomain "$SEARCHDOMAIN")

case "$SSH" in
  none) ;;
  password) [[ -n "$CT_PASSWORD" ]] || die "SSH=password needs CT_PASSWORD." ;;
  key) [[ "$SSH_KEY" =~ ^(ssh-|ecdsa-|sk-) ]] || die "SSH=key needs a public key in SSH_KEY." ;;
  *) die "SSH must be none, password or key." ;;
esac
[[ "$LANGUAGE" == "en" || "$LANGUAGE" == "sr" ]] || LANGUAGE="en"

# ------------------------------------------------------------------ create

if [[ $TPL_PRESENT -eq 0 ]]; then
  step "Downloading $TEMPLATE to $TPL_STORAGE"
  pveam download "$TPL_STORAGE" "$TEMPLATE" >/dev/null
  ok "Downloaded"
fi

step "Container $CTID"
pct create "$CTID" "$TPL_STORAGE:vztmpl/$TEMPLATE" \
  --hostname "$CT_NAME" --cores "$CORES" --memory "$RAM" --swap 256 \
  --rootfs "$STORAGE:$DISK" --net0 "$NET0" "${DNS_OPTS[@]}" \
  --unprivileged 1 --features nesting=1 --onboot 1 \
  --tags wallmox --description "Wallmox status dashboard - https://github.com/krajcara/wallmox" \
  >/dev/null
CREATED_CT="$CTID"
pct start "$CTID"
ok "Created and started"

printf '    waiting for network'
for _ in $(seq 1 45); do
  if ct getent hosts deb.debian.org >/dev/null 2>&1; then break; fi
  printf '.'; sleep 2
done
echo
ct getent hosts deb.debian.org >/dev/null 2>&1 \
  || die "The container has no internet access. Check the IP, gateway and DNS settings."
ok "Network is up"

if [[ -n "$CT_PASSWORD" ]]; then
  printf 'root:%s\n' "$CT_PASSWORD" | ct chpasswd
  ok "Root password set"
fi

# ------------------------------------------------------------------ install

step "Installing packages"
PKGS=(git ca-certificates python3 python3-venv)
[[ "$SSH" != "none" ]] && PKGS+=(openssh-server)
ct bash -c 'export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq "$@" >/dev/null' _ "${PKGS[@]}"
ok "${PKGS[*]}"

step "Installing Wallmox"
ct git clone -q "$REPO" "$APP_DIR"
# shellcheck disable=SC2016  # expanded inside the container
ct bash -c '
  cd "$1" || exit 1
  ref="$2"
  [ -n "$ref" ] || ref=$(git tag -l "[vV][0-9]*" | sed "s/^[vV]\(.*\)$/\1 &/" | sort -V | tail -n1 | cut -d" " -f2)
  [ -n "$ref" ] || ref=main
  git -c advice.detachedHead=false checkout -q --detach "$ref" 2>/dev/null \
    || git -c advice.detachedHead=false checkout -q --detach "origin/$ref"
' _ "$APP_DIR" "$BRANCH"
INSTALLED_VER="$(ct sed -n 's/^__version__ = "\(.*\)"/\1/p' "$APP_DIR/wallmox/__init__.py")"

if ! ct bash -c "bash '$APP_DIR/scripts/setup-container.sh' > /var/log/wallmox-install.log 2>&1"; then
  ct tail -n 25 /var/log/wallmox-install.log >&2 || true
  die "Setting up the app failed (log above, full log: /var/log/wallmox-install.log in the container)."
fi
ct test -f /etc/wallmox/config.toml || die "Setup finished but /etc/wallmox/config.toml is missing."
ct id wallmox >/dev/null || die "Setup finished but the user 'wallmox' is missing."
ok "Wallmox ${INSTALLED_VER:-} installed in $APP_DIR"

CONF_TMP="$(mktemp)"
cat > "$CONF_TMP" <<EOF
# Written by the Wallmox installer.
# Set up the Proxmox connection and everything else in the admin panel.
language = "$LANGUAGE"
listen = "0.0.0.0"
port = $PORT
EOF
pct push "$CTID" "$CONF_TMP" /etc/wallmox/config.toml --perms 640
rm -f "$CONF_TMP"
ct chown root:wallmox /etc/wallmox/config.toml

ADMIN_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
printf '%s\n' "$ADMIN_PASS" | ct /usr/bin/wallmox set-password --stdin >/dev/null
ct systemctl restart wallmox
ok "Admin password set, service started"

# ------------------------------------------------------------------ ssh

if [[ "$SSH" == "none" ]]; then
  ct bash -c 'systemctl disable --now ssh >/dev/null 2>&1 || true'
else
  step "SSH"
  if [[ "$SSH" == "password" ]]; then
    ct bash -c 'printf "PermitRootLogin yes\nPasswordAuthentication yes\n" > /etc/ssh/sshd_config.d/wallmox.conf'
  else
    KEY_TMP="$(mktemp)"
    printf '%s\n' "$SSH_KEY" > "$KEY_TMP"
    ct install -d -m 700 /root/.ssh
    pct push "$CTID" "$KEY_TMP" /root/.ssh/authorized_keys --perms 600
    rm -f "$KEY_TMP"
    ct bash -c 'printf "PermitRootLogin prohibit-password\nPasswordAuthentication no\n" > /etc/ssh/sshd_config.d/wallmox.conf'
  fi
  ct systemctl enable ssh >/dev/null 2>&1
  ct systemctl restart ssh
  ok "Root login with $([[ "$SSH" == "password" ]] && echo password || echo key) enabled"
fi

# ------------------------------------------------------------------ check

step "Checking"
CT_ADDR=""
for _ in $(seq 1 20); do
  CT_ADDR="$(ct hostname -I 2>/dev/null | awk '{print $1}' || true)"
  [[ -n "$CT_ADDR" ]] && break
  sleep 2
done
if ct python3 - "$PORT" <<'PY'
import sys, time, urllib.request, urllib.error
for _ in range(20):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/admin/login", timeout=3)
        sys.exit(0)
    except urllib.error.HTTPError:
        sys.exit(0)
    except Exception:
        time.sleep(1.5)
sys.exit(1)
PY
then
  ok "Wallmox answers on port $PORT"
else
  warn "Wallmox does not answer yet. Check: pct enter $CTID, then journalctl -u wallmox -n 50"
fi
CREATED_CT=""

CT_ADDR="${CT_ADDR:-<container-ip>}"
cat <<EOF

${C_OK}${C_B}Wallmox ${INSTALLED_VER:-} is installed.${C_0}

  Admin panel:     ${C_B}http://$CT_ADDR:$PORT/admin${C_0}
  Admin password:  ${C_B}$ADMIN_PASS${C_0}
  Status page:     http://$CT_ADDR:$PORT/status   (for the tablet)
EOF
case "$SSH" in
  password) echo "  SSH:             ssh root@$CT_ADDR  (root password)" ;;
  key)      echo "  SSH:             ssh root@$CT_ADDR  (your key)" ;;
esac
cat <<EOF

${C_B}Next step:${C_0} open the admin panel and set up the Proxmox connection.
It shows the three commands that create a read-only API token.

${C_DIM}Save the admin password now, it is not shown again. You can change it in
the admin panel under Access. Container: $CTID ($CT_NAME).${C_0}

To update later, open the container console (or: pct enter $CTID) and run:  ${C_B}update${C_0}
EOF
