"""Admin panel: sign-in and all settings that used to live in config.toml."""

import functools
import hmac
import re
import secrets
import shlex
import socket

from flask import (Blueprint, current_app, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)

from . import __version__
from .auth import (MIN_PASSWORD, Throttle, reload_password_hash, set_password,
                   verify_password)
from .config import LANGUAGES, ProxmoxConfig, save_settings, settings_path
from .i18n import LANGUAGE_NAMES, strings
from .proxmox import ProxmoxClient, ProxmoxError

bp = Blueprint("admin", __name__, url_prefix="/admin")


class FormError(ValueError):
    pass


# ---------------------------------------------------------------- helpers

def cfg():
    return current_app.config["WALLMOX"]


def poller():
    return current_app.extensions["wallmox_poller"]


def updates():
    return current_app.extensions["wallmox_updates"]


def throttle() -> Throttle:
    return current_app.extensions.setdefault("wallmox_throttle", Throttle())


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@bp.app_context_processor
def inject_csrf():
    return {"csrf_token": csrf_token}


@bp.before_request
def check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            if request.is_json or request.headers.get("X-CSRF-Token") is not None:
                return jsonify({"ok": False, "message": g.S["session_expired"]}), 400
            flash(g.S["session_expired"], "error")
            return redirect(request.referrer or url_for("admin.settings"))


def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def number(name, label, lo, hi, kind=int):
    raw = request.form.get(name, "").strip().replace(",", ".")
    try:
        value = kind(float(raw)) if kind is int else kind(raw)
    except ValueError:
        value = None
    if value is None or not lo <= value <= hi:
        raise FormError(g.S["invalid_number"].format(field=label, min=lo, max=hi))
    return value


def checkbox(name) -> bool:
    return request.form.get(name) == "on"


def clean_host(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0]
    if value.count(":") == 1:          # host:port, but leave IPv6 alone
        value = value.split(":")[0]
    return value


def known_names():
    """Node and storage names from the latest snapshot, for the display lists."""
    snap = poller().state()["snapshot"] or {"nodes": []}
    nodes = [n["name"] for n in snap["nodes"]]
    storages = sorted({s["name"] for n in snap["nodes"] for s in n.get("storage", [])})
    return nodes, storages


AGENT_INSTALL_URL = "https://raw.githubusercontent.com/krajcara/wallmox/main/agent/install.sh"


def own_ip(target: str) -> str:
    """This container's address on the way to Proxmox (for the firewall rule)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((target or "192.0.2.1", 9))
            return sock.getsockname()[0]
    except OSError:
        return ""


def agent_command(c) -> str:
    env = [f"WALLMOX_AGENT_KEY={c.agent_key}"]
    if c.agent_port != 9105:
        env.append(f"WALLMOX_AGENT_PORT={c.agent_port}")
    ip = own_ip(c.proxmox.host)
    if ip and not ip.startswith("127."):
        env.append(f"WALLMOX_AGENT_ALLOW={ip}")
    return " ".join(env) + f' bash -c "$(curl -fsSL {shlex.quote(AGENT_INSTALL_URL)})"'


def agent_rows(c, S):
    snap = poller().state()["snapshot"] or {"nodes": []}
    rows = []
    for n in snap["nodes"]:
        temps, err = n.get("temps"), n.get("temp_error")
        if not c.display.show_temps:
            status, state = S["agent_off"], "off"
        elif err:
            status, state = err, "error"
        elif temps is None:
            status, state = S["agent_waiting"], "waiting"
        elif temps.get("cpu") is None:
            status, state = S["agent_no_cpu"], "ok"
        else:
            status, state = S["agent_ok"].format(temp=round(temps["cpu"])), "ok"
        override = c.agent_hosts.get(n["name"], "")
        rows.append({"name": n["name"], "override": override,
                     "detected": "" if override else n.get("agent_host", ""),
                     "status": status, "state": state})
    return rows


def status_url(external=True):
    args = {"key": cfg().status_key} if cfg().status_key else {}
    return url_for("status", _external=external, **args)


def saved(section):
    save_settings(cfg())
    flash(g.S["saved"], "ok")
    return redirect(url_for("admin.settings") + f"#{section}")


# ---------------------------------------------------------------- sign-in

@bp.route("/login", methods=["GET", "POST"])
def login():
    c = cfg()
    reload_password_hash(c)
    error = None
    if request.method == "POST":
        addr = request.remote_addr or "?"
        if throttle().locked(addr):
            error = g.S["locked"]
        elif verify_password(c, request.form.get("password", "")):
            throttle().success(addr)
            session.clear()
            session["admin"] = True
            session.permanent = True
            nxt = request.args.get("next", "")
            if not nxt.startswith("/admin") or nxt.startswith("//"):
                nxt = url_for("admin.settings")
            return redirect(nxt)
        else:
            throttle().fail(addr)
            error = g.S["locked"] if throttle().locked(addr) else g.S["wrong_password"]
    return render_template("admin/login.html", S=g.S, cfg=c, error=error,
                           has_password=bool(c.admin_password_hash),
                           version=__version__)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


# ---------------------------------------------------------------- settings page

@bp.route("/")
@login_required
def settings():
    c = cfg()
    nodes, storages = known_names()
    updates().check_in_background()
    return render_template(
        "admin/settings.html", S=g.S, cfg=c, version=__version__,
        languages=[(code, LANGUAGE_NAMES[code]) for code in LANGUAGES],
        nodes=nodes, storages=storages,
        tablet_url=status_url(), preview_url=status_url(external=False),
        agent_cmd=agent_command(c), agents=agent_rows(c, g.S),
        upd=updates().info(), upd_state=updates().state(),
        settings_file=settings_path(c))


@bp.route("/save/<section>", methods=["POST"])
@login_required
def save(section):
    c = cfg()
    S = g.S
    try:
        if section == "general":
            c.title = (request.form.get("title", "").strip() or "Wallmox")[:40]
            lang = request.form.get("language", "en")
            c.language = lang if lang in LANGUAGES else "en"
            c.refresh_interval = number("refresh_interval", S["f_refresh"], 3, 300)
            c.poll_interval = number("poll_interval", S["f_poll"], 2, 300)
            poller().interval = c.poll_interval
            g.S = S = strings(c.language)   # confirm in the new language

        elif section == "proxmox":
            c.proxmox.host = clean_host(request.form.get("host", ""))
            c.proxmox.port = number("port", S["f_port"], 1, 65535)
            c.proxmox.token_id = request.form.get("token_id", "").strip()
            secret = request.form.get("token_secret", "").strip()
            if secret:
                c.proxmox.token_secret = secret
            c.proxmox.verify_ssl = checkbox("verify_ssl")
            poller().set_source(current_app.extensions["wallmox_make_source"](c))

        elif section == "thresholds":
            for name, label, top in (("cpu", S["th_cpu_pct"], 100), ("mem", S["th_mem_pct"], 100),
                                     ("storage", S["th_storage_pct"], 100),
                                     ("cpu_temp", S["th_cpu_temp"], 120),
                                     ("disk_temp", S["th_disk_temp"], 120)):
                warn = number(f"{name}_warn", f"{label}: {S['th_warn']}", 1, top, float)
                crit = number(f"{name}_crit", f"{label}: {S['th_crit']}", warn, top, float)
                c.thresholds[name].warn = warn
                c.thresholds[name].crit = crit

        elif section == "display":
            d = c.display
            d.show_trend = checkbox("show_trend")
            d.show_storage = checkbox("show_storage")
            d.show_guests = checkbox("show_guests")
            d.show_stopped_guests = checkbox("show_stopped_guests")
            d.show_cpu_model = checkbox("show_cpu_model")
            for field, form_key in (("hidden_nodes", "node"), ("hidden_storages", "storage")):
                known = request.form.getlist(f"known_{form_key}")
                shown = set(request.form.getlist(form_key))
                old = getattr(d, field)
                setattr(d, field, sorted({k for k in known if k not in shown}
                                         | {h for h in old if h not in known}))

        elif section == "temps":
            c.display.show_temps = checkbox("show_temps")
            c.agent_port = number("agent_port", S["f_agent_port"], 1, 65535)
            names = request.form.getlist("agent_node")
            hosts = request.form.getlist("agent_host")
            for name, host in zip(names, hosts):
                host = host.strip()
                if host:
                    c.agent_hosts[name] = host
                else:
                    c.agent_hosts.pop(name, None)

        elif section == "security":
            c.behind_proxy = checkbox("behind_proxy")

        else:
            return redirect(url_for("admin.settings"))

    except FormError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.settings") + f"#{section}")
    return saved(section)


@bp.route("/status-key", methods=["POST"])
@login_required
def status_key():
    c = cfg()
    c.status_key = secrets.token_urlsafe(12) if request.form.get("action") == "new" else ""
    return saved("security")


@bp.route("/agent-key", methods=["POST"])
@login_required
def agent_key():
    cfg().agent_key = secrets.token_urlsafe(24)
    return saved("temps")


@bp.route("/update/check", methods=["POST"])
@login_required
def update_check():
    updates().check(force=True)
    return redirect(url_for("admin.settings") + "#update")


@bp.route("/update/start", methods=["POST"])
@login_required
def update_start():
    info = updates().info()
    if not (info["newer"] and info["can_update"]):
        return jsonify({"ok": False, "message": g.S["upd_uptodate"]})
    return jsonify({"ok": updates().request()})


@bp.route("/update/status")
@login_required
def update_status():
    return jsonify(updates().state())


@bp.route("/password", methods=["POST"])
@login_required
def password():
    c = cfg()
    if not verify_password(c, request.form.get("current_password", "")):
        flash(g.S["wrong_password"], "error")
    elif len(request.form.get("new_password", "")) < MIN_PASSWORD:
        flash(g.S["pw_short"], "error")
    else:
        set_password(c, request.form["new_password"])
        flash(g.S["pw_changed"], "ok")
    return redirect(url_for("admin.settings") + "#security")


@bp.route("/test-proxmox", methods=["POST"])
@login_required
def test_proxmox():
    c = cfg()
    try:
        port = int(request.form.get("port") or 8006)
    except ValueError:
        port = 8006
    px = ProxmoxConfig(
        host=clean_host(request.form.get("host", "")),
        port=port,
        token_id=request.form.get("token_id", "").strip(),
        token_secret=request.form.get("token_secret", "").strip() or c.proxmox.token_secret,
        verify_ssl=checkbox("verify_ssl"),
        timeout=5.0,
    )
    if not (px.host and px.token_id and px.token_secret):
        return jsonify({"ok": False, "message": g.S["not_configured"]})
    try:
        client = ProxmoxClient(px)
        version = (client.get("/version") or {}).get("version", "?")
        nodes = client.get("/nodes") or []
    except ProxmoxError as exc:
        return jsonify({"ok": False, "message": str(exc)})
    return jsonify({"ok": True,
                    "message": g.S["test_ok"].format(version=version, nodes=len(nodes))})
