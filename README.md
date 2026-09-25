# Wallmox

Turn an old tablet into a wall-mounted Proxmox status dashboard.

Wallmox runs in a small LXC container, reads your Proxmox VE nodes through a
read-only API token and serves a lightweight status page that works even on
Android 4.4 browsers.

![Wallmox status page](docs/screenshot.png)

## What it shows

- CPU and RAM gauges per node, with amber and red zones at your thresholds
- CPU trend for the last few minutes
- Usage of every active storage
- VMs and containers, running ones first
- A banner when Proxmox stops answering, so old numbers never pass as current

> Status: **v0.1**. Installer, admin panel, temperatures and in-app updates
> are coming in the next releases (see [Roadmap](#roadmap)).

## Try it in 30 seconds

```bash
git clone https://github.com/krajcara/wallmox.git && cd wallmox
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m wallmox --demo
```

Open `http://<your-ip>:8080/status` on the tablet.

## Manual install (v0.1)

### 1. Create a read-only API token (Proxmox host shell)

```bash
pveum user add wallmox@pve --comment "Wallmox dashboard (read-only)"
pveum acl modify / --users wallmox@pve --roles PVEAuditor
pveum user token add wallmox@pve dash --privsep 0
```

Copy the `value` from the last command. Proxmox shows it only once.

### 2. Create the container

In the Proxmox web UI create an unprivileged LXC from a Debian 12 or 13
template: 1 core, 512 MB RAM, 4 GB disk is plenty.

### 3. Install Wallmox (inside the container)

```bash
apt update && apt install -y python3 python3-venv git
useradd --system --home /opt/wallmox --shell /usr/sbin/nologin wallmox
git clone https://github.com/krajcara/wallmox.git /opt/wallmox
python3 -m venv /opt/wallmox/venv
/opt/wallmox/venv/bin/pip install -r /opt/wallmox/requirements.txt

mkdir -p /etc/wallmox
cp /opt/wallmox/config.example.toml /etc/wallmox/config.toml
chown root:wallmox /etc/wallmox/config.toml && chmod 640 /etc/wallmox/config.toml
nano /etc/wallmox/config.toml     # host, token_id, token_secret

cp /opt/wallmox/systemd/wallmox.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now wallmox
```

Check it with `systemctl status wallmox` or `journalctl -u wallmox -f`.

## Setting up the tablet

- Use a browser that still supports your Android version. For Android 4.4 that
  is Chrome up to version 81 or Firefox up to version 68. The built-in browser
  also works.
- Open `http://<container-ip>:8080/status` and add it to the home screen.
- Keep the screen on: enable Developer options, then **Stay awake** (screen
  stays on while charging).
- A tablet that is always plugged in can develop a swollen battery. Check it
  from time to time.

## Configuration

All settings live in `/etc/wallmox/config.toml`. See
[`config.example.toml`](config.example.toml) for every option. After a change,
run `systemctl restart wallmox`.

## Browser compatibility

The status page is written for old browsers on purpose: plain ES5 JavaScript,
flexbox without `gap`, no CSS variables or grid, server-drawn SVG, and a
bundled font (Barlow Semi Condensed, SIL OFL). Please keep it that way in pull
requests.

## Roadmap

- **0.2** Installer run from the Proxmox host shell, admin panel for settings
- **0.3** Temperatures through a small agent on each node, longer history
- **0.4** Updates from the admin panel with rollback
- **1.0** Multi-node and cluster polish, documentation

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest
python -m wallmox --demo
```

## License

MIT. The bundled font is licensed under the SIL Open Font License
(`wallmox/static/fonts/OFL.txt`).
