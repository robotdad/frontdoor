## System Architecture

frontdoor is the authentication gateway and service dashboard for a developer host. This document describes the system topology, request flows, and protocol handling patterns. For machine-readable architecture diagrams, see the DOT files in `docs/`.

### Architecture Diagrams (DOT/Graphviz)

These diagrams are the source of truth for system design. Load them for graph analysis or render with `dot -Tsvg <file>.dot`.

| Diagram | Path | What it covers |
|---------|------|---------------|
| System overview | `docs/architecture.dot` | Infrastructure, frontend, backend, discovery pipeline, auth core, downstream apps |
| Auth flows | `docs/auth-flow.dot` | HTTP and WebSocket authentication side by side, login flow |
| Protocol support | `docs/protocol-support.dot` | Protocol traversal patterns, decision flowchart for enabling new protocols |

### System Topology

```
User (browser)
  → Tailscale (optional VPN mesh, WireGuard-encrypted)
    → Caddy (TLS termination, reverse proxy, port 443)
      → forward_auth → frontdoor :8420 (validates every request)
        → 200 + X-Authenticated-User header
      → reverse_proxy → downstream app (filebrowser, your-app, etc.)
```

frontdoor runs on port 8420 as a FastAPI/uvicorn application behind Caddy. Caddy's `forward_auth` directive sends every incoming request to frontdoor's `/api/auth/validate` endpoint before proxying to the target app.

### Authentication: HTTP vs WebSocket

**HTTP requests** flow through `forward_auth` transparently. frontdoor's `require_auth()` validates the `frontdoor_session` cookie and returns 200 with the `X-Authenticated-User` header, or 401 which Caddy redirects to the login page.

**WebSocket upgrades** also flow through `forward_auth`, but require an explicit `@router.websocket("/api/auth/validate")` handler in frontdoor. Without this handler, FastAPI's `StaticFiles` catch-all receives the non-HTTP ASGI scope and crashes. The WebSocket handler (`validate_ws`) reads the session cookie from the handshake headers before accepting, then either:
- Accepts with `headers=[x-authenticated-user: <username>]` and immediately closes (Caddy treats accept as 200)
- Closes with code 4001 (Caddy treats close as 401)

This was a non-obvious requirement discovered during filebrowser's terminal integration. Any app with WebSocket support behind frontdoor's `forward_auth` benefits from this handler.

### Protocol Bypass Pattern (Caddy Limitation)

Some protocols cannot complete their handshake after `forward_auth` validation. Caddy 2.6 has a known limitation where WebSocket connections that pass through `forward_auth` may not proxy correctly to downstream apps. The workaround is a Caddy `handle` block that routes protocol-specific paths **before** the `forward_auth` block:

```caddy
# Bypass: route WebSocket paths directly to the app
handle /api/terminal* {
    reverse_proxy localhost:<app-port>
}

# Standard: everything else goes through auth
handle {
    forward_auth localhost:8420 {
        uri /api/auth/validate
        copy_headers X-Authenticated-User
    }
    reverse_proxy localhost:<app-port>
}
```

When an app uses this bypass, its WebSocket endpoints cannot rely on the `X-Authenticated-User` header from frontdoor. The app needs its own auth for those endpoints. The established pattern is a **cookie bridge**: the app's `/api/auth/me` endpoint detects frontdoor mode (header present, no local session cookie) and issues its own session cookie, which the WebSocket endpoint then validates independently.

### Discovery Pipeline

frontdoor discovers running services through four mechanisms:
1. **Caddy config parser** — reads `/etc/caddy/conf.d/*.caddy` for virtual host definitions and upstream ports
2. **Manifest overlay** — reads `/opt/frontdoor/manifests/*.json` for app display names, descriptions, icons
3. **TCP port prober** — scans ports 8440+ to find processes listening without Caddy configs
4. **Process scanner** — correlates listening ports with running processes

### Companion App: filebrowser

[filebrowser](https://github.com/robotdad/filebrowser) is designed to work with frontdoor. It demonstrates the full integration pattern including:
- `forward_auth` for HTTP request authentication
- WebSocket bypass for the terminal endpoint (`/api/terminal*`)
- Cookie bridge for WebSocket auth when `forward_auth` is bypassed
- Dual-mode auth (`X-Authenticated-User` header OR session cookie)
- Frontdoor-aware logout (redirects to frontdoor's logout endpoint)

When setting up new apps with similar needs, filebrowser's Caddy template and auth module serve as the reference implementation.
