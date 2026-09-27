# Changelog

## 0.6.0

- Battery and WiFi on the tablet. The screen helper reports the tablet's
  battery level, charger, battery temperature and WiFi signal every minute.
  The status page shows WiFi and battery icons next to the clock; the battery
  turns red with "on battery" when the charger is unplugged, and a warning
  appears when the battery gets warm.
- Admin panel: new Tablets section with every tablet's battery, WiFi and last
  report, plus warnings at the top when a tablet runs on battery or stops
  reporting.
- Android tablets without the helper show the battery from the browser, where
  the browser supports it.
- Fixed: the Copy buttons for commands copied nothing.

## 0.5.1

- Screen helper: follows redirects (e.g. http to https behind a reverse proxy),
  accepts only a real schedule and writes a clear message to the log when it
  cannot get one. Before, a redirect left the screen at day brightness without
  any message. Update it by running the install command on the tablet again.

## 0.5.0

- SATA drive temperatures. The agent installer loads the kernel's `drivetemp`
  module (kept after reboots), so SATA SSDs and hard disks show up next to NVMe
  drives. `WALLMOX_AGENT_DRIVETEMP=0` skips it for disks that should spin down.
- Separate warning levels for NVMe and SATA drives, and a switch to hide disk
  temperatures.
- Night mode, set in the admin panel: from/to time (by the tablet's clock),
  dim or turn off, night brightness.
  - "Darken the page" works in any browser, a tap wakes the screen for a minute.
  - "Control the backlight" uses a small helper on Linux kiosk tablets
    (`tablet/`), which really dims or switches off the backlight. The admin
    panel shows the install command.
- `/api/night` gives the schedule to the helper.

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
