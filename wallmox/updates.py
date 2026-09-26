"""Check GitHub for new releases and hand update requests to the root helper."""

import json
import logging
import os
import re
import threading
import time

import requests

from . import __version__

log = logging.getLogger(__name__)

REPO = os.environ.get("WALLMOX_REPO", "krajcara/wallmox")
CHECK_EVERY = 6 * 3600
PATH_UNIT = "/etc/systemd/system/wallmox-update.path"


def parse_version(text: str) -> tuple:
    nums = re.findall(r"\d+", (text or "").split("-")[0])
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


class UpdateChecker:
    def __init__(self, data_dir: str):
        self.dir = os.path.join(data_dir, "update")
        self._lock = threading.Lock()
        self._latest = None      # dict or None
        self._error = None
        self._checked = 0.0

    # ---------------------------------------------------------- GitHub

    def check(self, force: bool = False) -> None:
        with self._lock:
            if not force and time.time() - self._checked < CHECK_EVERY:
                return
            self._checked = time.time()
        try:
            resp = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest",
                                timeout=6, headers={"Accept": "application/vnd.github+json"})
            if resp.status_code == 404:
                latest, error = None, "no_releases"
            elif resp.status_code != 200:
                latest, error = None, f"GitHub answered {resp.status_code}"
            else:
                d = resp.json()
                latest, error = {
                    "tag": d.get("tag_name", ""),
                    "name": d.get("name") or d.get("tag_name", ""),
                    "notes": (d.get("body") or "").strip(),
                    "url": d.get("html_url", ""),
                    "date": (d.get("published_at") or "")[:10],
                }, None
        except requests.RequestException as exc:
            latest, error = None, f"Cannot reach GitHub ({exc.__class__.__name__})"
        with self._lock:
            self._latest, self._error = latest, error

    def check_in_background(self) -> None:
        if time.time() - self._checked >= CHECK_EVERY:
            threading.Thread(target=self.check, daemon=True).start()

    def info(self) -> dict:
        with self._lock:
            latest, error, checked = self._latest, self._error, self._checked
        newer = bool(latest and parse_version(latest["tag"]) > parse_version(__version__))
        return {"current": __version__, "latest": latest, "error": error,
                "checked": checked, "newer": newer,
                "can_update": os.path.exists(PATH_UNIT) and os.path.isdir(self.dir)}

    # ---------------------------------------------------------- running an update

    def state(self) -> dict:
        try:
            with open(os.path.join(self.dir, "state.json"), encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            st = {"state": "idle"}
        if os.path.exists(os.path.join(self.dir, "request")):
            st = {"state": "queued"}
        try:
            with open(os.path.join(self.dir, "log"), encoding="utf-8", errors="replace") as fh:
                st["log"] = fh.read()[-6000:]
        except OSError:
            st["log"] = ""
        st["version"] = __version__
        return st

    def request(self) -> bool:
        if self.state()["state"] in ("queued", "running"):
            return False
        with open(os.path.join(self.dir, "request"), "w", encoding="utf-8") as fh:
            fh.write(f"release {time.time():.0f}\n")
        return True
