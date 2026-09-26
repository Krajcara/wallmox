import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

AGENT = os.path.join(os.path.dirname(__file__), "..", "agent", "wallmox-agent.py")


def load_agent(sysfs):
    os.environ["WALLMOX_AGENT_SYSFS"] = str(sysfs)
    spec = importlib.util.spec_from_file_location("wallmox_agent", AGENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def sysfs(tmp_path):
    root = tmp_path / "sys"
    # Intel CPU with two packages
    hw0 = root / "class/hwmon/hwmon0"
    w(hw0 / "name", "coretemp\n")
    w(hw0 / "temp1_input", "52000\n"); w(hw0 / "temp1_label", "Package id 0\n")
    w(hw0 / "temp2_input", "58000\n"); w(hw0 / "temp2_label", "Package id 1\n")
    w(hw0 / "temp3_input", "49000\n"); w(hw0 / "temp3_label", "Core 0\n")
    # NVMe drive
    nvme_dev = root / "devices/pci0000:00/nvme/nvme0"
    w(nvme_dev / "model", "Samsung SSD 980 PRO 1TB   \n")
    hw1 = root / "class/hwmon/hwmon1"
    w(hw1 / "name", "nvme\n")
    w(hw1 / "temp1_input", "41850\n"); w(hw1 / "temp1_label", "Composite\n")
    w(hw1 / "temp2_input", "47850\n"); w(hw1 / "temp2_label", "Sensor 1\n")
    w(hw1 / "temp1_crit", "84850\n")
    os.symlink(nvme_dev, hw1 / "device")
    # broken sensor value must be ignored
    hw2 = root / "class/hwmon/hwmon2"
    w(hw2 / "name", "acpitz\n"); w(hw2 / "temp1_input", "-273000\n")
    return root


def test_snapshot(sysfs):
    agent = load_agent(sysfs)
    snap = agent.snapshot()
    assert snap["cpu"] == 58.0                       # hottest package
    assert snap["disks"] == [{"name": "nvme0", "model": "Samsung SSD 980 PRO 1TB",
                              "temp": round(41.85, 1), "max": None, "crit": round(84.85, 1)}]
    assert all(s["driver"] != "acpitz" for s in snap["sensors"])


def test_amd_prefers_tdie(tmp_path):
    root = tmp_path / "sys"
    hw = root / "class/hwmon/hwmon0"
    w(hw / "name", "k10temp\n")
    w(hw / "temp1_input", "71000\n"); w(hw / "temp1_label", "Tctl\n")
    w(hw / "temp2_input", "61000\n"); w(hw / "temp2_label", "Tdie\n")
    assert load_agent(root).snapshot()["cpu"] == 61.0


def test_thermal_zone_fallback(tmp_path):
    root = tmp_path / "sys"
    tz = root / "class/thermal/thermal_zone0"
    w(tz / "type", "x86_pkg_temp\n"); w(tz / "temp", "45000\n")
    assert load_agent(root).snapshot()["cpu"] == 45.0


def test_http_requires_key(sysfs):
    agent = load_agent(sysfs)
    agent.Handler.key = "k" * 20
    server = agent.ThreadingHTTPServer(("127.0.0.1", 0), agent.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/temps"
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(url, timeout=3)
        assert err.value.code == 401
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + "k" * 20})
        data = json.load(urllib.request.urlopen(req, timeout=3))
        assert data["cpu"] == 58.0
    finally:
        server.shutdown()
