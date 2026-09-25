"""Run with: python -m wallmox [--config PATH] [--demo]"""

import argparse
import logging

from waitress import serve

from . import __version__
from .app import create_app
from .config import load_config


def main():
    parser = argparse.ArgumentParser(prog="wallmox", description="Wallmox status dashboard")
    parser.add_argument("--config", help="path to config.toml")
    parser.add_argument("--demo", action="store_true", help="show generated data")
    parser.add_argument("--port", type=int, help="override the listen port")
    parser.add_argument("--version", action="version", version=f"wallmox {__version__}")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    if args.demo:
        cfg.demo = True
    if args.port:
        cfg.port = args.port

    app = create_app(cfg)
    logging.getLogger("wallmox").info("Wallmox %s listening on http://%s:%s/status",
                                      __version__, cfg.listen, cfg.port)
    serve(app, host=cfg.listen, port=cfg.port, threads=4, ident="wallmox")


if __name__ == "__main__":
    main()
