"""Status reports from the tablets' screen helpers (battery, charger, WiFi)."""

import threading
import time

STALE_AFTER = 5 * 60   # seconds without a report before a tablet counts as silent


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def wifi_bars(signal, link):
    """0-4 bars from the signal in dBm, or from the link quality (0-70) if that is all we have."""
    if signal is not None and signal < 0:
        for bars, floor in ((4, -60), (3, -67), (2, -75), (1, -85)):
            if signal >= floor:
                return bars
        return 0
    if link is not None:
        return max(0, min(4, round(link / 70 * 4)))
    return None


class Tablets:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_name = {}

    def report(self, form, ip: str) -> None:
        battery = _int(form.get("battery"))
        status = (form.get("bat_status") or "").strip()
        mains = form.get("mains", "")
        if mains in ("0", "1"):
            plugged = mains == "1"
        elif status:
            plugged = status in ("Charging", "Full", "Not charging")
        else:
            plugged = None
        temp = _int(form.get("bat_temp"))
        signal, link = _int(form.get("signal")), _int(form.get("link"))
        name = (form.get("host") or ip or "tablet").strip()[:64]
        entry = {
            "name": name, "ip": ip,
            "battery": battery if battery is not None and 0 <= battery <= 100 else None,
            "bat_status": status[:20],
            "bat_temp": round(temp / 10, 1) if temp is not None else None,
            "plugged": plugged,
            "wifi": (form.get("wifi") or "")[:16],
            "signal": signal, "link": link,
            "bars": wifi_bars(signal, link),
            "version": (form.get("v") or "")[:16],
            "seen": time.time(),
        }
        with self._lock:
            self._by_name[name] = entry

    def all(self) -> list:
        now = time.time()
        with self._lock:
            items = [dict(t) for t in self._by_name.values()]
        for t in items:
            t["age"] = now - t["seen"]
            t["stale"] = t["age"] > STALE_AFTER
        return sorted(items, key=lambda t: t["name"])

    def for_ip(self, ip: str):
        """The fresh report of the tablet that is looking at the page, if any."""
        matches = [t for t in self.all() if t["ip"] == ip and not t["stale"]]
        return max(matches, key=lambda t: t["seen"]) if matches else None
