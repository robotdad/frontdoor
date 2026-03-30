# frontdoor Developer Guide

Authentication gateway and service dashboard for developer hosts. One login covers every app on the machine via Caddy `forward_auth` and a shared `frontdoor_session` cookie.

This project is also an **Amplifier bundle** that ships skills and templates for provisioning new apps on the host.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| Web framework | FastAPI + Starlette |
| ASGI server | Uvicorn (`[standard]` extras for WebSocket support) |
| Auth | Linux PAM (`python-pam`) + HMAC-signed cookies (`itsdangerous`) |
| Frontend | Preact + HTM via CDN (`esm.sh`) -- zero build step |
| Icons / Fonts | Phosphor Icons v2, Inter + JetBrains Mono (Google Fonts) |
| Reverse proxy | Caddy (TLS termination, `forward_auth`, `reverse_proxy`) |
| Networking | Tailscale (preferred FQDN + cert source) |
| Service manager | systemd |
| Package manager | `uv` (lockfile committed) / `pip` |
| Build backend | setuptools |
| Test framework | pytest + httpx |
| Quality tools | ruff (lint/format), pyright (types) |

No Docker, no npm, no frontend build tooling.

## Directory Map

```
frontdoor/
|-- frontdoor/               # Python package
|   |-- main.py              # FastAPI app, router registration, static mount
|   |-- auth.py              # PAM auth, token create/validate, HMAC signer
|   |-- config.py            # Settings dataclass (reads env vars)
|   |-- discovery.py         # Caddy config parser, TCP probe, process scanner
|   |-- ports.py             # Reserved port set, next_available_port()
|   |-- routes/
|   |   |-- auth.py          # /login, /api/auth/validate, /api/auth/login, /api/auth/logout
|   |   +-- services.py      # GET /api/services
|   +-- static/
|       |-- index.html       # Dashboard SPA (Preact components, no build)
|       +-- login.html       # Login page (plain HTML/CSS)
|-- tests/                   # 14 test files (backend + doc/script validation)
|-- deploy/                  # Shell-script deployment (see Deployment below)
|-- docs/                    # Architecture diagrams (DOT) + hosting guide
|-- context/                 # Amplifier bundle context documents
|-- skills/                  # Amplifier skills (host-infra-discovery, web-app-setup)
|-- templates/               # Scaffold templates for new apps
|-- bundle.md                # Amplifier bundle manifest
|-- pyproject.toml           # Package metadata, deps, pytest config
+-- uv.lock                  # Deterministic dependency lockfile
```

## Amplifier Bundle

frontdoor doubles as an Amplifier AI bundle (`bundle.md`). When the bundle is active, an AI agent gets the context documents injected and can use the skills and templates to manage the host.

### Bundle manifest: `bundle.md`

Declares the bundle identity (`frontdoor` v0.1.0), inherits `amplifier-foundation`, and `@`-mentions the two context files so they load into agent context automatically.

### Context documents: `context/`

| File | What it provides |
|------|-----------------|
| `context/conventions.md` | Port allocation rules (8440+), reserved port table, cookie and header conventions, WebSocket bypass pattern |
| `context/architecture.md` | System topology, HTTP vs WebSocket auth flows, discovery pipeline, companion app integration pattern |

These are always injected into the agent's context when the bundle is active -- they define the rules an agent must follow when working on this host.

### Skills: `skills/`

| Skill | Purpose |
|-------|---------|
| `host-infra-discovery` | Inventory a host before touching it -- detects Caddy configs, allocated ports, cert infrastructure, systemd services, shared components |
| `web-app-setup` | Provision a new web app end-to-end. Always run `host-infra-discovery` first. Fills shared infra gaps and creates per-app config |

### Templates: `templates/`

| Template | Generates |
|----------|-----------|
| `app.caddy.template` | Caddy virtual host snippet (HTTPS, `forward_auth`, `reverse_proxy`) |
| `app.service.template` | systemd unit file for a web app |
| `install.sh.template` | Bootstrap installer for `/opt/<name>` |
| `frontdoor.json.template` | App manifest for the frontdoor dashboard |
| `signout-link.html.template` | Reusable sign-out HTML snippet |

## Architecture Diagrams (DOT)

| File | What it shows |
|------|--------------|
| `docs/architecture.dot` | System overview: browser, Tailscale, Caddy, frontdoor, companion apps, service discovery pipeline |
| `docs/auth-flow.dot` | HTTP and WebSocket authentication flows through Caddy `forward_auth` |
| `docs/protocol-support.dot` | Decision flowchart for protocol handling (HTTP vs WebSocket) |

Render with Graphviz: `dot -Tsvg docs/architecture.dot -o docs/architecture.svg`

## Configuration Files

### Build and package

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package metadata, runtime deps (fastapi, uvicorn, python-pam, itsdangerous, python-multipart, six), dev deps (pytest, httpx), dependency groups (pyright, ruff), pytest config |
| `uv.lock` | Full transitive dependency lockfile |

### Deployment artifacts: `deploy/`

| File | Purpose |
|------|---------|
| `install.sh` | Full installer: FQDN detection, PAM setup, rsync, venv, Caddy install, 3-tier TLS (Tailscale > self-signed > HTTP), systemd unit, env file |
| `update.sh` | Incremental update: rsync + pip upgrade + systemctl restart |
| `uninstall.sh` | Stop, disable, remove (with `--purge` option) |
| `frontdoor.service` | systemd unit template (`FRONTDOOR_USER` / `FRONTDOOR_DIR` placeholders, `sed`-substituted by `install.sh`) |

### Runtime config (generated at install, not committed)

| File | Location | Contents |
|------|----------|----------|
| `frontdoor.env` | `/opt/frontdoor/frontdoor.env` | `FRONTDOOR_SECRET_KEY`, `FRONTDOOR_SECURE_COOKIES`, `FRONTDOOR_COOKIE_DOMAIN`, `FRONTDOOR_LOG_LEVEL` (mode 0600) |

### Dot files

| File | Purpose |
|------|---------|
| `.gitignore` | Ignores `__pycache__/`, `*.egg-info/`, `.venv/`, `dist/`, `build/`, `.discovery/` |

No `.env`, `.dockerignore`, `.eslintrc`, or CI config.

## Development Workflow

### Setup

```bash
cd frontdoor
uv sync                          # or: python -m venv .venv && pip install -e ".[dev]"
```

### Run locally

```bash
uv run uvicorn frontdoor.main:app --reload --host 127.0.0.1 --port 8420
```

App object: `frontdoor.main:app`

### Test

```bash
uv run pytest                    # 14 test files, PAM is always mocked
```

Tests cover: auth lifecycle, token validation, service discovery, config, ports, routes, static files, deploy script structure, and doc content validation.

### Quality checks

```bash
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run pyright                   # type check
```

### Deploy to host

```bash
sudo deploy/install.sh           # first time (creates /opt/frontdoor, systemd, Caddy)
sudo deploy/update.sh            # incremental update (rsync + restart)
```

## Key Architectural Decisions

**SSO gateway pattern** -- frontdoor sits between Caddy and every app. Caddy's `forward_auth` sends every request to `GET /api/auth/validate`. Authenticated requests get `X-Authenticated-User` injected; unauthenticated ones redirect to `/login`. Apps never implement their own auth.

**No-build frontend** -- The dashboard is a single `index.html` using Preact + HTM loaded from `esm.sh`. No npm, no bundler, no transpiler. Components are real Preact components written with tagged template literals.

**PAM + HMAC cookies** -- Users authenticate with Linux system credentials via PAM. Sessions are HMAC-signed timestamps (`itsdangerous.TimestampSigner`), not server-stored.

**Service discovery pipeline** -- Four stages: parse Caddy `conf.d/*.caddy` files, TCP probe discovered ports, overlay JSON manifests from `/opt/frontdoor/manifests/`, scan for unregistered listeners via `ss -tlnp`.

**systemd + Caddy, no Docker** -- Designed for bare-metal/VM Linux hosts. The 3-tier TLS strategy (Tailscale cert > self-signed > HTTP) adapts to what's available.

## Relationship to filebrowser

[filebrowser](../filebrowser) is a companion web app that runs on the same host behind frontdoor's auth. It uses the `forward_auth` + `X-Authenticated-User` pattern described in `context/conventions.md`. Its Caddy config is a `conf.d/` drop-in managed by frontdoor's discovery pipeline.

## Existing Documentation

| File | Contents |
|------|----------|
| `README.md` | Project purpose, install instructions, downstream app integration, protocol handling |
| `docs/HOSTING.md` | TLS tiers, FQDN detection, env var reference, uninstall guide |
| `docs/debugging.md` | Logging configuration and troubleshooting |
| `context/conventions.md` | Port allocation, cookie, header, and WebSocket conventions |
| `context/architecture.md` | System topology, auth flows, discovery pipeline |
| `bundle.md` | Amplifier bundle manifest with skills and templates table |