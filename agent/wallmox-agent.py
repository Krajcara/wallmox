#!/usr/bin/env python3
"""Wallmox agent: reports temperatures of a Proxmox node to Wallmox.

Reads the kernel's hardware sensors (/sys/class/hwmon, /sys/class/thermal),
so lm-sensors is not needed. Standard library only. Read-only: it answers one
question ("how warm is this node?") and nothing else.

  GET /temps     with header  Authorization: Bearer <key>

Configuration comes from /etc/wallmox-agent/agent.conf (KEY=..., PORT=...,
LISTEN=...) or the environment variables WALLMOX_AGENT_KEY / _PORT / _LISTEN.
"""

import glob
import hmac
import json
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.3.0"
CONF_FILE = "/etc/wallmox-agent/agent.conf"
SYS = os.environ.get("WALLMOX_AGENT_SYSFS", "/sys")   # overridable for tests

# hwmon drivers that describe the CPU, best first
CPU_DRIVERS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "soc_thermal")
# preferred labels within those drivers
CPU_LABELS = ("tdie", "tctl", "package", "cpu")


def read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return default


def read_temp(path):
    raw = read(path)
    try:
        value = int(raw) / 1000.0
    except ValueError:
        return None
    return round(value, 1) if -40.0 < value < 150.0 else None


def device_name(hwmon_dir):
    """For NVMe: nvme0 and its model; for drivetemp: the block device (sda)."""
    dev = os.path.realpath(os.path.join(hwmon_dir, "device"))
    base = os.path.basename(dev)
    if base.startswith("nvme"):
        model = read(os.path.join(dev, "model")) or read(f"{SYS}/class/nvme/{base}/model")
        return base, model
    blocks = glob.glob(os.path.join(dev, "block", "*"))
    if blocks:
        name = os.path.basename(blocks[0])
        return name, read(os.path.join(dev, "model"))
    return base, ""


def hwmon_sensors():
    sensors = []
    for hw in sorted(glob.glob(f"{SYS}/class/hwmon/hwmon*")):
        driver = read(os.path.join(hw, "name"))
        for inp in sorted(glob.glob(os.path.join(hw, "temp*_input"))):
            prefix = inp[: -len("_input")]
            temp = read_temp(inp)
            if temp is None:
                continue
            sensors.append({
                "driver": driver,
                "label": read(prefix + "_label") or os.path.basename(prefix),
                "temp": temp,
                "max": read_temp(prefix + "_max"),
                "crit": read_temp(prefix + "_crit"),
                "hwmon": hw,
            })
    return sensors


def thermal_zones():
    zones = []
    for tz in sorted(glob.glob(f"{SYS}/class/thermal/thermal_zone*")):
        temp = read_temp(os.path.join(tz, "temp"))
        if temp is not None:
            zones.append({"type": read(os.path.join(tz, "type")), "temp": temp})
    return zones


def cpu_temp(sensors, zones):
    for driver in CPU_DRIVERS:
        found = [s for s in sensors if s["driver"] == driver]
        if not found:
            continue
        for wanted in CPU_LABELS:
            hits = [s["temp"] for s in found if s["label"].lower().startswith(wanted)]
            if hits:
                return max(hits)          # hottest package on multi-socket boards
        return max(s["temp"] for s in found)
    for wanted in ("x86_pkg_temp", "cpu", "soc"):
        hits = [z["temp"] for z in zones if wanted in z["type"].lower()]
        if hits:
            return max(hits)
    acpi = [s["temp"] for s in sensors if s["driver"] == "acpitz"]
    return max(acpi) if acpi else None


def disk_temps(sensors):
    disks = {}
    for s in sensors:
        if s["driver"] not in ("nvme", "drivetemp"):
            continue
        name, model = device_name(s["hwmon"])
        # NVMe reports several sensors; "Composite" is the drive's own summary
        if name in disks and s["label"].lower() != "composite":
            continue
        disks[name] = {"name": name, "model": model, "temp": s["temp"],
                       "max": s["max"], "crit": s["crit"]}
    return sorted(disks.values(), key=lambda d: d["name"])


def snapshot():
    sensors = hwmon_sensors()
    zones = thermal_zones()
    return {
        "agent": "wallmox-agent",
        "version": VERSION,
        "node": socket.gethostname(),
        "time": time.time(),
        "cpu": cpu_temp(sensors, zones),
        "disks": disk_temps(sensors),
        "sensors": [{k: v for k, v in s.items() if k != "hwmon"} for s in sensors],
    }


def load_conf():
    conf = {}
    for line in read(CONF_FILE).splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            conf[key.strip()] = value.strip().strip('"').strip("'")
    key = os.environ.get("WALLMOX_AGENT_KEY") or conf.get("KEY", "")
    port = int(os.environ.get("WALLMOX_AGENT_PORT") or conf.get("PORT") or 9105)
    listen = os.environ.get("WALLMOX_AGENT_LISTEN") or conf.get("LISTEN") or "0.0.0.0"
    return key, port, listen


class Handler(BaseHTTPRequestHandler):
    server_version = f"wallmox-agent/{VERSION}"
    key = ""

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            return self._send(200, {"ok": True, "version": VERSION})
        if self.path.split("?")[0] != "/temps":
            return self._send(404, {"error": "not found"})
        sent = self.headers.get("Authorization", "")
        sent = sent[7:] if sent.startswith("Bearer ") else ""
        if not hmac.compare_digest(sent.encode(), self.key.encode()):
            return self._send(401, {"error": "wrong or missing key"})
        self._send(200, snapshot())

    def log_message(self, fmt, *args):   # keep the journal quiet
        pass


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--print":
        print(json.dumps(snapshot(), indent=2))
        return
    key, port, listen = load_conf()
    if len(key) < 16:
        sys.exit(f"No agent key set (at least 16 characters) in {CONF_FILE}.")
    Handler.key = key
    server = ThreadingHTTPServer((listen, port), Handler)
    print(f"wallmox-agent {VERSION} listening on {listen}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
