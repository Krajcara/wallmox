"""Read-only Proxmox VE API client and snapshot collector."""

import logging
import time

import requests
import urllib3

log = logging.getLogger(__name__)


class ProxmoxError(Exception):
    """A problem talking to the Proxmox API, with a message fit for the screen."""


class ProxmoxClient:
    def __init__(self, cfg):
        self.base = f"https://{cfg.host}:{cfg.port}/api2/json"
        self.timeout = cfg.timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = (
            f"PVEAPIToken={cfg.token_id}={cfg.token_secret}")
        self.session.verify = cfg.verify_ssl
        if cfg.verify_ssl is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get(self, path: str, **params):
        try:
            resp = self.session.get(self.base + path, params=params or None,
                                    timeout=self.timeout)
        except requests.exceptions.SSLError as exc:
            raise ProxmoxError(
                "TLS certificate check failed. Set verify_ssl = false or "
                "point it to the CA file.") from exc
        except requests.RequestException as exc:
            raise ProxmoxError(f"Cannot reach Proxmox at {self.base}") from exc

        if resp.status_code == 401:
            raise ProxmoxError("Proxmox rejected the API token. Check token_id and token_secret.")
        if resp.status_code == 403:
            raise ProxmoxError(f"The API token has no permission for {path}. "
                               "Give the user the PVEAuditor role on /.")
        if resp.status_code >= 400:
            raise ProxmoxError(f"Proxmox answered {resp.status_code} for {path}")
        return resp.json().get("data")


def _pct(used, total) -> float:
    return round(100.0 * used / total, 1) if total else 0.0


def collect(client: ProxmoxClient) -> dict:
    """Gather one snapshot of every node, its storage and guests."""
    nodes_raw = client.get("/nodes") or []
    guests_raw = client.get("/cluster/resources", type="vm") or []

    nodes = []
    for n in sorted(nodes_raw, key=lambda x: x.get("node", "")):
        name = n.get("node", "?")
        node = {
            "name": name,
            "online": n.get("status") == "online",
            "error": None,
            "cpu": round(100.0 * (n.get("cpu") or 0), 1),
            "cores": n.get("maxcpu") or 0,
            "cpu_model": "",
            "mem_used": n.get("mem") or 0,
            "mem_total": n.get("maxmem") or 0,
            "uptime": n.get("uptime") or 0,
            "loadavg": [],
            "storage": [],
            "guests": [],
        }

        if node["online"]:
            try:
                st = client.get(f"/nodes/{name}/status") or {}
                node["cpu"] = round(100.0 * (st.get("cpu") or 0), 1)
                mem = st.get("memory") or {}
                node["mem_used"] = mem.get("used", node["mem_used"])
                node["mem_total"] = mem.get("total", node["mem_total"])
                node["uptime"] = st.get("uptime", node["uptime"])
                node["loadavg"] = [float(x) for x in st.get("loadavg") or []]
                info = st.get("cpuinfo") or {}
                node["cores"] = info.get("cpus", node["cores"])
                node["cpu_model"] = info.get("model", "")

                for s in client.get(f"/nodes/{name}/storage") or []:
                    if not s.get("active") or not s.get("total"):
                        continue
                    node["storage"].append({
                        "name": s.get("storage", "?"),
                        "type": s.get("type", ""),
                        "used": s.get("used") or 0,
                        "total": s.get("total") or 0,
                        "pct": _pct(s.get("used") or 0, s.get("total")),
                        "shared": bool(s.get("shared")),
                    })
                node["storage"].sort(key=lambda s: s["name"])
            except ProxmoxError as exc:
                log.warning("Node %s: %s", name, exc)
                node["error"] = str(exc)

        node["mem_pct"] = _pct(node["mem_used"], node["mem_total"])

        for g in guests_raw:
            if g.get("node") != name or g.get("template"):
                continue
            node["guests"].append({
                "vmid": g.get("vmid"),
                "name": g.get("name") or str(g.get("vmid")),
                "kind": "lxc" if g.get("type") == "lxc" else "vm",
                "running": g.get("status") == "running",
                "cpu": round(100.0 * (g.get("cpu") or 0), 1),
            })
        node["guests"].sort(key=lambda g: (not g["running"], g["vmid"] or 0))
        nodes.append(node)

    return {"time": time.time(), "nodes": nodes}
