<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/branding/icons/frontdoor-icon-128.png">
    <source media="(prefers-color-scheme: light)" srcset="assets/branding/icons/frontdoor-icon-128.png">
    <img alt="frontdoor" src="assets/branding/icons/frontdoor-icon-128.png" width="80">
  </picture>
</p>

# frontdoor

**frontdoor** is a developer-host dashboard and shared authentication gateway. It runs on your Linux machine and provides a single authenticated entry point that shows all your locally-running web apps in one place.

## What frontdoor does

- **Discovers services** from Caddy virtual host configs in `/etc/caddy/conf.d/` and TCP probing of known ports — no manual registration required for most apps.
- **Shows status** with green/red dots: green means the upstream port is responding, red means it's down.
- **Shared auth via domain cookie** — one login covers all apps on the host. frontdoor sets a `frontdoor_session` cookie on the root domain; apps that check this cookie get authentication for free.
- **Authenticated identity forwarding** — Caddy's `forward_auth` validates every request through frontdoor, then injects the `X-Authenticated-User` header into the proxied request so downstream apps know who's calling without implementing their own auth.
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
- Target host with **Caddy** installed. **Tailscale** is recommended for automatic cert provisioning and FQDN detection but is not required.

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

## Downstream app integration

Apps behind frontdoor receive the authenticated username via the `X-Authenticated-User` request header, injected by Caddy's `forward_auth`. No app-level auth needed.

**Reading the header:**
```python
user = request.headers.get("X-Authenticated-User", "unknown")
```

**Required Caddy snippet** (in `/etc/caddy/conf.d/<app>.caddy`):
```caddy
forward_auth localhost:8420 {
    uri /api/auth/validate
    copy_headers X-Authenticated-User
}
```

For the full integration guide (ports, manifests, sign-out, templates), see the `web-app-setup` skill.

### Companion app: filebrowser

[filebrowser](https://github.com/robotdad/filebrowser) is designed to work with frontdoor out of the box. When deployed together, filebrowser inherits frontdoor's SSO and its install script automatically configures the `forward_auth` integration.

## Protocol support

frontdoor validates authentication for both HTTP and WebSocket protocols. Understanding the protocol handling is important when integrating apps that use persistent connections.

### HTTP (works out of the box)

Standard HTTP requests flow through Caddy's `forward_auth` transparently:

```
Request → Caddy → forward_auth → frontdoor /api/auth/validate (HTTP)
  → validates frontdoor_session cookie
  → 200 + X-Authenticated-User header (success)
  → 401 (failure, Caddy redirects to /login)
```

### WebSocket (requires explicit handler)

Caddy's `forward_auth` sends WebSocket Upgrade requests to the validate endpoint. Without an explicit WebSocket handler, FastAPI's `StaticFiles` catch-all crashes on the non-HTTP ASGI scope. frontdoor handles this with a dedicated `@router.websocket("/api/auth/validate")` endpoint:

```
WS Upgrade → Caddy → forward_auth → frontdoor /api/auth/validate (WebSocket)
  → validate_ws() reads cookie from handshake headers (before accept)
  → websocket.accept(headers=[x-authenticated-user: <name>]) + close()  (success)
  → websocket.close(code=4001)  (failure, 401-equivalent)
```

Key details:
- The session cookie is available on WebSocket handshake headers **before** accept -- no need to accept the connection first
- Close code `4001` is the 401-equivalent for WebSocket; Caddy interprets close as auth failure
- The `websockets` library (v16+) is pulled in transitively via `uvicorn[standard]`

### Enabling additional protocols

If a new protocol doesn't work through `forward_auth`, the pattern is:

1. **Check if `forward_auth` passes the protocol correctly.** If yes, no changes needed.
2. **If the protocol needs a persistent connection** (like WebSocket), the downstream app may need to:
   - Add a Caddy `handle` block to route protocol-specific paths before `forward_auth`
   - Implement a cookie bridge to issue an app-level session cookie for protocol auth
   - See [filebrowser's terminal WebSocket bypass](https://github.com/robotdad/filebrowser) for the working pattern
3. **If the protocol is HTTP-based** (like SSE), it should work through `forward_auth` without changes.

The general Caddy bypass pattern:
```caddy
# Route protocol-specific paths BEFORE forward_auth
handle /api/<protocol-path>* {
    reverse_proxy localhost:<app-port>
}

# Everything else goes through auth
handle {
    forward_auth localhost:8420 {
        uri /api/auth/validate
        copy_headers X-Authenticated-User
    }
    reverse_proxy localhost:<app-port>
}
```

See `docs/protocol-support.dot` for the full decision flowchart.

## Architecture diagrams

The `docs/` directory contains DOT/Graphviz architecture diagrams. These are the source of truth for system design -- no rendered images are committed. View them with `dot -Tsvg <file>.dot` or a live Graphviz preview extension.

| Diagram | What it covers |
|---------|---------------|
| `docs/architecture.dot` | System overview: infrastructure, frontend, backend, discovery pipeline, auth core, downstream apps |
| `docs/auth-flow.dot` | HTTP and WebSocket auth flows side by side, login flow, why WebSocket needs special handling |
| `docs/protocol-support.dot` | Protocol traversal patterns, decision flowchart for enabling new protocols, Caddy config patterns |

These diagrams are particularly useful for AI agents working on this codebase -- they encode the system topology in a machine-parseable format that can be analyzed with graph tools.

## Status commands

Check the frontdoor service:

```bash
systemctl status frontdoor
```

Follow logs:

```bash
journalctl -u frontdoor -f
```
