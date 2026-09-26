#!/usr/bin/env bash
# Wallmox screen helper: sets the tablet's backlight by the night mode schedule
# from the Wallmox admin panel. For Linux kiosk tablets with /sys/class/backlight.
# Settings: /etc/wallmox-screen.conf (URL=..., KEY=..., DEVICE=..., INTERVAL=...)
set -u

CONF="${WALLMOX_SCREEN_CONF:-/etc/wallmox-screen.conf}"
BL_DIR="${WALLMOX_BACKLIGHT_DIR:-/sys/class/backlight}"   # overridable for tests
URL=""; KEY=""; DEVICE=""; INTERVAL=60
while IFS='=' read -r k v; do
  case "$k" in
    URL) URL="$v" ;; KEY) KEY="$v" ;; DEVICE) DEVICE="$v" ;; INTERVAL) INTERVAL="$v" ;;
  esac
done < <(grep -E '^[A-Z]+=' "$CONF" 2>/dev/null)

[[ -n "$URL" ]] || { echo "URL is not set in $CONF" >&2; exit 1; }
if [[ -z "$DEVICE" ]]; then
  DEVICE="$(find "$BL_DIR" -mindepth 1 -maxdepth 1 \( -type l -o -type d \) 2>/dev/null | sort | head -n1)"
  DEVICE="${DEVICE##*/}"
fi
BL="$BL_DIR/$DEVICE"
[[ -n "$DEVICE" && -w "$BL/brightness" ]] || { echo "No writable backlight found ($BL)" >&2; exit 1; }
MAX="$(cat "$BL/max_brightness")"

# last known schedule, used while Wallmox cannot be reached
ENABLED=0; START="22:00"; END="07:00"; MODE="dim"; NIGHT_LEVEL=20; DAY_LEVEL=100; METHOD="overlay"
LAST=""

to_min() { local h=${1%%:*} m=${1##*:}; echo $(( 10#$h * 60 + 10#$m )); }

echo "wallmox-screen: controlling $BL (max $MAX), asking $URL every ${INTERVAL}s"
while true; do
  query="format=env"; [[ -n "$KEY" ]] && query="$query&key=$KEY"
  if resp="$(curl -fsS --max-time 10 "$URL/api/night?$query")"; then
    while IFS='=' read -r k v; do
      case "$k" in
        ENABLED) ENABLED="$v" ;; START) START="$v" ;; END) END="$v" ;; MODE) MODE="$v" ;;
        NIGHT_LEVEL) NIGHT_LEVEL="$v" ;; DAY_LEVEL) DAY_LEVEL="$v" ;; METHOD) METHOD="$v" ;;
      esac
    done <<< "$resp"
  fi

  level="$DAY_LEVEL"
  if [[ "$ENABLED" == "1" && "$METHOD" == "backlight" ]]; then
    now=$(( 10#$(date +%H) * 60 + 10#$(date +%M) ))
    s=$(to_min "$START"); e=$(to_min "$END")
    night=0
    if (( s < e )); then (( now >= s && now < e )) && night=1
    elif (( s > e )); then (( now >= s || now < e )) && night=1
    fi
    if (( night )); then
      if [[ "$MODE" == "off" ]]; then level=0; else level="$NIGHT_LEVEL"; fi
    fi
  fi

  value=$(( MAX * level / 100 ))
  (( level > 0 && value < 1 )) && value=1
  if [[ "$value" != "$LAST" ]]; then
    echo "$value" > "$BL/brightness" && LAST="$value" && echo "brightness $level% ($value/$MAX)"
  fi
  sleep "$INTERVAL"
done
