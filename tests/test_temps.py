import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from wallmox.config import Config
from wallmox.i18n import strings
from wallmox.temps import add_temps, agent_url
from wallmox.ui import build_view


class Agent(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer good-key-123456789":
            self.send_response(401); self.end_headers(); return
        body = json.dumps({"cpu": 61.5, "disks": [{"name": "nvme0", "temp": 58.0},
                                                   {"name": "sda", "temp": None}]}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def agent():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Agent)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


class Client:
    def __init__(self, port):
        self.port = port

    def get(self, path, **kw):
        assert path == "/cluster/status"
        return [{"type": "cluster", "name": "c"},
                {"type": "node", "name": "pve1", "ip": "127.0.0.1"},
                {"type": "node", "name": "pve2", "ip": "10.255.255.1"}]


def snapshot():
    base = {"online": True, "cpu": 10, "mem_pct": 20, "mem_used": 1, "mem_total": 2,
            "uptime": 5, "cores": 4, "cpu_model": "", "loadavg": [], "storage": [],
            "guests": [], "error": None}
    return {"time": 0, "nodes": [dict(base, name="pve1"), dict(base, name="pve2"),
                                 dict(base, name="pve3", online=False)]}


def test_agent_url():
    assert agent_url("10.0.0.5", 9105) == "http://10.0.0.5:9105/temps"
    assert agent_url("10.0.0.5:9999", 9105) == "http://10.0.0.5:9999/temps"
    assert agent_url("http://x/", 9105) == "http://x/temps"
    assert agent_url("fd00::5", 9105) == "http://[fd00::5]:9105/temps"


def test_add_temps(agent):
    cfg = Config()
    cfg.agent_key = "good-key-123456789"
    cfg.agent_port = agent
    snap = snapshot()
    add_temps(snap, Client(agent), cfg)
    pve1, pve2, pve3 = snap["nodes"]
    assert pve1["temps"]["cpu"] == 61.5
    assert [d["name"] for d in pve1["temps"]["disks"]] == ["nvme0"]   # None temps dropped
    assert pve2["temps"] is None and "No agent answering" in pve2["temp_error"]
    assert "temps" not in pve3                                         # offline: skipped


def test_wrong_key_and_override(agent):
    cfg = Config()
    cfg.agent_key = "wrong-key-123456789"
    cfg.agent_port = 1
    cfg.agent_hosts = {"pve1": f"127.0.0.1:{agent}"}
    snap = snapshot()
    add_temps(snap, Client(agent), cfg)
    assert "rejected the key" in snap["nodes"][0]["temp_error"]


def test_view_temperature_gauge_and_disks():
    cfg = Config()
    cfg.proxmox.host, cfg.proxmox.token_id, cfg.proxmox.token_secret = "h", "t", "s"
    snap = snapshot()
    snap["nodes"][0]["temps"] = {"cpu": 88.0, "disks": [{"name": "nvme0", "temp": 57.0}]}
    state = {"snapshot": snap, "error": None, "last_ok": 0,
             "history": {("pve1", "cpu"): [10, 20, 30], ("pve1", "temp"): [50, 60, 88]}}
    view = build_view(state, cfg, strings("en"))
    n = view["nodes"][0]
    assert n["temp_gauge"]["value"] == 88 and n["temp_gauge"]["level"] == "crit"
    assert n["temp_gauge"]["unit"] == "°C"
    assert n["disks"][0]["level"] == "warn"
    assert n["spark"]["line2"]
    assert n["level"] == "crit"

    cfg.display.show_temps = False
    n = build_view(state, cfg, strings("en"))["nodes"][0]
    assert n["temp_gauge"] is None and n["disks"] == [] and n["spark"]["line2"] is None
