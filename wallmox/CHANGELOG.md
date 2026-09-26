# Changelog

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
