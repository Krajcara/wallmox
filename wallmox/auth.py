"""Admin password handling and a small sign-in rate limit."""

import json
import threading
import time

from werkzeug.security import check_password_hash, generate_password_hash

from .config import save_settings, settings_path

MIN_PASSWORD = 8
MAX_FAILS = 5
LOCK_SECONDS = 60


def set_password(cfg, password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Password needs at least {MIN_PASSWORD} characters.")
    cfg.admin_password_hash = generate_password_hash(password)
    save_settings(cfg)


def reload_password_hash(cfg) -> None:
    """Pick up a password set from the command line while the server runs."""
    try:
        with open(settings_path(cfg), encoding="utf-8") as fh:
            stored = json.load(fh).get("admin_password_hash")
    except (OSError, ValueError):
        return
    if stored:
        cfg.admin_password_hash = stored


def verify_password(cfg, password: str) -> bool:
    reload_password_hash(cfg)
    if not cfg.admin_password_hash or not password:
        return False
    return check_password_hash(cfg.admin_password_hash, password)


class Throttle:
    """Lock an address out for a minute after too many wrong passwords."""

    def __init__(self):
        self._lock = threading.Lock()
        self._fails = {}   # addr -> (count, locked_until)

    def locked(self, addr: str) -> bool:
        with self._lock:
            _, until = self._fails.get(addr, (0, 0))
            return until > time.time()

    def fail(self, addr: str) -> None:
        with self._lock:
            count, _ = self._fails.get(addr, (0, 0))
            count += 1
            until = time.time() + LOCK_SECONDS if count >= MAX_FAILS else 0
            self._fails[addr] = (0 if until else count, until)

    def success(self, addr: str) -> None:
        with self._lock:
            self._fails.pop(addr, None)
