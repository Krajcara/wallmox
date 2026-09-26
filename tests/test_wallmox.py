import time

import pytest

from wallmox.app import create_app
from wallmox.config import Config, Threshold
from wallmox.i18n import strings
from wallmox.proxmox import ProxmoxError, collect
from wallmox.ui import build_view, fmt_bytes, fmt_duration, gauge, level, sparkline


def test_level_and_gauge():
    th = Threshold(70, 90)
    assert level(10, th) == "ok"
    assert level(70, th) == "warn"
    assert level(95, th) == "crit"
    g = gauge(150, th, "CPU")
    assert g["value"] == 150 and g["level"] == "crit" and g["fill"].startswith(g["track"].split()[0])
    assert gauge(0, th, "CPU")["show_fill"] is False


def test_formatting():
    assert fmt_bytes(0) == "0 B"
    assert fmt_bytes(64 * 1024 ** 3) == "64.0 GiB"
    assert fmt_bytes(3.5 * 1024 ** 4) == "3.5 TiB"
    assert fmt_duration(38 * 86400 + 5 * 3600) == "38d 5h"
    assert fmt_duration(3700) == "1h 1m"


def test_sparkline_needs_two_points():
    assert sparkline([10], 60) is None
    assert sparkline([10, 20, 30], 60)["line"].count(",") == 3


class FakeClient:
    def __init__(self, fail_status=False):
        self.fail_status = fail_status

    def get(self, path, **params):
        if path == "/nodes":
            return [{"node": "pve", "status": "online", "cpu": 0.1, "maxcpu": 4,
                     "mem": 1, "maxmem": 2, "uptime": 10},
                    {"node": "old", "status": "offline"}]
        if path == "/cluster/resources":
            return [{"node": "pve", "vmid": 101, "name": "b", "type": "lxc", "status": "stopped"},
                    {"node": "pve", "vmid": 100, "name": "a", "type": "qemu", "status": "running"},
                    {"node": "pve", "vmid": 900, "name": "tpl", "type": "qemu", "template": 1}]
        if path.endswith("/status"):
            if self.fail_status:
                raise ProxmoxError("boom")
            return {"cpu": 0.25, "memory": {"used": 4, "total": 16}, "uptime": 99,
                    "loadavg": ["0.5", "0.4", "0.3"], "cpuinfo": {"cpus": 8, "model": "X"}}
        if path.endswith("/storage"):
            return [{"storage": "local", "type": "dir", "active": 1, "used": 5, "total": 10},
                    {"storage": "gone", "active": 0, "total": 0}]
        raise AssertionError(path)


def test_collect():
    snap = collect(FakeClient())
    pve, old = snap["nodes"][1], snap["nodes"][0]
    assert old["name"] == "old" and not old["online"]
    assert pve["cpu"] == 25.0 and pve["mem_pct"] == 25.0 and pve["cores"] == 8
    assert [s["name"] for s in pve["storage"]] == ["local"]
    assert [g["vmid"] for g in pve["guests"]] == [100, 101]   # running first, template hidden


def test_collect_node_error_is_kept_per_node():
    snap = collect(FakeClient(fail_status=True))
    assert snap["nodes"][1]["error"] == "boom"


def test_view_marks_stale_data():
    cfg = Config()
    cfg.proxmox.host, cfg.proxmox.token_id, cfg.proxmox.token_secret = "h", "t", "s"
    snap = collect(FakeClient())
    state = {"snapshot": snap, "error": "down", "last_ok": time.time() - 120, "history": {}}
    view = build_view(state, cfg, strings("sr"))
    assert view["stale"] and view["banner"]["level"] == "crit"
    assert "2 min" in view["banner"]["detail"]


@pytest.fixture
def client(tmp_path):
    cfg = Config()
    cfg.demo = True
    cfg.status_key = "secret"
    cfg.data_dir = str(tmp_path)
    app = create_app(cfg, start_poller=False)
    app.extensions["wallmox_poller"].poll_once()
    return app.test_client()


def test_status_key_required(client):
    assert client.get("/status").status_code == 403
    r = client.get("/status?key=secret")
    assert r.status_code == 200 and b"pve1" in r.data
    assert client.get("/status/fragment?key=secret").status_code == 200
    assert client.get("/api/snapshot?key=secret").get_json()["snapshot"]["nodes"]


def test_healthz(client):
    assert client.get("/healthz").get_json()["ok"] is True
