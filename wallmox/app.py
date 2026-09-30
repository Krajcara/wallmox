"""Flask application: tablet status page, admin panel and a small JSON API."""

import hmac
import logging
import secrets
import time

from flask import (Flask, abort, g, jsonify, redirect, render_template,
                   request, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

from . import __version__
from .config import proxmox_ready, save_settings
from .demo import DemoSource
from .i18n import strings
from .poller import Poller
from .proxmox import ProxmoxClient, collect
from .temps import add_temps
from .updates import UpdateChecker
from .tablets import Tablets
from .ui import build_view

log = logging.getLogger(__name__)


def make_source(cfg):
    """Pick where snapshots come from: demo data, Proxmox, or nothing yet."""
    if cfg.demo:
        return DemoSource()
    if not proxmox_ready(cfg):
        return None          # the poller idles until the admin panel sets it up
    client = ProxmoxClient(cfg.proxmox)

    def source():
        snap = collect(client)
        if cfg.display.show_temps and cfg.agent_key:
            add_temps(snap, client, cfg)
        return snap
    return source


class DynamicProxyFix:
    """Apply ProxyFix only while the 'behind a reverse proxy' setting is on."""

    def __init__(self, app, cfg):
        self.raw = app
        self.fixed = ProxyFix(app, x_for=1, x_proto=1, x_host=1, x_port=1)
        self.cfg = cfg

    def __call__(self, environ, start_response):
        target = self.fixed if self.cfg.behind_proxy else self.raw
        return target(environ, start_response)


def ensure_secret_key(cfg) -> str:
    if not cfg.secret_key:
        cfg.secret_key = secrets.token_hex(32)
        try:
            save_settings(cfg)
        except OSError as exc:
            log.warning("Cannot store the session key (%s). Admin sign-ins "
                        "will not survive a restart.", exc)
    return cfg.secret_key


def ensure_agent_key(cfg) -> None:
    if not cfg.agent_key:
        cfg.agent_key = secrets.token_urlsafe(24)
        try:
            save_settings(cfg)
        except OSError as exc:
            log.warning("Cannot store the agent key (%s).", exc)


def create_app(cfg, start_poller: bool = True) -> Flask:
    app = Flask(__name__)
    app.config["WALLMOX"] = cfg
    app.config.update(
        SECRET_KEY=ensure_secret_key(cfg),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=12 * 3600,
    )
    app.wsgi_app = DynamicProxyFix(app.wsgi_app, cfg)
    ensure_agent_key(cfg)

    poller = Poller(make_source(cfg), cfg.poll_interval, cfg.history_size)
    app.extensions["wallmox_poller"] = poller
    app.extensions["wallmox_make_source"] = make_source
    app.extensions["wallmox_updates"] = UpdateChecker(cfg.data_dir)
    tablets = Tablets()
    app.extensions["wallmox_tablets"] = tablets
    if start_poller:
        poller.start()

    if cfg.demo:
        log.info("Demo mode: showing generated data.")

    @app.before_request
    def load_strings():
        g.S = strings(cfg.language)

    def check_key():
        if cfg.status_key and not hmac.compare_digest(
                request.args.get("key", ""), cfg.status_key):
            abort(403)

    def key_args():
        return {"key": cfg.status_key} if cfg.status_key else {}

    def context():
        view = build_view(poller.state(), cfg, g.S)
        return {"view": view, "S": g.S, "cfg": cfg, "version": __version__,
                "hint_url": url_for("api_tablet_hint", **key_args()),
                "tablet": tablets.for_ip(request.remote_addr or ""),
                "fragment_url": url_for("status_fragment", **key_args())}

    @app.after_request
    def headers(resp):
        if request.path.startswith(("/status", "/api", "/admin")):
            resp.headers["Cache-Control"] = "no-store"
        if request.path.startswith("/admin"):
            resp.headers["X-Frame-Options"] = "DENY"
            resp.headers["Referrer-Policy"] = "same-origin"
        return resp

    @app.route("/")
    def index():
        return redirect(url_for("status", **request.args))

    @app.route("/status")
    def status():
        check_key()
        return render_template("status.html", **context())

    @app.route("/status/fragment")
    def status_fragment():
        check_key()
        return render_template("_dashboard.html", **context())

    @app.route("/api/snapshot")
    def api_snapshot():
        check_key()
        st = poller.state()
        return jsonify({"version": __version__, "snapshot": st["snapshot"],
                        "error": st["error"], "last_ok": st["last_ok"]})

    @app.route("/api/night", methods=["GET", "POST"])
    def api_night():
        """Night mode schedule for the tablet's screen helper.

        The helper POSTs its battery / charger / WiFi status and gets the schedule back."""
        check_key()
        if request.method == "POST":
            tablets.report(request.form, request.remote_addr or "")
        nm = cfg.night
        data = {"enabled": nm.enabled, "start": nm.start, "end": nm.end, "mode": nm.mode,
                "night_level": nm.dim_level, "day_level": nm.day_level, "method": nm.method}
        if request.args.get("format") == "env":
            lines = [f"{k.upper()}={int(v) if isinstance(v, bool) else v}" for k, v in data.items()]
            return app.response_class("\n".join(lines) + "\n", mimetype="text/plain")
        return jsonify(data)

    @app.route("/api/tablet-event", methods=["POST"])
    def api_tablet_event():
        check_key()
        tablets.event(request.form, request.remote_addr or "")
        return jsonify({"ok": True})

    @app.route("/api/tablet-hint")
    def api_tablet_hint():
        check_key()
        return jsonify(tablets.hint(request.remote_addr or ""))

    @app.route("/healthz")
    def healthz():
        st = poller.state()
        ok = st["last_ok"] is not None and time.time() - st["last_ok"] < cfg.poll_interval * 6
        return jsonify({"ok": ok, "version": __version__}), (200 if ok else 503)

    from .admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    return app
