---
bundle:
  name: frontdoor
  version: 0.1.0
  description: Web app deployment and management for developer hosts

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
---

# frontdoor

`frontdoor` is an Amplifier bundle for creating, deploying, and managing web apps on developer hosts. It provides skills for host inventory and app provisioning, deployment templates, and documents the conventions shared across all apps on a host.

## Skills

| Skill | Purpose |
|-------|---------|
| `host-infra-discovery` | Inventory a host before touching it — detects existing Caddy configs, allocated ports, cert infrastructure, systemd services, and shared components to reuse vs. install fresh. |
| `web-app-setup` | Provision a new web app — fills shared infra gaps and creates per-app config (Caddy virtual host, systemd service, frontdoor manifest). Always run `host-infra-discovery` first. |

## Templates

| Template | Description |
|----------|-------------|
| `app.caddy.template` | Caddy virtual host snippet — reverse-proxies a local port over HTTPS via Tailscale TLS, includes `forward_auth` for shared authentication. |
| `app.service.template` | systemd service unit for running a web app as a non-root user with automatic restart. |
| `install.sh.template` | Bootstrap script template for installing a new app to `/opt/<name>`, creating a venv, and wiring up the service and Caddy config. |
| `frontdoor.json.template` | App manifest template dropped into `/opt/frontdoor/manifests/`. Describes the app for the frontdoor service discovery dashboard. |
| `signout-link.html.template` | Reusable sign-out link snippet that posts to `/api/auth/logout` with the shared `frontdoor_session` cookie. Embed in any app's UI. |

@frontdoor:context/conventions.md
