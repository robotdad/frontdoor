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

## Using with Amplifier

The `frontdoor` bundle gives Amplifier the knowledge to inventory your host, provision new web apps, and wire them into the shared Caddy + Tailscale infrastructure — following the port allocation, auth, and service discovery conventions used across all frontdoor-managed hosts.

### Prerequisites

- [Amplifier](https://github.com/microsoft/amplifier) installed:
  ```bash
  uv tool install git+https://github.com/microsoft/amplifier
  amplifier init   # configure your AI provider if you haven't yet
  ```
- Target host running **Tailscale** with **Caddy** installed

### Install the Bundle

```bash
amplifier bundle add git+https://github.com/robotdad/frontdoor@main
amplifier bundle use frontdoor --local   # activate for your current session
```

### Register the Skills

The skills ship in this repo's `skills/` directory and are discovered separately from the bundle. Register them once:

```bash
# In an Amplifier session:
load_skill(source="git+https://github.com/robotdad/frontdoor")
```

Once registered, `host-infra-discovery` and `web-app-setup` are available automatically whenever Amplifier thinks they're relevant — or you can invoke them explicitly.

### Typical Workflow

**Step 1 — Inventory the host before touching it:**
```
"Run host-infra-discovery on this host and give me the summary table"
```

**Step 2 — Set up a new web app:**
```
"Using that summary, help me set up a new app called myapp"
```

Amplifier will load the relevant skill, run the shell commands to detect available ports and existing infrastructure, generate deployment files in your project's `deploy/` directory from the templates, and leave activation to you — run `deploy/install.sh` when you're ready to go live.

### One-Shot (No Installation)

```bash
amplifier run --bundle git+https://github.com/robotdad/frontdoor@main \
  "What web apps are currently running on this host?"
```

### Keep Up to Date

```bash
amplifier bundle refresh frontdoor
```

## Status commands

Check the frontdoor service:

```bash
systemctl status frontdoor
```

Follow logs:

```bash
journalctl -u frontdoor -f
```
