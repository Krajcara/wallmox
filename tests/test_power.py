import os
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

POWER = os.path.join(os.path.dirname(__file__), "..", "tablet", "wallmox-power.py")
EVENT = struct.Struct("llHHi")


def ev(value):
    return EVENT.pack(0, 0, 1, 116, value) + EVENT.pack(0, 0, 0, 0, 0)   # key + SYN


def test_short_press_notifies_and_long_press_powers_off(tmp_path):
    events = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            events.append((self.path, body))
            self.send_response(200); self.end_headers()

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    fifo = tmp_path / "event3"
    os.mkfifo(fifo)
    (tmp_path / "devices").write_text(
        'I: Bus=0019 Vendor=0000 Product=0001 Version=0000\n'
        'N: Name="Power Button"\nH: Handlers=kbd event3 \nB: KEY=10000000000000 0\n\n'
        'I: Bus=0011\nN: Name="AT Keyboard"\nH: Handlers=kbd event1\nB: KEY=1f\n')
    conf = tmp_path / "conf"
    conf.write_text(f"URL=http://127.0.0.1:{srv.server_address[1]}\nKEY=abc\nHOLD=1\n")
    off = tmp_path / "off"
    env = dict(os.environ, WALLMOX_SCREEN_CONF=str(conf), WALLMOX_INPUT_DEVICES=str(tmp_path / "devices"),
               WALLMOX_INPUT_DIR=str(tmp_path), WALLMOX_POWEROFF=f"touch {off}")
    proc = subprocess.Popen([sys.executable, POWER], env=env, stdout=subprocess.PIPE, text=True)
    try:
        with open(fifo, "wb", buffering=0) as w:
            w.write(ev(1)); time.sleep(0.2); w.write(ev(0))          # short press
            time.sleep(0.5)
            assert not off.exists()
            w.write(ev(1)); time.sleep(1.5)                           # hold
            assert off.exists()
            w.write(ev(0))
            time.sleep(0.5)
    finally:
        proc.terminate()
        srv.shutdown()
    kinds = [b for _, b in events]
    assert any("event=power_short" in b for b in kinds)
    assert any("event=power_off" in b for b in kinds)
    assert all(p.startswith("/api/tablet-event?key=abc") for p, _ in events)
