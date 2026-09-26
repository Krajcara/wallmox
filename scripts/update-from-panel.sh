#!/usr/bin/env bash
# Runs as root when the admin panel asks for an update (see wallmox-update.path).
# The web app never gets root rights: it only drops a request file, and this
# script runs the same fixed "update" command you would type in the console.
set -uo pipefail

DIR="/var/lib/wallmox/update"
LOG="$DIR/log"
STATE="$DIR/state.json"

rm -f "$DIR/request"          # consume the request first, so the path unit won't loop

state() {  # state <running|done|failed> [exit code]
  printf '{"state": "%s", "time": %s, "exit": %s}\n' "$1" "$(date +%s)" "${2:-null}" > "$STATE.tmp"
  mv "$STATE.tmp" "$STATE"
  chmod 644 "$STATE" "$LOG" 2>/dev/null || true
}

: > "$LOG"
state "running"
/usr/bin/update >> "$LOG" 2>&1
rc=$?
if [[ $rc -eq 0 ]]; then state "done" 0; else state "failed" "$rc"; fi
exit 0
