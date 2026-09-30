#!/usr/bin/env python3
"""Wallmox power button guard for Linux kiosk tablets.

A short press on the power button no longer shuts the tablet down: Wallmox
shows "hold the button for N seconds to turn the tablet off" on the screen.
Holding the button for N seconds shuts the tablet down.

systemd-logind is told to ignore the power button (the installer adds a
logind.conf.d drop-in), and this program reads the button itself from
/dev/input. Settings come from /etc/wallmox-screen.conf (URL, KEY, HOLD).
Standard library only.
"""

import os
import select
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

VERSION = "0.7.0"
CONF = os.environ.get("WALLMOX_SCREEN_CONF", "/etc/wallmox-screen.conf")
DEVICES = os.environ.get("WALLMOX_INPUT_DEVICES", "/proc/bus/input/devices")
INPUT_DIR = os.environ.get("WALLMOX_INPUT_DIR", "/dev/input")
POWEROFF = os.environ.get("WALLMOX_POWEROFF", "systemctl poweroff").split()

EV_KEY, KEY_POWER = 0x01, 116
EVENT = struct.Struct("llHHi")          # struct input_event on 64-bit Linux


def log(msg):
    print(msg, flush=True)


def load_conf():
    conf = {"URL": "", "KEY": "", "HOLD": "3"}
    try:
        with open(CONF, encoding="utf-8") as fh:
            for line in fh:
                key, sep, value = line.strip().partition("=")
                if sep and key in conf:
                    conf[key] = value.strip()
    except OSError:
        pass
    try:
        hold = max(1.0, min(15.0, float(conf["HOLD"])))
    except ValueError:
        hold = 3.0
    return conf["URL"].rstrip("/"), conf["KEY"], hold


def power_button_devices():
    """eventN nodes of every input device that has a power key."""
    nodes = []
    try:
        blocks = open(DEVICES, encoding="utf-8").read().split("\n\n")
    except OSError:
        return nodes
    for block in blocks:
        name = handlers = keybits = ""
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip('"')
            elif line.startswith("H: Handlers="):
                handlers = line.split("=", 1)[1]
            elif line.startswith("B: KEY="):
                keybits = line.split("=", 1)[1]
        # the KEY bitmap is printed as hex words, most significant first
        bits = 0
        for word in keybits.split():
            bits = (bits << 64) | int(word, 16)
        has_power = bool(bits >> KEY_POWER & 1) if keybits else False
        if has_power or "power button" in name.lower():
            for h in handlers.split():
                if h.startswith("event"):
                    nodes.append((os.path.join(INPUT_DIR, h), name))
    return nodes


def notify(url, key, event, hold):
    """Tell Wallmox, so the status page shows the message. Best effort."""
    if not url:
        return
    query = "?key=" + urllib.parse.quote(key) if key else ""
    data = urllib.parse.urlencode({"host": socket.gethostname(), "event": event,
                                   "hold": f"{hold:g}", "v": VERSION}).encode()
    try:
        urllib.request.urlopen(url + "/api/tablet-event" + query, data=data, timeout=5)
    except Exception as exc:          # the tablet still works without Wallmox
        log(f"could not reach Wallmox: {exc}")


def main():
    url, key, hold = load_conf()
    devices = power_button_devices()
    if not devices:
        sys.exit("No power button input device found.")
    files = []
    for path, name in devices:
        try:
            files.append(open(path, "rb", buffering=0))
            log(f"wallmox-power {VERSION}: watching {path} ({name}), hold {hold:g}s to power off")
        except OSError as exc:
            log(f"cannot open {path}: {exc}")
    if not files:
        sys.exit("Cannot open any power button device.")

    pressed_at = None
    timer = None
    lock = threading.Lock()

    def shut_down():
        nonlocal pressed_at
        with lock:
            if pressed_at is None:
                return
            pressed_at = None
        log("power button held, shutting down")
        notify(url, key, "power_off", hold)
        subprocess.run(POWEROFF, check=False)

    while True:
        ready, _, _ = select.select(files, [], [])
        for fh in ready:
            data = fh.read(EVENT.size)
            if len(data) < EVENT.size:
                continue
            _, _, etype, code, value = EVENT.unpack(data)
            if etype != EV_KEY or code != KEY_POWER:
                continue
            if value == 1:                                   # pressed
                with lock:
                    if pressed_at is None:
                        pressed_at = time.monotonic()
                        timer = threading.Timer(hold, shut_down)
                        timer.daemon = True
                        timer.start()
            elif value == 0:                                 # released
                with lock:
                    if pressed_at is None:
                        continue
                    held = time.monotonic() - pressed_at
                    pressed_at = None
                if timer:
                    timer.cancel()
                if held < hold:
                    log(f"short press ({held:.1f}s), showing the hint")
                    threading.Thread(target=notify, args=(url, key, "power_short", hold),
                                     daemon=True).start()


if __name__ == "__main__":
    main()
