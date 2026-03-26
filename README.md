# frontdoor

**frontdoor** is a developer-host dashboard and shared authentication gateway. It runs on your Tailscale-connected machine and gives you a single HTTPS URL that shows all your locally-running web apps in one place.

## What frontdoor does

- **Discovers services** from Caddy virtual host configs in `/etc/caddy/conf.d/` and TCP probing of known ports — no manual registration required for most apps.
- **Shows status** with green/red dots: green means the upstream port is responding, red means it's down.
- **Shared auth via domain cookie** — one login covers all apps on the host. frontdoor sets a `frontdoor_session` cookie on the root domain; apps that check this cookie get authentication for free.
- **Detects unregistered processes** — TCP probe of the 8440+ port range surfaces processes that are listening but have no Caddy config yet, so nothing hides from the dashboard.

## Install

```bash
sudo deploy/install.sh
```

### What the installer does

1. **Installs to `/opt/frontdoor`** — copies the app, creates a virtualenv, installs Python dependencies.
2. **Migrates filebrowser to `conf.d/`** — moves the filebrowser Caddy config into `/etc/caddy/conf.d/` and updates it to run on port 8447, freeing up the default port.
3. **Takes over port 443** — configures Caddy to serve frontdoor on the host's Tailscale FQDN over HTTPS.
4. **Short hostname redirect** — adds a redirect so `http://<short-hostname>/` resolves to the HTTPS Tailscale address.
5. **Creates `manifests/`** — initialises `/opt/frontdoor/manifests/` for per-app JSON metadata files that apps can drop in to customize their dashboard entry.

## Amplifier bundle

frontdoor ships as an **Amplifier bundle** (`bundle.md`). The bundle packages:

- **Skills** for host inventory (`host-infra-discovery`) and app provisioning (`web-app-setup`) — use these in an Amplifier session to set up new apps on this host.
- **Templates** for Caddy configs, systemd units, install scripts, app manifests, and sign-out links.

To use the skills in an Amplifier session, point your bundle config at this directory.

## Status commands

Check the frontdoor service:

```bash
systemctl status frontdoor
```

Follow logs:

```bash
journalctl -u frontdoor -f
```
