"""Turn raw snapshots into ready-to-draw values for the status templates.

All geometry is computed here so the page needs no JavaScript to draw,
which keeps it working on Android 4.4 browsers.
"""

import math
import time

from .config import proxmox_ready

GAUGE_CENTER = 65
GAUGE_R = 48          # value arc
ZONE_R = 58           # thin outer ring that marks warn/crit zones
GAUGE_SWEEP = 0.75    # 270 degree arc, open at the bottom
GAUGE_ROTATE = 135    # start the arc at the lower left

MAX_GUEST_CHIPS = 14
SPARK_W, SPARK_H = 200, 40


def level(pct: float, th) -> str:
    if pct >= th.crit:
        return "crit"
    if pct >= th.warn:
        return "warn"
    return "ok"


def worst(levels) -> str:
    order = {"ok": 0, "warn": 1, "crit": 2}
    return max(levels, key=lambda lv: order[lv], default="ok")


def _arc(r: float):
    circ = 2 * math.pi * r
    return circ, circ * GAUGE_SWEEP


def gauge(pct: float, th, label: str) -> dict:
    pct = max(0.0, min(100.0, pct))
    circ, sweep = _arc(GAUGE_R)
    zcirc, zsweep = _arc(ZONE_R)
    warn_start = zsweep * th.warn / 100
    crit_start = zsweep * th.crit / 100
    return {
        "label": label,
        "value": int(round(pct)),
        "level": level(pct, th),
        "c": GAUGE_CENTER, "r": GAUGE_R, "zr": ZONE_R, "rot": GAUGE_ROTATE,
        "track": f"{sweep:.2f} {circ:.2f}",
        "fill": f"{sweep * pct / 100:.2f} {circ:.2f}",
        "show_fill": pct >= 0.5,
        # zone ring: amber from warn to crit, red from crit to the end
        "warn_dash": f"{max(0.0, crit_start - warn_start):.2f} {zcirc:.2f}",
        "warn_offset": f"{-warn_start:.2f}",
        "crit_dash": f"{max(0.0, zsweep - crit_start):.2f} {zcirc:.2f}",
        "crit_offset": f"{-crit_start:.2f}",
    }


def sparkline(values, capacity: int) -> dict | None:
    if len(values) < 2:
        return None
    step = SPARK_W / max(1, capacity - 1)
    x0 = SPARK_W - step * (len(values) - 1)   # newest sample sits at the right edge
    pts = []
    for i, v in enumerate(values):
        v = max(0.0, min(100.0, v))
        pts.append(f"{x0 + i * step:.1f},{SPARK_H - 2 - v / 100 * (SPARK_H - 4):.1f}")
    return {
        "w": SPARK_W, "h": SPARK_H,
        "line": " ".join(pts),
        "area": f"{x0:.1f},{SPARK_H} " + " ".join(pts) + f" {SPARK_W},{SPARK_H}",
    }


def fmt_bytes(n: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    i = 0
    n = float(n or 0)
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    if n >= 100 or i == 0:
        return f"{n:.0f} {units[i]}"
    return f"{n:.1f} {units[i]}"


def fmt_duration(seconds: float) -> str:
    s = int(seconds or 0)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def fmt_age(seconds: float) -> str:
    s = int(seconds)
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{s // 60} min"
    return fmt_duration(s)


def build_view(state: dict, cfg, S: dict) -> dict:
    snap = state["snapshot"]
    now = time.time()
    view = {"nodes": [], "banner": None, "stale": False}
    disp = cfg.display

    if not cfg.demo and not proxmox_ready(cfg):
        view["banner"] = {"level": "warn", "title": S["not_configured"], "detail": ""}
        return view

    if snap is None:
        view["banner"] = {"level": "warn" if not state["error"] else "crit",
                          "title": S["waiting"] if not state["error"] else S["lost"],
                          "detail": state["error"] or ""}
        return view

    if state["error"]:
        view["stale"] = True
        view["banner"] = {
            "level": "crit", "title": S["lost"],
            "detail": S["last_data"].format(age=fmt_age(now - state["last_ok"])),
            "error": state["error"],
        }

    th = cfg.thresholds
    spark_minutes = round(cfg.history_size * cfg.poll_interval / 60)
    hidden_nodes = set(disp.hidden_nodes)
    hidden_storages = set(disp.hidden_storages)
    for n in snap["nodes"]:
        if n["name"] in hidden_nodes:
            continue
        node = {
            "name": n["name"],
            "online": n["online"],
            "error": n.get("error"),
            "uptime": fmt_duration(n["uptime"]),
            "cores": n["cores"],
            "cpu_model": n["cpu_model"] if disp.show_cpu_model else "",
            "load": " ".join(f"{x:.2f}" for x in n["loadavg"]),
        }
        if not n["online"]:
            node["level"] = "crit"
            view["nodes"].append(node)
            continue

        node["cpu_gauge"] = gauge(n["cpu"], th["cpu"], S["cpu"])
        node["mem_gauge"] = gauge(n["mem_pct"], th["mem"], S["ram"])
        node["mem_text"] = f"{fmt_bytes(n['mem_used'])} {S['of']} {fmt_bytes(n['mem_total'])}"

        node["storage"] = [{
            "name": s["name"], "type": s["type"],
            "pct": s["pct"], "width": max(1.5, min(100.0, s["pct"])),
            "level": level(s["pct"], th["storage"]),
            "text": f"{fmt_bytes(s['used'])} {S['of']} {fmt_bytes(s['total'])}",
        } for s in n["storage"] if s["name"] not in hidden_storages]
        node["show_storage"] = disp.show_storage
        node["show_guests"] = disp.show_guests

        spark = None
        if disp.show_trend:
            spark = sparkline(state["history"].get((n["name"], "cpu"), []), cfg.history_size)
        node["spark"] = spark
        node["spark_label"] = S["last_hour"].format(min=spark_minutes)

        guests = n["guests"]
        if not disp.show_stopped_guests:
            guests = [g for g in guests if g["running"]]
        running = sum(1 for g in guests if g["running"])
        node["guests_total"] = len(n["guests"])
        node["guests_stopped"] = len(n["guests"]) - running
        node["guests_running"] = running
        node["guest_chips"] = guests[:MAX_GUEST_CHIPS]
        node["guests_hidden"] = max(0, len(guests) - MAX_GUEST_CHIPS)

        node["level"] = worst([node["cpu_gauge"]["level"], node["mem_gauge"]["level"]]
                              + ([s["level"] for s in node["storage"]] if disp.show_storage else [])
                              + (["warn"] if node["error"] else []))
        view["nodes"].append(node)
    return view
