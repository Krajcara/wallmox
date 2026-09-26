"""Fake data so the status page can be tried without a Proxmox server."""

import math
import random
import time

GiB = 1024 ** 3


class DemoSource:
    def __init__(self):
        self.start = time.time()
        self.rng = random.Random(7)
        self.nodes = [
            {"name": "pve1", "cores": 16, "temp_base": 41,
             "disks": [("nvme0", "Samsung SSD 980 PRO 1TB", 43), ("nvme1", "WD Red SN700 2TB", 47)], "model": "AMD Ryzen 7 5700G", "mem": 64 * GiB,
             "base_cpu": 22, "base_mem": 0.58, "uptime": 38 * 86400 + 5 * 3600,
             "storage": [("local", "dir", 94, 0.41), ("local-lvm", "lvmthin", 832, 0.63),
                         ("tank", "zfspool", 3600, 0.86)],
             "guests": [(100, "pfsense", "vm", True), (101, "homeassistant", "vm", True),
                        (102, "nextcloud", "lxc", True), (103, "jellyfin", "lxc", True),
                        (104, "pihole", "lxc", True), (105, "wallmox", "lxc", True),
                        (110, "win11-lab", "vm", False), (111, "kali", "vm", False)]},
            {"name": "pve2", "cores": 4, "temp_base": 36,
             "disks": [("nvme0", "Crucial P3 500GB", 39)], "model": "Intel N100", "mem": 16 * GiB,
             "base_cpu": 9, "base_mem": 0.47, "uptime": 12 * 86400 + 19 * 3600,
             "storage": [("local", "dir", 58, 0.33), ("local-lvm", "lvmthin", 400, 0.52),
                         ("backup-nfs", "nfs", 7400, 0.71)],
             "guests": [(200, "docker-host", "lxc", True), (201, "unifi", "lxc", True),
                        (202, "grafana", "lxc", False)]},
        ]

    def __call__(self) -> dict:
        t = time.time() - self.start
        nodes = []
        for i, n in enumerate(self.nodes):
            wave = math.sin(t / 40.0 + i) * 12 + math.sin(t / 7.0 + i * 2) * 5
            cpu = max(1.0, min(99.0, n["base_cpu"] + wave + self.rng.uniform(-3, 6)))
            mem_used = n["mem"] * (n["base_mem"] + math.sin(t / 90.0 + i) * 0.03)
            nodes.append({
                "name": n["name"], "online": True, "error": None,
                "cpu": round(cpu, 1), "cores": n["cores"], "cpu_model": n["model"],
                "mem_used": mem_used, "mem_total": n["mem"],
                "mem_pct": round(100.0 * mem_used / n["mem"], 1),
                "uptime": n["uptime"] + t,
                "loadavg": [round(cpu / 100 * n["cores"] * f, 2) for f in (1.0, 0.9, 0.8)],
                "storage": [{"name": s, "type": ty, "used": size * GiB * frac,
                             "total": size * GiB, "pct": round(frac * 100, 1),
                             "shared": ty == "nfs"}
                            for s, ty, size, frac in n["storage"]],
                "agent_host": f"192.168.0.{20 + i}",
                "temp_error": None,
                "temps": {
                    "cpu": round(n["temp_base"] + cpu * 0.38 + self.rng.uniform(-0.8, 0.8), 1),
                    "disks": [{"name": d, "model": m, "temp": round(base + math.sin(t / 60.0 + i) * 1.5, 1)}
                              for d, m, base in n["disks"]],
                    "version": "demo",
                },
                "guests": sorted(
                    [{"vmid": v, "name": nm, "kind": k, "running": r,
                      "cpu": round(self.rng.uniform(0, 30), 1) if r else 0.0}
                     for v, nm, k, r in n["guests"]],
                    key=lambda g: (not g["running"], g["vmid"])),
            })
        return {"time": time.time(), "nodes": nodes}
