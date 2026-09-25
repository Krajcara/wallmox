"""Flask application: the tablet status page and a small JSON API."""

import hmac
import logging
import time

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from . import __version__
from .demo import DemoSource
from .i18n import strings
from .poller import Poller
from .proxmox import ProxmoxClient, collect
from .ui import build_view

log = logging.getLogger(__name__)


def create_app(cfg, start_poller: bool = True) -> Flask:
    app = Flask(__name__)
    app.config["WALLMOX"] = cfg

    if cfg.demo:
        source = DemoSource()
        log.info("Demo mode: showing generated data.")
    else:
        client = ProxmoxClient(cfg.proxmox)
        source = lambda: collect(client)  # noqa: E731

    poller = Poller(source, cfg.poll_interval, cfg.history_size)
    app.extensions["wallmox_poller"] = poller
    if start_poller:
        poller.start()

    S = strings(cfg.language)

    def check_key():
        if cfg.status_key and not hmac.compare_digest(
                request.args.get("key", ""), cfg.status_key):
            abort(403)

    def key_args():
        return {"key": cfg.status_key} if cfg.status_key else {}

    def context():
        view = build_view(poller.state(), cfg, S)
        return {"view": view, "S": S, "cfg": cfg, "version": __version__,
                "fragment_url": url_for("status_fragment", **key_args())}

    @app.after_request
    def no_cache(resp):
        if request.path.startswith(("/status", "/api")):
            resp.headers["Cache-Control"] = "no-store"
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

    @app.route("/healthz")
    def healthz():
        st = poller.state()
        ok = st["last_ok"] is not None and time.time() - st["last_ok"] < cfg.poll_interval * 6
        return jsonify({"ok": ok, "version": __version__}), (200 if ok else 503)

    return app
