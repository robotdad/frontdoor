---
name: frontdoor
version: 0.1.0
---

# frontdoor Amplifier Bundle

`frontdoor` is an Amplifier bundle for creating, deploying, and managing web apps on developer hosts. It provides skills for host inventory and app provisioning, deployment templates, and documents the conventions shared across all apps on a host.

## Skills

| Skill | Purpose |
|-------|---------|
| `host-infra-discovery` | Inventory a host before touching it — detects existing Caddy configs, allocated ports, cert infrastructure, systemd services, and shared components to reuse vs. install fresh. |
| `web-app-setup` | Provision a new web app — fills shared infra gaps and creates per-app config (Caddy virtual host, systemd service, frontdoor manifest). Always run `host-infra-discovery` first. |

## Templates

| Template | Description |
|----------|-------------|
| `app.caddy.template` | Caddy virtual host snippet for a web app — reverse-proxies a local port over HTTPS via Tailscale TLS. Drop into `/etc/caddy/conf.d/` as `<name>.caddy`. |
| `app.service.template` | systemd service unit for running a web app as a non-root user with automatic restart. |
| `install.sh.template` | Bootstrap script template for installing a new app to `/opt/<name>`, creating a venv, and wiring up the service and Caddy config. |
| `frontdoor.json.template` | App manifest template dropped into `/opt/frontdoor/manifests/`. Describes the app for the frontdoor service discovery dashboard. |
| `signout-link.html.template` | Reusable sign-out link snippet that posts to `/auth/logout` with the shared `frontdoor_session` cookie. Embed in any app's UI to participate in shared auth. |

## Conventions

### HTTPS via Caddy + Tailscale

All apps are served over HTTPS through Caddy acting as a reverse proxy. TLS certificates come from Tailscale's built-in cert infrastructure (`tailscale cert`). Caddy virtual host configs live in `/etc/caddy/conf.d/` and are auto-included by the main `Caddyfile`.

### Shared Auth via `frontdoor_session` Cookie

A shared session cookie named `frontdoor_session` is set on the root domain (e.g., `monad.tail…ts.net`). Any app on that host can read this cookie to verify that the user has already authenticated through frontdoor. Apps that want to participate in shared auth should check for `frontdoor_session` and redirect to frontdoor's login if absent.

### Service Discovery via `conf.d/` + Manifests

frontdoor discovers running services two ways:

1. **Caddy configs** — scans `/etc/caddy/conf.d/*.caddy` to find reverse-proxy targets and their upstream ports.
2. **App manifests** — reads JSON files from `/opt/frontdoor/manifests/*.json` for richer metadata (display name, description, icon, health URL).

### Port Allocation from 8440+

New apps should allocate ports starting from **8440** and counting up (8441, 8442, …). This avoids conflicts with the reserved ranges below.

## Reserved Ports

The following port ranges are reserved by common development tools and should not be used for new apps:

| Range | Reserved for |
|-------|-------------|
| 3000–3010 | Node.js / React dev servers |
| 4000–4010 | Phoenix / Elixir / various |
| 4200–4210 | Angular dev server |
| 5000–5010 | Flask / Python dev servers |
| 5173–5183 | Vite dev server |
| 8000–8010 | Django / Python HTTP servers |
| 8080–8090 | Generic HTTP alt / Java / Go |
| 8410–8420 | frontdoor internal range |
| 8888–8898 | Jupyter notebooks |
| 9090–9100 | Prometheus / metrics |
| Various | Databases (PostgreSQL 5432, MySQL 3306, Redis 6379, MongoDB 27017) |
