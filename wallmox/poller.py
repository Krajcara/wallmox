"""Background polling so tablet refreshes never wait on the Proxmox API."""

import copy
import logging
import threading
import time
from collections import defaultdict, deque

log = logging.getLogger(__name__)


class Poller(threading.Thread):
    def __init__(self, source, interval: int, history_size: int):
        super().__init__(name="wallmox-poller", daemon=True)
        self.source = source
        self.interval = interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._snapshot = None
        self._error = None
        self._last_ok = None
        self._history = defaultdict(lambda: deque(maxlen=history_size))

    def poll_once(self):
        try:
            snap = self.source()
        except Exception as exc:  # keep polling whatever happens
            log.warning("Poll failed: %s", exc)
            with self._lock:
                self._error = str(exc)
            return
        with self._lock:
            self._snapshot = snap
            self._error = None
            self._last_ok = snap["time"]
            for node in snap["nodes"]:
                if node["online"]:
                    self._history[(node["name"], "cpu")].append(node["cpu"])
                    self._history[(node["name"], "mem")].append(node["mem_pct"])

    def run(self):
        while not self._stop.is_set():
            started = time.monotonic()
            self.poll_once()
            self._stop.wait(max(0.5, self.interval - (time.monotonic() - started)))

    def stop(self):
        self._stop.set()

    def state(self) -> dict:
        with self._lock:
            return {
                "snapshot": copy.deepcopy(self._snapshot),
                "error": self._error,
                "last_ok": self._last_ok,
                "history": {k: list(v) for k, v in self._history.items()},
            }
