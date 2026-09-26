"""Read temperatures from the Wallmox agents running on the Proxmox nodes."""

import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from .proxmox import ProxmoxError

log = logging.getLogger(__name__)
TIMEOUT = 2.5


def node_addresses(client) -> dict:
    """Node name -> IP, as Proxmox knows it (works for single nodes and clusters)."""
    try:
        entries = client.get("/cluster/status") or []
    except ProxmoxError as exc:
        log.info("Cannot read node addresses: %s", exc)
        return {}
    return {e["name"]: e["ip"] for e in entries
            if e.get("type") == "node" and e.get("name") and e.get("ip")}


def agent_url(host: str, port: int) -> str:
    host = host.strip()
    if host.startswith(("http://", "https://")):
        return host.rstrip("/") + "/temps"
    if ":" in host and not host.startswith("["):
        if host.count(":") == 1:          # host:port
            return f"http://{host}/temps"
        host = f"[{host}]"                # bare IPv6
    return f"http://{host}:{port}/temps"


def read_agent(host: str, cfg) -> dict:
    url = agent_url(host, cfg.agent_port)
    try:
        resp = requests.get(url, timeout=TIMEOUT,
                            headers={"Authorization": f"Bearer {cfg.agent_key}"})
    except requests.RequestException:
        return {"error": f"No agent answering at {url.rsplit('/', 1)[0]}"}
    if resp.status_code == 401:
        return {"error": "The agent rejected the key. Run the install command again."}
    if resp.status_code != 200:
        return {"error": f"The agent answered {resp.status_code}"}
    try:
        data = resp.json()
    except ValueError:
        return {"error": "The agent sent an invalid answer"}
    return {"cpu": data.get("cpu"),
            "disks": [d for d in data.get("disks", []) if d.get("temp") is not None],
            "version": data.get("version", "")}


def add_temps(snapshot: dict, client, cfg) -> None:
    """Attach temps / temp_error / agent_host to every online node of a snapshot."""
    nodes = [n for n in snapshot["nodes"] if n["online"]]
    if not nodes:
        return
    ips = node_addresses(client) if client is not None else {}
    jobs = {}
    for n in nodes:
        host = cfg.agent_hosts.get(n["name"]) or ips.get(n["name"])
        if not host and len(snapshot["nodes"]) == 1:
            host = cfg.proxmox.host
        n["agent_host"] = host or ""
        if host:
            jobs[n["name"]] = host
        else:
            n["temps"], n["temp_error"] = None, "No address known for this node"

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as pool:
        results = dict(zip(jobs, pool.map(lambda h: read_agent(h, cfg), jobs.values())))
    for n in nodes:
        if n["name"] not in results:
            continue
        res = results[n["name"]]
        if "error" in res:
            n["temps"], n["temp_error"] = None, res["error"]
        else:
            n["temps"], n["temp_error"] = res, None
