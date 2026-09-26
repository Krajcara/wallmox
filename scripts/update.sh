#!/usr/bin/env bash
# Wallmox updater. Run inside the Wallmox container as root:  update
#
#   update            install the newest release (or main if there are no releases)
#   update --main     install the latest code from the main branch
#   update --check    only show whether a newer version exists
#
# Settings are backed up first. If the new version does not start,
# the previous version is restored automatically.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/wallmox}"
DATA_DIR="/var/lib/wallmox"
PORT="${WALLMOX_PORT:-8080}"

# Run from a copy, because "git checkout" below replaces this very file.
if [[ "${WALLMOX_UPDATE_COPY:-}" != "1" ]]; then
  tmp="$(mktemp /tmp/wallmox-update.XXXXXX)"
  cp "$0" "$tmp"
  WALLMOX_UPDATE_COPY=1 exec bash "$tmp" "$@"
fi
trap 'rm -f "$0"' EXIT

if [[ -t 1 ]]; then
  C_OK=$'\e[32m'; C_WARN=$'\e[33m'; C_ERR=$'\e[31m'; C_B=$'\e[1m'; C_0=$'\e[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_B=""; C_0=""
fi
step() { printf '%s==>%s %s\n' "$C_B" "$C_0" "$*"; }
ok()   { printf '    %s✓%s %s\n' "$C_OK" "$C_0" "$*"; }
warn() { printf '    %s!%s %s\n' "$C_WARN" "$C_0" "$*"; }
die()  { printf '%sError:%s %s\n' "$C_ERR" "$C_0" "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root."
[[ -d "$APP_DIR/.git" ]] || die "$APP_DIR is not a git checkout, cannot update."

MODE="release"
case "${1:-}" in
  --main)  MODE="main" ;;
  --check) MODE="check" ;;
  "")      ;;
  -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) die "Unknown option: $1 (use --main or --check)" ;;
esac

cd "$APP_DIR"
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true

version_of() {  # version_of <git-ref>
  git show "$1:wallmox/__init__.py" 2>/dev/null | sed -n 's/^__version__ = "\(.*\)"/\1/p'
}

app_answers() {  # the web server answers at all (healthz may be 503 if Proxmox is down)
  python3 - "$PORT" <<'PY'
import sys, time, urllib.request, urllib.error
url = f"http://127.0.0.1:{sys.argv[1]}/healthz"
for _ in range(20):
    try:
        urllib.request.urlopen(url, timeout=3)
        sys.exit(0)
    except urllib.error.HTTPError:
        sys.exit(0)          # 503 still means Wallmox is running
    except Exception:
        time.sleep(1.5)
sys.exit(1)
PY
}

step "Checking for updates"
# --prune-tags drops local tags that were deleted on GitHub (e.g. a release made twice)
git fetch -q --tags --force --prune --prune-tags origin
CURRENT_REF="$(git rev-parse HEAD)"
CURRENT_VER="$(version_of HEAD)"

# newest release tag, "v1.2.3" or "V1.2.3"
LATEST_TAG="$(git tag -l '[vV][0-9]*' | sed 's/^[vV]\(.*\)$/\1 &/' | sort -V | tail -n1 | cut -d' ' -f2 || true)"
if [[ "$MODE" == "main" || -z "$LATEST_TAG" ]]; then
  TARGET="origin/main"
else
  TARGET="$LATEST_TAG"
fi
TARGET_REF="$(git rev-parse "$TARGET^{commit}")"
TARGET_VER="$(version_of "$TARGET_REF")"

echo "    installed: ${CURRENT_VER:-?} (${CURRENT_REF:0:7})"
echo "    available: ${TARGET_VER:-?} (${TARGET_REF:0:7}, $TARGET)"

if [[ "$CURRENT_REF" == "$TARGET_REF" ]]; then
  ok "Wallmox is up to date."
  exit 0
fi
if git merge-base --is-ancestor "$TARGET_REF" "$CURRENT_REF"; then
  ok "The installed version is newer than $TARGET. Nothing to do."
  [[ "$MODE" == "main" ]] || echo "    (for the latest development code run: update --main)"
  exit 0
fi
if [[ "$MODE" == "check" ]]; then
  ok "An update is available. Run: update"
  exit 0
fi

step "Backing up settings"
BACKUP_DIR="$DATA_DIR/backups"
install -d -o wallmox -g wallmox -m 750 "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
[[ -f "$DATA_DIR/settings.json" ]] && cp -p "$DATA_DIR/settings.json" "$BACKUP_DIR/settings-$STAMP.json"
cp -p /etc/wallmox/config.toml "$BACKUP_DIR/config-$STAMP.toml" 2>/dev/null || true
# keep the 10 newest backups of each kind
for kind in settings config; do
  { ls -1t "$BACKUP_DIR"/"$kind"-*.* 2>/dev/null || true; } | tail -n +11 | xargs -r rm -f
done
ok "Saved in $BACKUP_DIR"

install_ref() {   # explicit returns: "set -e" is off inside an "if" condition
  git -c advice.detachedHead=false checkout -q -f --detach "$1" || return 1
  bash "$APP_DIR/scripts/setup-container.sh" >/dev/null || return 1
  systemctl restart wallmox || return 1
}

step "Installing ${TARGET_VER:-$TARGET}"
if install_ref "$TARGET_REF" && app_answers; then
  ok "Wallmox ${TARGET_VER:-} is running."
  exit 0
fi

warn "The new version did not start. Restoring ${CURRENT_VER:-the previous version}."
install_ref "$CURRENT_REF" || true
if app_answers; then
  warn "Restored ${CURRENT_VER:-previous version}. Logs of the failed start: journalctl -u wallmox -n 50"
else
  die "Wallmox does not start. See: journalctl -u wallmox -n 50"
fi
exit 1
