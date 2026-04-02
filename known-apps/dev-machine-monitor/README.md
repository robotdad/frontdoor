# dev-machine-monitor

Dashboard and API for autonomous dev machines.

## Deployment

**Default ports:**
- External (Caddy): `8444`
- Internal (app): `8111`
- Frontdoor auth: `8420`

## Setup Steps

### 1. Deploy the Caddy config

```bash
sudo cp dev-machine-monitor.caddy /etc/caddy/conf.d/dev-machine-monitor.caddy
# Edit with actual FQDN, ports, and TLS cert paths, then:
sudo systemctl reload caddy
```

### 2. Deploy the frontdoor manifest

```bash
sudo cp dev-machine-monitor.json /opt/frontdoor/manifests/dev-machine-monitor.json
```

### 3. Install the systemd user service

```bash
cp dev-machine-monitor.service ~/.config/systemd/user/dev-machine-monitor.service
systemctl --user daemon-reload
systemctl --user enable --now dev-machine-monitor
```

## Server startup

The app must be started in `serve` mode with TLS and auth disabled (Caddy handles TLS,
frontdoor handles auth via `forward_auth`):

```bash
dev-machine-monitor serve --port 8111 --tls off --no-auth
```

Do NOT use the bare `dev-machine-monitor` command — that mode enables local-only
defaults (127.0.0.1, TLS off, auth off) but is not designed for production use.
