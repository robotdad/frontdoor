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
