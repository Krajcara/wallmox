"""Configuration loading.

v0.1 reads a TOML file. From v0.2 the admin panel will manage settings,
but the TOML file stays as the source for connection details.
"""

import logging
import os
import sys
from dataclasses import dataclass, field

if sys.version_info < (3, 11):
    sys.exit("Wallmox needs Python 3.11 or newer (Debian 12+).")

import tomllib

log = logging.getLogger(__name__)

SEARCH_PATHS = ["/etc/wallmox/config.toml", "config.toml"]


@dataclass
class ProxmoxConfig:
    host: str = ""
    port: int = 8006
    token_id: str = ""        # e.g. "wallmox@pve!dash"
    token_secret: str = ""
    verify_ssl: bool | str = False  # False, True, or path to a CA bundle
    timeout: float = 5.0


@dataclass
class Threshold:
    warn: float
    crit: float


def _default_thresholds() -> dict:
    return {
        "cpu": Threshold(70, 90),
        "mem": Threshold(80, 92),
        "storage": Threshold(80, 90),
    }


@dataclass
class Config:
    listen: str = "0.0.0.0"
    port: int = 8080
    title: str = "Wallmox"
    language: str = "en"
    poll_interval: int = 5        # seconds between Proxmox API polls
    refresh_interval: int = 10    # seconds between tablet screen updates
    history_size: int = 72        # samples kept for the CPU/RAM sparklines
    status_key: str = ""          # optional: require ?key=... on the status page
    demo: bool = False
    proxmox: ProxmoxConfig = field(default_factory=ProxmoxConfig)
    thresholds: dict = field(default_factory=_default_thresholds)
    source_path: str = ""


def find_config(explicit: str | None = None) -> str | None:
    candidates = [explicit, os.environ.get("WALLMOX_CONFIG"), *SEARCH_PATHS]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    if explicit:
        raise FileNotFoundError(f"Config file not found: {explicit}")
    return None


def load_config(path: str | None = None) -> Config:
    found = find_config(path)
    cfg = Config()
    if not found:
        log.warning("No config file found, starting in demo mode.")
        cfg.demo = True
        return cfg

    with open(found, "rb") as fh:
        raw = tomllib.load(fh)
    cfg.source_path = found

    for key in ("listen", "port", "title", "language", "poll_interval",
                "refresh_interval", "history_size", "status_key", "demo"):
        if key in raw:
            setattr(cfg, key, raw[key])

    px = raw.get("proxmox", {})
    for key in ("host", "port", "token_id", "token_secret", "verify_ssl", "timeout"):
        if key in px:
            setattr(cfg.proxmox, key, px[key])

    for name, values in raw.get("thresholds", {}).items():
        if name in cfg.thresholds:
            cfg.thresholds[name] = Threshold(
                float(values.get("warn", cfg.thresholds[name].warn)),
                float(values.get("crit", cfg.thresholds[name].crit)),
            )

    cfg.poll_interval = max(2, int(cfg.poll_interval))
    cfg.refresh_interval = max(3, int(cfg.refresh_interval))
    cfg.history_size = max(10, int(cfg.history_size))

    if not cfg.demo:
        missing = [k for k in ("host", "token_id", "token_secret")
                   if not getattr(cfg.proxmox, k)]
        if missing:
            raise ValueError(
                f"{found}: missing [proxmox] settings: {', '.join(missing)}")
    return cfg
