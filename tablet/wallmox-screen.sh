#!/usr/bin/env bash
# Wallmox screen helper for Linux kiosk tablets:
#  - sets the backlight by the night mode schedule from the Wallmox admin panel
#  - reports the tablet's battery, charger and WiFi signal to Wallmox
# Settings: /etc/wallmox-screen.conf (URL=..., KEY=..., DEVICE=..., INTERVAL=...)
HELPER_VERSION="0.6.0"
set -u

CONF="${WALLMOX_SCREEN_CONF:-/etc/wallmox-screen.conf}"
BL_DIR="${WALLMOX_BACKLIGHT_DIR:-/sys/class/backlight}"   # overridable for tests
PS_DIR="${WALLMOX_POWER_DIR:-/sys/class/power_supply}"
WIRELESS="${WALLMOX_WIRELESS_FILE:-/proc/net/wireless}"
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
WARNED=0

to_min() { local h=${1%%:*} m=${1##*:}; echo $(( 10#$h * 60 + 10#$m )); }

# Tablet status -> curl form fields (REPORT array)
collect_status() {
  local ps type bat="" bstat="" btemp="" mains="" iface="" link="" level=""
  for ps in "$PS_DIR"/*; do
    [[ -r "$ps/type" ]] || continue
    read -r type < "$ps/type" || continue
    case "$type" in
      Battery)
        if [[ -z "$bat" ]]; then
          read -r bat < "$ps/capacity" 2>/dev/null || bat=""
          read -r bstat < "$ps/status" 2>/dev/null || bstat=""
          read -r btemp < "$ps/temp" 2>/dev/null || btemp=""
        fi ;;
      Mains|USB*)
        local online=""
        read -r online < "$ps/online" 2>/dev/null || online=""
        if [[ "$online" == "1" ]]; then mains=1; elif [[ -z "$mains" ]]; then mains=0; fi ;;
    esac
  done
  # /proc/net/wireless: "wlan0: 0000   58.  -52.  -256 ..."
  if [[ -r "$WIRELESS" ]]; then
    read -r iface _ link level _ < <(awk -F'[: ]+' 'NR>2 {sub(/^ +/, ""); print}' "$WIRELESS" | head -n1)
  fi
  REPORT=(--data-urlencode "host=$(hostname)" --data-urlencode "v=$HELPER_VERSION"
          --data-urlencode "battery=$bat" --data-urlencode "bat_status=$bstat"
          --data-urlencode "bat_temp=$btemp" --data-urlencode "mains=$mains"
          --data-urlencode "wifi=${iface%:}" --data-urlencode "link=${link%.}"
          --data-urlencode "signal=${level%.}")
}

echo "wallmox-screen: controlling $BL (max $MAX), asking $URL every ${INTERVAL}s"
while true; do
  query="format=env"; [[ -n "$KEY" ]] && query="$query&key=$KEY"
  # -L follows a redirect (e.g. http -> https behind a reverse proxy)
  # POST = report the tablet's status and get the schedule back in one request
  collect_status
  if resp="$(curl -fsSL --post301 --post302 --post303 --max-time 10 "${REPORT[@]}" \
               "$URL/api/night?$query")" && grep -q '^METHOD=' <<< "$resp"; then
    [[ "$WARNED" == "1" ]] && echo "schedule received again from $URL"
    WARNED=0
    while IFS='=' read -r k v; do
      case "$k" in
        ENABLED) ENABLED="$v" ;; START) START="$v" ;; END) END="$v" ;; MODE) MODE="$v" ;;
        NIGHT_LEVEL) NIGHT_LEVEL="$v" ;; DAY_LEVEL) DAY_LEVEL="$v" ;; METHOD) METHOD="$v" ;;
      esac
    done <<< "$resp"
  elif [[ "$WARNED" != "1" ]]; then
    echo "no schedule from $URL/api/night (wrong address or status page key?), keeping the last one" >&2
    WARNED=1
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
