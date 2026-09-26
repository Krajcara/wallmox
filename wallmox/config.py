"""Configuration.

Two layers:
  1. config.toml      - written once (by the installer or by hand), read-only for the app
  2. settings.json    - everything changed in the admin panel, stored in the data dir

settings.json wins over config.toml, so the admin panel can change any
editable value without touching the TOML file.
"""

import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field

if sys.version_info < (3, 11):
    sys.exit("Wallmox needs Python 3.11 or newer (Debian 12+).")

import tomllib

log = logging.getLogger(__name__)

SEARCH_PATHS = ["/etc/wallmox/config.toml", "config.toml"]
DEFAULT_DATA_DIRS = ["/var/lib/wallmox", "data"]
SETTINGS_FILE = "settings.json"


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


@dataclass
class Display:
    show_trend: bool = True
    show_storage: bool = True
    show_guests: bool = True
    show_stopped_guests: bool = True
    show_cpu_model: bool = True
    show_temps: bool = True
    hidden_nodes: list = field(default_factory=list)
    hidden_storages: list = field(default_factory=list)


def _default_thresholds() -> dict:
    return {
        "cpu": Threshold(70, 90),
        "mem": Threshold(80, 92),
        "storage": Threshold(80, 90),
        "cpu_temp": Threshold(70, 85),    # degrees Celsius
        "disk_temp": Threshold(55, 65),
    }


@dataclass
class Config:
    listen: str = "0.0.0.0"
    port: int = 8080
    title: str = "Wallmox"
    language: str = "en"
    poll_interval: int = 5        # seconds between Proxmox API polls
    refresh_interval: int = 10    # seconds between tablet screen updates
    history_size: int = 72        # samples kept for the CPU sparkline
    status_key: str = ""          # optional: require ?key=... on the status page
    behind_proxy: bool = False    # trust X-Forwarded-* headers from a reverse proxy
    agent_key: str = ""           # shared key of the temperature agents on the nodes
    agent_port: int = 9105
    agent_hosts: dict = field(default_factory=dict)   # node name -> address override
    demo: bool = False
    proxmox: ProxmoxConfig = field(default_factory=ProxmoxConfig)
    thresholds: dict = field(default_factory=_default_thresholds)
    display: Display = field(default_factory=Display)
    # security, kept only in settings.json
    admin_password_hash: str = ""
    secret_key: str = ""
    # where things came from
    source_path: str = ""
    data_dir: str = ""


# Values the admin panel may change. Anything else stays TOML-only.
EDITABLE_TOP = ("title", "language", "poll_interval", "refresh_interval",
                "status_key", "behind_proxy", "agent_key", "agent_port", "agent_hosts")
EDITABLE_PROXMOX = ("host", "port", "token_id", "token_secret", "verify_ssl")
LANGUAGES = ("en", "sr")


def find_config(explicit: str | None = None) -> str | None:
    candidates = [explicit, os.environ.get("WALLMOX_CONFIG"), *SEARCH_PATHS]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    if explicit:
        raise FileNotFoundError(f"Config file not found: {explicit}")
    return None


def find_data_dir() -> str:
    env = os.environ.get("WALLMOX_DATA")
    if env:
        return env
    for path in DEFAULT_DATA_DIRS:
        if os.path.isdir(path) and os.access(path, os.W_OK):
            return path
    return os.path.abspath("data")


def _apply(cfg: Config, raw: dict) -> None:
    """Copy known keys from a parsed TOML or JSON dict onto cfg."""
    for key in ("listen", "port", "title", "language", "poll_interval",
                "refresh_interval", "history_size", "status_key",
                "behind_proxy", "demo", "admin_password_hash", "secret_key",
                "agent_key", "agent_port", "agent_hosts"):
        if key in raw:
            setattr(cfg, key, raw[key])

    for key, value in (raw.get("proxmox") or {}).items():
        if hasattr(cfg.proxmox, key):
            setattr(cfg.proxmox, key, value)

    for name, values in (raw.get("thresholds") or {}).items():
        if name in cfg.thresholds and isinstance(values, dict):
            cur = cfg.thresholds[name]
            cfg.thresholds[name] = Threshold(float(values.get("warn", cur.warn)),
                                             float(values.get("crit", cur.crit)))

    for key, value in (raw.get("display") or {}).items():
        if hasattr(cfg.display, key):
            setattr(cfg.display, key, value)


def normalize(cfg: Config) -> None:
    cfg.poll_interval = max(2, int(cfg.poll_interval))
    cfg.refresh_interval = max(3, int(cfg.refresh_interval))
    cfg.history_size = max(10, int(cfg.history_size))
    cfg.proxmox.port = int(cfg.proxmox.port)
    cfg.agent_port = int(cfg.agent_port)
    if not isinstance(cfg.agent_hosts, dict):
        cfg.agent_hosts = {}
    if cfg.language not in LANGUAGES:
        cfg.language = "en"
    for th in cfg.thresholds.values():
        th.warn = max(0.0, min(100.0, float(th.warn)))
        th.crit = max(th.warn, min(100.0, float(th.crit)))


def proxmox_ready(cfg: Config) -> bool:
    px = cfg.proxmox
    return bool(px.host and px.token_id and px.token_secret)


def settings_path(cfg: Config) -> str:
    return os.path.join(cfg.data_dir, SETTINGS_FILE)


def load_config(path: str | None = None) -> Config:
    cfg = Config()
    cfg.data_dir = find_data_dir()

    found = find_config(path)
    if found:
        with open(found, "rb") as fh:
            _apply(cfg, tomllib.load(fh))
        cfg.source_path = found

    sp = settings_path(cfg)
    if os.path.isfile(sp):
        with open(sp, encoding="utf-8") as fh:
            _apply(cfg, json.load(fh))

    normalize(cfg)
    if not found and not os.path.isfile(sp):
        log.warning("No config found, starting in demo mode.")
        cfg.demo = True
    elif not cfg.demo and not proxmox_ready(cfg):
        log.warning("Proxmox connection is not configured yet. "
                    "Set it up in the admin panel.")
    return cfg


def save_settings(cfg: Config) -> None:
    """Write every editable value to settings.json (atomic, mode 600)."""
    data = {key: getattr(cfg, key) for key in EDITABLE_TOP}
    data["proxmox"] = {key: getattr(cfg.proxmox, key) for key in EDITABLE_PROXMOX}
    data["thresholds"] = {name: asdict(th) for name, th in cfg.thresholds.items()}
    data["display"] = asdict(cfg.display)
    data["admin_password_hash"] = cfg.admin_password_hash
    data["secret_key"] = cfg.secret_key

    os.makedirs(cfg.data_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=cfg.data_dir, prefix=".settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, settings_path(cfg))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
