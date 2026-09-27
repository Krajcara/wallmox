import time

from wallmox.tablets import Tablets, wifi_bars


def test_wifi_bars():
    assert wifi_bars(-50, None) == 4
    assert wifi_bars(-70, None) == 2
    assert wifi_bars(-90, None) == 0
    assert wifi_bars(None, 35) == 2
    assert wifi_bars(None, None) is None


def test_report_and_lookup():
    t = Tablets()
    t.report({"host": "wallmox-tablet", "battery": "87", "bat_status": "Charging",
              "bat_temp": "312", "mains": "1", "signal": "-52", "link": "58"}, "192.168.0.115")
    t.report({"host": "other", "battery": "40", "bat_status": "Discharging", "mains": ""},
             "192.168.0.116")
    a = t.for_ip("192.168.0.115")
    assert a["plugged"] is True and a["bat_temp"] == 31.2 and a["bars"] == 4
    b = t.for_ip("192.168.0.116")
    assert b["plugged"] is False and b["bars"] is None      # plugged guessed from status
    assert t.for_ip("10.0.0.1") is None
    t._by_name["other"]["seen"] = time.time() - 3600
    assert t.for_ip("192.168.0.116") is None                  # stale reports are ignored
    assert [x["stale"] for x in t.all()] == [True, False]
