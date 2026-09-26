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

Everything is set up in an admin panel on the same address, including a live
preview of the tablet screen.

![Wallmox admin panel](docs/admin.png)

## Install

Open the **Shell** of a Proxmox node and run:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/krajcara/wallmox/main/install.sh)"
```

The installer asks for:

- container ID, hostname, storage, disk size, memory and cores (defaults: next free ID, `wallmox`, 4 GB, 512 MB, 1 core),
- where to store the Debian template, if it is not downloaded yet,
- IP address: DHCP, or a static address and gateway,
- DNS servers and search domain (empty = same as the Proxmox node),
- SSH access for root: none, with the root password, or with an SSH key,
- the root password,
- the language of the status page and admin panel.

Then it creates an unprivileged Debian container, installs the newest Wallmox
release and prints the admin panel address and a generated admin password.
Nothing is installed on the Proxmox node itself.

### Connect Wallmox to Proxmox

Open the admin panel, section **Proxmox connection**. It shows these three
commands; run them in the Shell of any Proxmox node:

```bash
pveum user add wallmox@pve --comment "Wallmox (read-only)"
pveum acl modify / --users wallmox@pve --roles PVEAuditor
pveum user token add wallmox@pve wallmox --privsep 0
```

Enter the node address, token ID `wallmox@pve!wallmox` and the `value` from the
last command, press **Test connection**, then **Save**. The role PVEAuditor can
only read, so Wallmox never changes anything in Proxmox.

### Temperatures

Proxmox does not report temperatures, so Wallmox reads them from a small agent
on each node. Open the admin panel, section **Temperatures**, copy the command
shown there (your key is already in it) and run it in the Shell of every node:

```bash
WALLMOX_AGENT_KEY=... bash -c "$(curl -fsSL https://raw.githubusercontent.com/krajcara/wallmox/main/agent/install.sh)"
```

The agent is one Python file using only the standard library. It reads the
kernel's sensors (no lm-sensors needed), runs as an unprivileged user, answers
only requests with the key and cannot change anything. It reports the CPU
temperature and NVMe drives; SATA drives only show up when the kernel's
`drivetemp` module is loaded. Run the same command again to update the agent;
add `WALLMOX_AGENT_UNINSTALL=1` in front to remove it.

When a node joins the cluster, run the command there as well. Wallmox finds
the node's address through Proxmox.

## Try it without Proxmox

```bash
git clone https://github.com/krajcara/wallmox.git && cd wallmox
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m wallmox --demo
```

Open `http://<your-ip>:8080/status`. For the admin panel, set a password first
with `venv/bin/python -m wallmox set-password`.

## Admin panel

Open `http://<container-ip>:8080/admin`. There you can:

- change the title, language and refresh intervals,
- choose what the tablet shows, and hide single nodes or storages,
- set the amber and red warning levels,
- change and test the Proxmox connection,
- protect the status page with a key, and set the reverse proxy option,
- change the admin password.

Forgot the password? In the container run:

```bash
wallmox set-password
```

## Updating

In the admin panel, section **Updates**, click **Update to vX.Y.Z** when a new
release is out. The panel shows what is new and follows the update live.

You can also open the container console in Proxmox (or run `pct enter <ID>` on
the node) and run:

```bash
update
```

It installs the newest release, backs up your settings to
`/var/lib/wallmox/backups` first, and puts the previous version back if the new
one does not start. `update --check` only tells you whether there is a new
version, `update --main` installs the latest development code.

### Upgrading from 0.1

The `update` command does not exist in 0.1 yet. Run this once in the container:

```bash
cd /opt/wallmox && git pull
bash scripts/setup-container.sh
wallmox set-password
systemctl restart wallmox
```

Your `config.toml` keeps working. Once you save something in the admin panel,
its settings take precedence over the file. From then on, use `update`.

## Releases

`update` and the installer follow GitHub releases: tag a release as `vX.Y.Z`
(matching `__version__` in `wallmox/__init__.py`) and every container picks it
up with `update`.

## Manual install

In a Debian 12 or 13 container:

```bash
apt update && apt install -y git python3 python3-venv
git clone https://github.com/krajcara/wallmox.git /opt/wallmox
bash /opt/wallmox/scripts/setup-container.sh
wallmox set-password
systemctl start wallmox
```

Then connect it to Proxmox in the admin panel as described above.

## Behind a reverse proxy

Wallmox serves plain HTTP on port 8080. For HTTPS, put it behind Nginx Proxy
Manager, Caddy or Traefik, forward to `http://<container-ip>:8080`, and turn on
**Wallmox is behind a reverse proxy** in the admin panel. Keep the admin panel
reachable only from your own network.

## Setting up the tablet

- Use a browser that still supports your Android version. For Android 4.4 that
  is Chrome up to version 81 or Firefox up to version 68. The built-in browser
  also works.
- Open `http://<container-ip>:8080/status` and add it to the home screen.
- Keep the screen on: enable Developer options, then **Stay awake** (screen
  stays on while charging).
- A tablet that is always plugged in can develop a swollen battery. Check it
  from time to time.

## Files

| Path | What it is |
|---|---|
| `/etc/wallmox/config.toml` | Starting values written by the installer |
| `/var/lib/wallmox/settings.json` | Everything saved in the admin panel (wins over the TOML file) |
| `/opt/wallmox` | The app |

Logs: `journalctl -u wallmox -f`.

## Browser compatibility

The status page is written for old browsers on purpose: plain ES5 JavaScript,
flexbox without `gap`, no CSS variables or grid, server-drawn SVG, and a
bundled font (Barlow Semi Condensed, SIL OFL). Please keep it that way in pull
requests.

## Roadmap

- ~~**0.2** Installer run from the Proxmox host shell, admin panel for settings~~
- ~~**0.3** Temperatures through a small agent on each node~~
- ~~**0.4** Updates from the admin panel with rollback~~
- **1.0** Multi-node and cluster polish, documentation

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest
WALLMOX_DATA=./data python -m wallmox set-password
WALLMOX_DATA=./data python -m wallmox --demo
```

## License

MIT. The bundled font is licensed under the SIL Open Font License
(`wallmox/static/fonts/OFL.txt`).
