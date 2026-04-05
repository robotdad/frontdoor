---
name: web-app-setup
description: Use when setting up a new web app on a Linux or macOS host — provisions shared infra gaps and per-app config. Always run host-infra-discovery first and have its summary table ready before starting. Covers Tailscale-based deployments fully; other network setups get scoped notes only.
---

# Web App Setup

## Overview

Takes the summary table from `host-infra-discovery` and does the work. Two phases: fix shared infra gaps (same for every app, idempotent), then provision per-app config (always done fresh).

**Scope:** This skill fully specifies the Tailscale path. For other network setups, Phase 1 cert steps do not apply — see Non-Tailscale Notes at the end.

Prefix every command with `ssh <hostname>` for remote hosts.

---

## Platform Detection (Run Once, Reference Throughout)

```bash
OS=$(uname -s)   # "Linux" or "Darwin" — referenced in steps below
echo $OS
```

---

## Phase 1 — Shared Infra (Idempotent, Driven by Discovery Output)

Work through each gap row in the discovery table. Skip any row already at target state.

### Caddy not installed

```bash
# Linux
apt-get update -qq && apt-get install -y caddy
systemctl enable --now caddy

# macOS
brew install caddy
brew services start caddy
```

### Caddy conf.d not wired *(both platforms)*

```bash
mkdir -p /etc/caddy/conf.d
grep -q 'import.*conf.d' /etc/caddy/Caddyfile || \
    echo 'import /etc/caddy/conf.d/*.caddy' | tee -a /etc/caddy/Caddyfile
```

### TLS certs absent

Three options — pick the first that applies:

**Option A — Tailscale certs *(preferred; requires paid plan)*:**

```bash
FQDN=$(tailscale status --json | python3 -c \
    "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))")
mkdir -p /etc/ssl/tailscale
tailscale cert \
    --cert-file /etc/ssl/tailscale/$FQDN.crt \
    --key-file  /etc/ssl/tailscale/$FQDN.key \
    "$FQDN"
chown root:caddy /etc/ssl/tailscale/$FQDN.key
chmod 640        /etc/ssl/tailscale/$FQDN.key
CERT_PATH=/etc/ssl/tailscale/$FQDN.crt
KEY_PATH=/etc/ssl/tailscale/$FQDN.key
```

**Option B — Self-signed cert *(fallback; HTTPS works but browser shows warning)*:**

```bash
mkdir -p /etc/ssl/self-signed
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/ssl/self-signed/server.key \
    -out    /etc/ssl/self-signed/server.crt \
    -subj   "/CN=$(hostname -f)"
chown root:caddy /etc/ssl/self-signed/server.key
chmod 640        /etc/ssl/self-signed/server.key
CERT_PATH=/etc/ssl/self-signed/server.crt
KEY_PATH=/etc/ssl/self-signed/server.key
```

**Option C — No certs available *(HTTP only)*:**

Set `HTTPS=false` and use the HTTP Caddy snippet (no `tls` directive). Traffic is still encrypted end-to-end on WireGuard/Tailscale overlays; plaintext is only on the loopback or VPN tunnel, not the public internet.

### Cert renewal timer absent *(Tailscale + Linux only)*

```bash
cat > /etc/systemd/system/tailscale-cert-renew.service <<EOF
[Unit]
Description=Renew Tailscale TLS certificates
[Service]
Type=oneshot
ExecStart=/usr/bin/tailscale cert --cert-file /etc/ssl/tailscale/$FQDN.crt --key-file /etc/ssl/tailscale/$FQDN.key $FQDN
ExecStartPost=/usr/bin/chown root:caddy /etc/ssl/tailscale/$FQDN.key
ExecStartPost=/usr/bin/chmod 640 /etc/ssl/tailscale/$FQDN.key
ExecStartPost=/usr/bin/systemctl reload caddy
EOF
cat > /etc/systemd/system/tailscale-cert-renew.timer <<EOF
[Unit]
Description=Weekly Tailscale cert renewal
[Timer]
OnCalendar=weekly
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload && systemctl enable --now tailscale-cert-renew.timer
```

*macOS:* `tailscale cert` can be run via a `launchd` calendar plist if desired, but manual renewal on demand is also reasonable given certs are valid 90 days.

### Service user not in shadow group *(Linux only)*

```bash
# Linux only — not applicable on macOS (no /etc/shadow; auth uses Tailscale identity instead)
usermod -aG shadow <SERVICE_USER>
```

---

## Phase 2 — Per-App Provisioning (via frontdoor-admin)

`frontdoor-admin` is installed alongside frontdoor and handles all app provisioning
steps. Requires frontdoor to be active (`systemctl is-active frontdoor`).

### Step 1: Allocate ports

```bash
PORTS=$(frontdoor-admin ports next --json)
INTERNAL=$(echo $PORTS | jq .internal_port)
EXTERNAL=$(echo $PORTS | jq .external_port)
echo "Internal: $INTERNAL  External: $EXTERNAL"
```

### Step 2a: Register a custom app

One command writes the Caddy config, systemd unit, and manifest, then enables
and starts the service:

```bash
frontdoor-admin app register SLUG \
  --name "App Display Name" \
  --internal-port $INTERNAL \
  --external-port $EXTERNAL \
  --exec-start "/path/to/start/command" \
  --service-user USER \
  [--description "One-line description"] \
  [--icon "emoji-or-phosphor-icon"] \
  [--kill-mode process]       # for apps managing child processes (tmux, workers)
  [--ws-path "/ws*"]          # for apps with WebSocket endpoints (repeatable)
```

`--kill-mode process` — adds `KillMode=process` to the systemd unit. Use for apps
that manage long-lived child processes (tmux sessions, background workers) that
must survive service restarts.

`--ws-path` — adds a Caddy `handle` block that routes that path directly without
`forward_auth` (Caddy 2.6 limitation for WebSocket connections). Can be specified
multiple times.

### Step 2b: Install a pre-built known-app configuration

For apps with pre-validated configs in frontdoor's `known-apps/` directory:

```bash
# Check what's available
frontdoor-admin known-apps list

# Install
frontdoor-admin known-apps install APPNAME --service-user USER
```

Currently available: muxplex, filebrowser, amp-distro, dev-machine-monitor.

### Step 3: Verify

```bash
frontdoor-admin services list
```

The service should appear with `"status": "up"` and a `systemd_unit` field.

---

**Note on Phase 3:** When frontdoor is deployed and `frontdoor-admin app register`
is used for provisioning, Phases 3a–3f from the original skill are automatically
handled by the CLI. The Caddy config includes `forward_auth`, the manifest is
written, and auth is managed by frontdoor. No manual Phase 3 steps required.

---

## Phase 3 — Frontdoor Integration (When Frontdoor is Deployed)

Check whether frontdoor is deployed before applying this phase:

```bash
systemctl is-active frontdoor   # "active" → apply Phase 3; anything else → skip
```

If frontdoor is active, apply the subsections below instead of the per-app auth in section 2e.

---

### 3a. Reserved Ports

Never allocate ports from these ranges — they are claimed by frontdoor and its integrated services:

| Range | Reserved for |
|-------|-------------|
| 3000–3010 | Development servers |
| 4000–4010 | Development servers |
| 4200–4210 | Angular dev servers |
| 5000–5010 | Flask / general dev |
| 5173–5183 | Vite dev servers |
| 8000–8010 | FastAPI / Django dev |
| 8080–8090 | Generic HTTP proxies |
| 8410–8420 | Frontdoor and amplifierd |
| 8888–8898 | Jupyter notebooks |
| 9090–9100 | Prometheus / monitoring |
| Databases | All standard DB ports |

New apps always go in the **8440+** range.

**When frontdoor is installed**, use `frontdoor-admin ports next` for port
allocation instead of manual scanning — it checks Caddy configs, live sockets,
and the reserved ports registry in one call:

```bash
frontdoor-admin ports next --json
# → {"internal_port": 8450, "external_port": 8451}
```

**Fallback** (when frontdoor is not installed):

```bash
# Scan the registry for claimed ports
cat /etc/app-ports.conf 2>/dev/null || echo "NO_REGISTRY"

# Scan live sockets to confirm the port is truly free
ss -tlnp | awk '/127\.0\.0\.1/{print $4}' | sort   # Linux
netstat -an | awk '/tcp.*127\.0\.0\.1.*LISTEN/{print $4}' | sort   # macOS

# Start from 8440 and skip anything in either source above
```

---

### 3b. Caddy Snippet with `forward_auth`

When frontdoor is deployed, replace the basic `reverse_proxy` snippet with one that validates every request through frontdoor's auth endpoint before proxying.

The `forward_auth` block **must** appear before `reverse_proxy` and **must** include `copy_headers X-Authenticated-User` so the downstream app receives the verified identity.

`$CERT_PATH` and `$KEY_PATH` were established in Phase 1 — they point to `/etc/ssl/tailscale/` (Option A) or `/etc/ssl/self-signed/` (Option B) depending on what was detected. If no certs are available (Option C), omit the `tls` directive and use a plain `http://` block instead.

```caddy
# /etc/caddy/conf.d/<APPNAME>.caddy
# <EXTERNAL_PORT>: Caddy vhost port (all interfaces) — check conf.d for taken ports
# <INTERNAL_PORT>: app's listening port (127.0.0.1) — must differ from EXTERNAL_PORT
<FQDN>:<EXTERNAL_PORT> {
    tls <CERT_PATH> <KEY_PATH>  # Paths from Phase 1: /etc/ssl/tailscale/ or /etc/ssl/self-signed/

    forward_auth localhost:8420 {
        uri /api/auth/validate
        copy_headers X-Authenticated-User
    }

    reverse_proxy localhost:<INTERNAL_PORT>
}
```

Reload Caddy after writing the snippet:

```bash
systemctl reload caddy   # Linux
# brew services reload caddy   # macOS
```

#### WebSocket and Persistent Connection Support

If the app uses WebSocket endpoints (e.g. interactive terminal, real-time updates), Caddy's `forward_auth` may not correctly proxy the connection after validation (Caddy 2.6 limitation). The fix is a `handle` block that routes WebSocket paths **before** `forward_auth`:

```caddy
# /etc/caddy/conf.d/<APPNAME>.caddy
<FQDN>:<EXTERNAL_PORT> {
    tls <CERT_PATH> <KEY_PATH>

    # WebSocket paths bypass forward_auth (Caddy 2.6 limitation)
    handle /api/<websocket-path>* {
        reverse_proxy localhost:<INTERNAL_PORT>
    }

    # Everything else goes through frontdoor auth
    handle {
        forward_auth localhost:8420 {
            uri /api/auth/validate
            copy_headers X-Authenticated-User
        }
        reverse_proxy localhost:<INTERNAL_PORT>
    }
}
```

When bypassing `forward_auth`, the app's WebSocket endpoints **cannot** rely on the `X-Authenticated-User` header. The app needs its own auth for those endpoints. The established pattern is a **cookie bridge**:

1. The app's `/api/auth/me` endpoint detects frontdoor mode (`X-Authenticated-User` header present, no local session cookie)
2. It issues an app-level session cookie to the browser
3. The WebSocket endpoint validates that cookie independently via `resolve_authenticated_user()` which checks the header first, then the cookie

See filebrowser's terminal implementation for the complete reference pattern: Caddy bypass, cookie bridge, and dual-mode auth.

---

### 3c. Frontdoor Manifest

Each app registers itself with frontdoor by providing a manifest at `deploy/frontdoor.json`. Frontdoor reads this file to display the app in its dashboard.

```json
{
  "name": "<App Display Name>",
  "description": "<One-line description of what the app does>",
  "icon": "<emoji or icon identifier>"
}
```

Install the manifest so frontdoor can discover it:

```bash
# Create the manifest directory if it doesn't exist
mkdir -p /opt/frontdoor/manifests

# Copy the manifest — use the app slug as the filename
cp deploy/frontdoor.json /opt/frontdoor/manifests/<APPNAME>.json
```

Include this copy step in the app's install/deploy script so the manifest is always current after an update.

---

### 3d. Sign Out Pattern

Because frontdoor sets a **shared authentication cookie** at the domain level, apps must not attempt their own logout. Instead, redirect the user to frontdoor's logout endpoint, which clears the shared cookie for all apps simultaneously.

Use a form POST (not a GET link) to prevent CSRF and accidental prefetch:

```html
<form method="POST" action="https://<FRONTDOOR_FQDN>/api/auth/logout">
    <button type="submit">Sign out</button>
</form>
```

Or from a backend route:

```python
from fastapi.responses import RedirectResponse

@app.post("/signout")
async def signout():
    return RedirectResponse(
        url="https://<FRONTDOOR_FQDN>/api/auth/logout",
        status_code=303
    )
```

Do not clear any local session cookie on signout — the shared cookie is what matters, and only frontdoor can clear it.

---

### 3e. No App-Level Auth

When frontdoor is deployed **and** the Caddy snippet includes `forward_auth` (section 3b), **do not implement app-level authentication**. Every request that reaches the app has already been validated by frontdoor.

The app can read the authenticated user's identity from the request header set by `copy_headers`:

```python
# FastAPI example — no auth check needed, just read the header
@app.get("/")
async def index(request: Request):
    user = request.headers.get("X-Authenticated-User", "unknown")
    return {"user": user}
```

Do not add login forms, session cookies, or `require_tailscale_identity` middleware when this pattern is in effect. Frontdoor owns authentication; the app owns its business logic.

---

### 3f. Behind Frontdoor — App Hosting Pattern

When your app runs behind frontdoor (i.e., frontdoor is deployed and section 3b's `forward_auth` Caddy snippet is in place), follow these conventions to keep the integration clean:

**Bind localhost only — no external exposure:**

```bash
# Start your app bound to 127.0.0.1 only
ExecStart=<START_COMMAND> --host 127.0.0.1 --port <PORT>
```

Caddy handles all external traffic. The app never needs to accept connections from outside the loopback interface.

**No app-level TLS:**

Do not configure TLS inside the app. TLS termination happens at Caddy. The app speaks plain HTTP on localhost, which is safe — traffic from Caddy to the app never leaves the machine.

**No app-level auth:**

Frontdoor's `forward_auth` validates every request before it reaches the app. Do not add login forms, session cookies, PAM, or Tailscale identity middleware. Trust the request; it has already been authenticated.

**Read the authenticated user from the request header:**

```python
# FastAPI — frontdoor has already verified the user; just read the header
@app.get("/")
async def index(request: Request):
    user = request.headers.get("X-Authenticated-User", "unknown")
    return {"user": user}
```

The `X-Authenticated-User` header is injected by Caddy's `copy_headers` directive (section 3b) and contains the verified user identity from frontdoor.

**amplifierd-specific: enable proxy auth trust:**

If the app being deployed is `amplifierd`, set this environment variable so it trusts the proxy-injected identity instead of performing its own authentication:

```bash
Environment=AMPLIFIERD_TRUST_PROXY_AUTH=true
```

Add this to the systemd unit (or launchd plist `EnvironmentVariables` dict) alongside the other environment variables in section 2d.

---

## Known-App Configurations

For third-party apps that have been tested and integrated with frontdoor, pre-built
configs are in `frontdoor:known-apps/<appname>/`. Each directory contains a ready-to-use
Caddy config, systemd service file, frontdoor manifest, and a README explaining any
integration quirks specific to that app.

Check `known-apps/` before setting up a third-party app — if a config exists there, use
it instead of building from the generic templates above.

Currently documented: **muxplex** (tmux session dashboard).

---

## Completion Checklist

```bash
# Linux
systemctl status <APPNAME>
systemctl status caddy
# macOS
launchctl list | grep <APPNAME>
brew services list | grep caddy

# Both platforms
caddy validate --config /etc/caddy/Caddyfile
# Linux
ss -tlnp | grep <PORT>
# macOS
netstat -an | grep <PORT>

curl -sf https://<FQDN>:<PORT>/ -o /dev/null && echo OK
```

All checks green → done.

---

## Non-Tailscale Notes

This skill fully specifies the Tailscale path. If your host runs something else, here are things to consider — not step-by-step instructions, as these paths haven't been validated:

**Other mesh VPNs (WireGuard, ZeroTier, Nebula):** Network isolation is present but there's no built-in cert provisioning or identity API. You'll need a cert source — Caddy's automatic ACME works if you have a real domain; `mkcert` is worth looking at for LAN-only setups without a domain. The session cookie model and per-app secrets apply unchanged.

**Cloudflare Tunnel (`cloudflared`):** Cloudflare terminates TLS at their edge — skip the cert generation and renewal steps. Cloudflare Access can handle outer authentication and passes the verified identity in a request header. Caddy is still useful for local port routing but needs no `tls` directive.

**No overlay (LAN or public IP):** Caddy's automatic ACME handles Let's Encrypt if you have a domain pointed at the machine — no manual cert steps needed. For LAN-only without a domain, `mkcert` is worth investigating. Auth carries full weight here since there's no network-layer trust boundary.
