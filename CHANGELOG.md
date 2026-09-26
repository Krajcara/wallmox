# Changelog

## 0.4.1

- `update` and the installer accept release tags written as `V1.2.3` as well as `v1.2.3`.
- `update` forgets tags that were deleted on GitHub, so a release that was made
  twice no longer confuses it.

## 0.4.0

- Updates from the admin panel. The panel checks GitHub for new releases, shows
  what is new and updates with one click, following the log live. The page
  reloads by itself when Wallmox is back.
- A "New version" badge in the admin panel's top bar.
- The web app never runs as root: it only leaves a request file, and a systemd
  path unit starts the same `update` command you would type in the console
  (settings backup and automatic rollback included).

## 0.3.1

- Fixed: the installer stopped with "No module named wallmox" when setting the
  admin password. The app now works from any directory.
- New `wallmox` command in the container, e.g. `wallmox set-password`.
- The example config no longer contains a placeholder Proxmox connection.
- The installer prints an error only once.

## 0.3.0

- Temperatures. A small read-only agent (`agent/`) runs on each Proxmox node and
  reports the CPU and NVMe temperatures from the kernel's sensors. No lm-sensors,
  no extra packages, runs as an unprivileged user and needs a key.
- Status page: third gauge for the CPU temperature, disk temperatures under the
  storage bars, temperature as a dashed line in the CPU trend.
- Admin panel: new Temperatures section with the install command for the nodes
  (key filled in), the state of every node's agent, address overrides and a new
  key button. Warning levels for CPU and disk temperatures.
- Works with clusters: node addresses come from Proxmox, so new nodes only need
  the install command.

## 0.2.2

- Fixed: the installer did not run the app setup, so the install stopped with
  "invalid group: wallmox".
- The installer no longer creates an API token. The Proxmox connection is set up
  in the admin panel, which now shows the commands to create a read-only token.
- The installer asks for the static IP and the gateway separately.
- The installer asks where to store the Debian template when it is not downloaded yet.
- New SSH question: no SSH, root login with password, or root login with a key.
- No more locale warnings during the install.
- Wallmox stays quiet in the log until a Proxmox connection is configured.

## 0.2.1

- Installer asks for the container root password and DNS servers / search domain.
- Installer installs the newest release instead of the main branch
  (`WALLMOX_BRANCH=main` for the latest code).
- New `update` command inside the container: installs the newest release,
  backs up settings first and restores the previous version if the new one
  does not start. `update --check` and `update --main` are available too.

## 0.2.0

- Installer: one command in the Proxmox node shell creates the container,
  a read-only API token (PVEAuditor) and starts Wallmox.
- Admin panel at `/admin` with sign-in: status page title, language and
  intervals, what the tablet shows, hiding nodes and storages, warning levels,
  Proxmox connection with a connection test, status page key, reverse proxy
  option, password change, live tablet preview.
- Settings from the admin panel are stored in `/var/lib/wallmox/settings.json`
  and apply without a restart.
- `python -m wallmox set-password` sets or resets the admin password.
- Reverse proxy support (X-Forwarded-* headers) when enabled.
- `scripts/setup-container.sh` for manual installs and upgrades.

## 0.1.0

- Status page for tablets: CPU and RAM gauges with warn/crit zones, CPU trend,
  storage bars, VM and container list, clock.
- Works on Android 4.4 browsers (ES5, no CSS variables or grid, bundled font).
- Read-only Proxmox API access with an API token (PVEAuditor role).
- Background polling, stale-data banner when Proxmox stops answering.
- Demo mode with generated data.
- English and Serbian screen text.
