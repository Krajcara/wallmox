"""Command line.

  python -m wallmox                 run the server
  python -m wallmox --demo          run with generated data
  python -m wallmox set-password    set the admin panel password
"""

import argparse
import getpass
import logging
import sys

from . import __version__
from .config import load_config


def cmd_serve(args):
    from waitress import serve

    from .app import create_app

    cfg = load_config(args.config)
    if args.demo:
        cfg.demo = True
    if args.port:
        cfg.port = args.port
    app = create_app(cfg)
    logging.getLogger("wallmox").info("Wallmox %s listening on http://%s:%s/status",
                                      __version__, cfg.listen, cfg.port)
    serve(app, host=cfg.listen, port=cfg.port, threads=4, ident="wallmox")


def cmd_set_password(args):
    from .auth import MIN_PASSWORD, set_password

    cfg = load_config(args.config)
    if args.stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("New admin password: ")
        if getpass.getpass("Repeat it: ") != password:
            sys.exit("Passwords do not match.")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"Password needs at least {MIN_PASSWORD} characters.")
    set_password(cfg, password)
    print(f"Admin password saved in {cfg.data_dir}.")


def main():
    parser = argparse.ArgumentParser(prog="wallmox", description="Wallmox status dashboard")
    parser.add_argument("--config", help="path to config.toml")
    parser.add_argument("--version", action="version", version=f"wallmox {__version__}")
    parser.add_argument("--demo", action="store_true", help="show generated data")
    parser.add_argument("--port", type=int, help="override the listen port")
    sub = parser.add_subparsers(dest="command")
    sp = sub.add_parser("set-password", help="set the admin panel password")
    sp.add_argument("--stdin", action="store_true", help="read the password from stdin")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "set-password":
        cmd_set_password(args)
    else:
        cmd_serve(args)


if __name__ == "__main__":
    main()
