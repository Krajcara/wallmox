import json
import re

import pytest

from wallmox.app import create_app
from wallmox.auth import set_password
from wallmox.config import Config, load_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLMOX_DATA", str(tmp_path))
    monkeypatch.delenv("WALLMOX_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    cfg.demo = True
    cfg.data_dir = str(tmp_path)
    set_password(cfg, "correct horse")
    app = create_app(cfg, start_poller=False)
    app.extensions["wallmox_poller"].poll_once()
    return app, cfg, tmp_path


def csrf(client, path="/admin/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def login(client, password="correct horse"):
    token = csrf(client)
    return client.post("/admin/login", data={"csrf": token, "password": password})


def test_admin_requires_login(env):
    app, _, _ = env
    c = app.test_client()
    r = c.get("/admin/")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_wrong_password_and_lockout(env):
    app, _, _ = env
    c = app.test_client()
    for _ in range(4):
        assert "Wrong password" in login(c, "nope").get_data(as_text=True)
    assert "Too many attempts" in login(c, "nope").get_data(as_text=True)
    assert "Too many attempts" in login(c).get_data(as_text=True)   # locked even if right


def test_post_without_csrf_is_rejected(env):
    app, cfg, _ = env
    c = app.test_client()
    login(c)
    c.post("/admin/save/general", data={"title": "Hacked", "refresh_interval": 10,
                                        "poll_interval": 5, "language": "en"})
    assert cfg.title == "Wallmox"


def test_save_general_and_display_persist(env):
    app, cfg, tmp = env
    c = app.test_client()
    assert login(c).status_code == 302
    token = csrf(c, "/admin/")
    r = c.post("/admin/save/general", data={"csrf": token, "title": "Rack",
               "language": "sr", "refresh_interval": "15", "poll_interval": "4"})
    assert r.status_code == 302
    assert cfg.title == "Rack" and cfg.language == "sr" and cfg.refresh_interval == 15

    c.post("/admin/save/display", data={
        "csrf": token, "show_trend": "on", "show_storage": "on",
        "known_node": ["pve1", "pve2"], "node": ["pve1"],
        "known_storage": ["local", "tank"], "storage": ["local"]})
    assert cfg.display.hidden_nodes == ["pve2"]
    assert cfg.display.hidden_storages == ["tank"]
    assert cfg.display.show_guests is False

    saved = json.loads((tmp / "settings.json").read_text())
    assert saved["title"] == "Rack" and saved["display"]["hidden_nodes"] == ["pve2"]

    html = c.get("/status/fragment").get_data(as_text=True)
    assert "pve1" in html and "pve2" not in html and "tank" not in html

    reloaded = load_config()
    assert reloaded.title == "Rack" and reloaded.display.hidden_storages == ["tank"]


def test_invalid_number_is_reported(env):
    app, cfg, _ = env
    c = app.test_client()
    login(c)
    token = csrf(c, "/admin/")
    r = c.post("/admin/save/thresholds", follow_redirects=True, data={
        "csrf": token, "cpu_warn": "80", "cpu_crit": "50",
        "mem_warn": "80", "mem_crit": "90", "storage_warn": "80", "storage_crit": "90"})
    assert "must be a number" in r.get_data(as_text=True)
    assert cfg.thresholds["cpu"].crit == 90


def test_status_key_and_password_change(env):
    app, cfg, _ = env
    c = app.test_client()
    login(c)
    token = csrf(c, "/admin/")
    c.post("/admin/status-key", data={"csrf": token, "action": "new"})
    assert cfg.status_key
    assert c.get("/status").status_code == 403
    assert c.get(f"/status?key={cfg.status_key}").status_code == 200

    c.post("/admin/password", data={"csrf": token, "current_password": "correct horse",
                                     "new_password": "battery staple"})
    fresh = app.test_client()
    assert login(fresh, "battery staple").status_code == 302


def test_proxmox_save_keeps_secret_when_blank(env):
    app, cfg, _ = env
    cfg.proxmox.token_secret = "keep-me"
    c = app.test_client()
    login(c)
    token = csrf(c, "/admin/")
    c.post("/admin/save/proxmox", data={"csrf": token, "host": "https://10.0.0.5:8006/",
                                        "port": "8006", "token_id": "wallmox@pve!dash",
                                        "token_secret": ""})
    assert cfg.proxmox.host == "10.0.0.5"
    assert cfg.proxmox.token_secret == "keep-me"
