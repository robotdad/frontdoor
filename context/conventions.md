## Conventions

### HTTPS via Caddy + TLS Certificates

All apps are served over HTTPS through Caddy acting as a reverse proxy. Caddy virtual host configs live in `/etc/caddy/conf.d/` and are auto-included by the main `Caddyfile`. TLS is configured via a three-tier priority:

1. **Tailscale certs** (recommended) — obtained via `tailscale cert`, stored in `/etc/ssl/tailscale/`, auto-renewed. Tailscale is recommended but not required.
2. **Self-signed certs** (fallback) — stored in `/etc/ssl/self-signed/`, generated with 10-year validity when Tailscale is unavailable.
3. **Plain HTTP** (ultimate fallback) — only acceptable on a Tailscale tailnet or other trusted LAN where traffic is otherwise protected.

The Caddy `tls` directive references whichever cert paths exist at runtime.

### Shared Auth via `frontdoor_session` Cookie

A shared session cookie named `frontdoor_session` is set on the root domain (e.g., `monad.tail…ts.net`). Any app on that host can read this cookie to verify that the user has already authenticated through frontdoor. Apps that want to participate in shared auth should check for `frontdoor_session` and redirect to frontdoor's login if absent.

`FRONTDOOR_SECURE_COOKIES` is `true` when HTTPS is active (both Tailscale and self-signed certs qualify), and `false` only for plain HTTP.

### Authenticated User Identity via `X-Authenticated-User` Header

When Caddy's `forward_auth` validates a request through frontdoor, the authenticated username is forwarded to the downstream app via the **`X-Authenticated-User`** request header. This is the canonical header name used across all frontdoor-managed apps.

Downstream apps read it like this:

```python
user = request.headers.get("X-Authenticated-User", "unknown")
```

The Caddy snippet that enables this:

```caddy
forward_auth localhost:8420 {
    uri /api/auth/validate
    copy_headers X-Authenticated-User
}
```

Apps behind `forward_auth` do not need their own login flow — every request that reaches them has already been authenticated. The header provides the verified identity.

### Protocol Support: HTTP and WebSocket

frontdoor's `/api/auth/validate` endpoint handles both HTTP and WebSocket protocols. This matters because Caddy's `forward_auth` sends the full incoming request — including WebSocket Upgrade requests — to the validate endpoint.

**HTTP** works transparently through `forward_auth`.

**WebSocket** requires an explicit `@router.websocket("/api/auth/validate")` handler in frontdoor. Without it, FastAPI's `StaticFiles` catch-all receives the WebSocket ASGI scope and crashes. The handler reads the session cookie from handshake headers before accept, then either accepts (with `X-Authenticated-User` header) or closes with code 4001 (401-equivalent).

### WebSocket Bypass Pattern for Downstream Apps

Caddy 2.6 has a limitation where WebSocket connections may not proxy correctly after `forward_auth` validation. When a downstream app needs WebSocket support (e.g. terminal, real-time features), use a Caddy `handle` block to route WebSocket paths before `forward_auth`:

```caddy
# Bypass forward_auth for WebSocket paths
handle /api/<websocket-path>* {
    reverse_proxy localhost:<app-port>
}

# Standard auth for everything else
handle {
    forward_auth localhost:8420 {
        uri /api/auth/validate
        copy_headers X-Authenticated-User
    }
    reverse_proxy localhost:<app-port>
}
```

When using this bypass, the app's WebSocket endpoints cannot rely on `X-Authenticated-User`. Instead, use the **cookie bridge pattern**: the app's `/api/auth/me` endpoint detects frontdoor mode (header present, no local session cookie) and issues an app-level session cookie. The WebSocket endpoint validates that cookie independently.

See filebrowser's terminal implementation for the reference pattern.

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
