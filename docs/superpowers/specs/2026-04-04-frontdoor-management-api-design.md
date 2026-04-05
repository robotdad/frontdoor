# frontdoor Management API — Design Spec

**Date:** 2026-04-04  
**Status:** Approved for implementation planning  
**Scope:** Management API, `frontdoor-admin` CLI, bundle skill updates

---

## Overview

frontdoor currently exposes a read-only API (`GET /api/services`, auth endpoints). All
app provisioning is done by AI agents or humans running raw shell commands — writing
Caddy configs, systemd units, and manifest files directly to the filesystem. This is
fragile, verbose, and bypasses any coordination frontdoor could provide.

This design adds a full management API, a `frontdoor-admin` CLI that wraps it, and
updates the frontdoor Amplifier bundle skills to use the CLI instead of shell commands.
The result is a deterministic, API-driven provisioning workflow usable by any agent on
any host — including remote headless boxes across a Tailscale fleet.

### Goals

- REST management API for port allocation, app registration, service control, and
  known-app installation
- `frontdoor-admin` CLI for local and remote use — designed as the primary interface
  for AI agents as well as humans
- API token authentication for remote access across multiple machines
- Updated `web-app-setup` and `host-infra-discovery` bundle skills that use the CLI
- uv tool migration compatibility — no hardcoded paths to `/opt/frontdoor/`

### Non-Goals

- Per-app log streaming or live output tailing
- Multi-user ACLs or per-token permission scoping (all authenticated callers are
  equivalent)
- macOS / launchd support in the management API (skills still document that path)
- Web UI for service control (dashboard remains read-only for now)

---

## 1. Authentication Model

All `/api/admin/*` endpoints check credentials in this order. First match wins.

### Tier 1 — Localhost Bypass

Requests from `127.0.0.1` to any `/api/admin/*` endpoint are allowed without a token.
Matches the established pattern (muxplex uses this for its own localhost trust).

The check uses `request.client.host` (the actual TCP connection source), **not**
`X-Forwarded-For`. The `frontdoor-admin` CLI connects directly to uvicorn on
`localhost:8420`, bypassing Caddy entirely, so the TCP source is always `127.0.0.1`.
Caddy-proxied web traffic arrives on a different port and path — there is no overlap.

Controlled by `settings.allow_localhost_admin` (default: `True`). Can be set to
`False` in `frontdoor.env` for stricter deployments.

### Tier 2 — API Token

`Authorization: Bearer ft_<token>` header. The raw token value is hashed (SHA-256)
and compared against stored hashes. Never stored in plaintext.

Token format: `ft_` prefix + `secrets.token_urlsafe(32)` (43 chars of URL-safe base64).
Prefix makes frontdoor tokens unambiguous in logs and config files.

### Tier 3 — PAM Session Cookie

The existing `frontdoor_session` cookie (already used for the dashboard). Authenticated
via the existing `require_auth` dependency.

### `require_admin_auth` Dependency

New FastAPI dependency in `frontdoor/auth.py`. Returns the authenticated identity
(username string) or raises HTTP 401. Used on every `/api/admin/*` route.

Token creation (`POST /api/admin/tokens`) accepts Tier 1 or Tier 3 only — you cannot
create a token using another token. This prevents escalation if a token leaks.

### New Settings (`frontdoor/config.py`)

```python
tokens_file: Path      # default: Path("/opt/frontdoor/tokens.json")
                       # env: FRONTDOOR_TOKENS_FILE
allow_localhost_admin: bool  # default: True
                             # env: FRONTDOOR_ALLOW_LOCALHOST_ADMIN
self_unit: str         # default: "frontdoor.service"
                       # env: FRONTDOOR_SELF_UNIT
service_user: str      # default: "" (empty = detect from os.getlogin() at startup)
                       # env: FRONTDOOR_SERVICE_USER
                       # Used as the default --service-user in app registration
```

`tokens_file` is the only path that must move with a uv tool migration.
`FRONTDOOR_TOKENS_FILE=~/.config/frontdoor/tokens.json` covers that.

---

## 2. Token Storage

**File:** `/opt/frontdoor/tokens.json` (path from `settings.tokens_file`)

```json
{
  "tok_abc123": {
    "name": "robotdad-macbook",
    "token_hash": "<sha256 hex of the ft_... value>",
    "created_at": "2026-04-04T21:00:00Z",
    "last_used_at": "2026-04-04T22:30:00Z"
  }
}
```

- Token IDs (`tok_...`) are `"tok_" + secrets.token_hex(8)` — short, unique, human-readable
- Raw token shown once at creation, never stored
- `last_used_at` updated on each successful auth (best-effort, non-blocking write)
- File is read on every request — no in-process cache — so revocation is immediate

**Module:** `frontdoor/tokens.py`
- `create_token(name: str) -> tuple[str, str]` — returns `(token_id, raw_token)`
- `validate_token(raw_token: str) -> str | None` — returns token name on success, None on failure; used by `require_admin_auth` to populate the identity string
- `list_tokens() -> list[dict]` — names + IDs, never hashes
- `revoke_token(token_id: str) -> bool`

---

## 3. Management API

**New router:** `frontdoor/routes/admin.py`  
**Prefix:** `/api/admin`  
**Auth:** `require_admin_auth` on all routes  
**Registered in:** `frontdoor/main.py` alongside existing routers

### 3.1 Port Allocation

```
GET /api/admin/ports/next?start=8440
```

Returns the next available internal+external port pair. Checks three sources:

1. `/etc/caddy/conf.d/` — extracts both used external ports **and** registered internal
   ports from existing vhost configs (handles services that are currently down)
2. `ss -tlnp` — captures all currently-bound internal ports (live reality check)
3. `RESERVED_PORTS` from `frontdoor/ports.py`

The union of sources 1 and 2 for internal ports prevents reusing a port that belongs
to a registered-but-down service.

Returns two sequential free ports: `internal_port` (app binds here) and
`external_port` (Caddy listens here). They must differ — Caddy and the app cannot
share a port.

**Response:**
```json
{"internal_port": 8450, "external_port": 8451}
```

**Query params:**
- `start` (int, default 8440) — scan starts here

### 3.2 Manifests

Frontdoor owns `/opt/frontdoor/manifests/` — no elevated privilege required.

```
GET    /api/admin/manifests
PUT    /api/admin/manifests/{slug}
DELETE /api/admin/manifests/{slug}
```

**Slug validation:** `^[a-z0-9][a-z0-9-]*[a-z0-9]$` — enforced on all write
operations. Prevents path traversal.

**PUT body:**
```json
{
  "name": "My App",
  "description": "One-line description",
  "icon": "🚀"
}
```

`icon` accepts an emoji character or a Phosphor icon keyword (`folder`, `terminal`,
etc.). Both are already handled by the SPA.

**GET response:**
```json
[
  {
    "slug": "muxplex",
    "name": "Muxplex",
    "description": "Tmux session dashboard",
    "icon": "/muxplex-icon.png"
  }
]
```

### 3.3 Service Control

Discovery enrichment (from Section 4 below) adds `systemd_unit` to each service.
Service control endpoints resolve slug → unit using a two-pass strategy:

1. **Live resolution** — parse Caddy configs to find the service's internal port, look
   up the PID via `ss -tlnp`, read `/proc/<pid>/cgroup` for the unit name. Works when
   the service is running.
2. **Fallback** — if the service is DOWN (no PID), fall back to the convention
   `{slug}.service`. This matches the naming pattern used by all apps registered via
   this API and all existing known-apps. Returns 404 if neither resolves.

```
POST /api/admin/services/{slug}/restart
POST /api/admin/services/restart-all
```

**`restart-all` response:**
```json
{
  "restarted": ["muxplex.service", "filebrowser.service"],
  "errors": {"dev-machine-monitor.service": "timeout after 30s"},
  "skipped": [
    {"unit": "frontdoor.service", "reason": "self — restart manually with: sudo systemctl restart frontdoor"}
  ],
  "no_unit": ["some-dev-process"]
}
```

`skipped` always contains frontdoor's own unit (from `settings.self_unit`). The
`reason` string is designed to be readable by an agent parsing the response.

`no_unit` lists services discovered via Caddy that have no associated systemd unit
(dev processes, manually-started apps).

### 3.4 Full App Registration

```
POST   /api/admin/apps
DELETE /api/admin/apps/{slug}
```

**`POST /api/admin/apps` request body:**
```json
{
  "slug": "myapp",
  "name": "My App",
  "description": "Does something cool",
  "icon": "🚀",
  "internal_port": 8450,
  "external_port": 8451,
  "exec_start": "/opt/myapp/.venv/bin/uvicorn myapp.main:app",
  "service_user": "robotdad",
  "kill_mode": "process",
  "websocket_paths": ["/ws*", "/terminal*"]
}
```

Fields:
- `slug` — required, validated `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- `internal_port`, `external_port`, `exec_start` — required
- `name` — optional, defaults to slug title-cased
- `description`, `icon` — optional, passed through to manifest
- `service_user` — optional, defaults to `settings.service_user` (new setting, see below)
- `kill_mode` — optional, `"process"` adds `KillMode=process` to the service unit;
  use for apps managing long-lived children (tmux sessions, spawned servers)
- `websocket_paths` — optional list; each entry adds a `handle` block in the Caddy
  config that routes the path directly without `forward_auth` (Caddy 2.6 limitation)

**`POST /api/admin/apps` response:**
```json
{
  "slug": "myapp",
  "caddy_config": "/etc/caddy/conf.d/myapp.caddy",
  "service_unit": "/etc/systemd/system/myapp.service",
  "manifest": "/opt/frontdoor/manifests/myapp.json",
  "internal_port": 8450,
  "external_port": 8451,
  "service_status": "active"
}
```

**`DELETE /api/admin/apps/{slug}`** — stops and disables the service, removes the
Caddy config, reloads Caddy, removes the manifest. Does not remove the app's own
installation directory (it never touched it).

**409 Conflict** — returned if slug already registered. Client must unregister first.

### 3.5 Known-App Installation

```
GET  /api/admin/known-apps
POST /api/admin/known-apps/{appname}/install
```

Known-apps live in `known-apps/<appname>/` within the frontdoor installation. The
endpoint reads `.caddy`, `.service`, and `.json` files from that directory and applies
them — substituting template variables before writing.

**`GET /api/admin/known-apps` response:**
```json
[
  {
    "name": "muxplex",
    "description": "Tmux session dashboard with WebSocket terminal",
    "files": ["muxplex.caddy", "muxplex.service", "muxplex.json"],
    "readme_url": null
  }
]
```

**`POST /api/admin/known-apps/{appname}/install` request body:**
```json
{
  "service_user": "robotdad"
}
```

Template variables substituted in `.caddy` and `.service` files:
- `{SERVICE_USER}` — from request body
- `{FQDN}` — detected from Tailscale or `hostname -f`
- `{CERT_PATH}`, `{KEY_PATH}` — detected from `/etc/ssl/tailscale/` or `/etc/ssl/self-signed/`

Response: same shape as `POST /api/admin/apps`.

### 3.6 Token Management

```
POST   /api/admin/tokens
GET    /api/admin/tokens
DELETE /api/admin/tokens/{token_id}
```

**`POST /api/admin/tokens`** — requires Tier 1 (localhost) or Tier 3 (PAM session).
Not callable via bearer token.

**Request body:**
```json
{"name": "robotdad-macbook"}
```

**Response (token shown once, never again):**
```json
{
  "id": "tok_a1b2c3d4",
  "name": "robotdad-macbook",
  "token": "ft_abc123...",
  "created_at": "2026-04-04T22:00:00Z"
}
```

**`GET /api/admin/tokens`** — lists all tokens, never returns hashes:
```json
[
  {"id": "tok_a1b2c3d4", "name": "robotdad-macbook", "created_at": "...", "last_used_at": "..."}
]
```

---

## 4. Discovery Enrichment

The `/api/services` response gains a `systemd_unit` field. This enables the service
control endpoints to resolve slug → unit, and surfaces the information in the
dashboard for future per-service controls.

**New functions in `frontdoor/discovery.py`:**

```python
def get_port_pids() -> dict[int, int]:
    """Return {internal_port: pid} for all listening TCP ports.

    Runs ss -tlnp once and parses the output. Reuses the regex already in
    scan_processes. Called once per request and shared across all lookups.
    """

def get_systemd_unit(pid: int) -> str | None:
    """Return the systemd unit name for this PID, or None.

    Reads /proc/<pid>/cgroup and extracts the service name:
      0::/system.slice/muxplex.service  →  "muxplex.service"
    Returns None for processes not running under systemd.
    """
```

**Change to `_collect_services` in `frontdoor/routes/services.py`:**

Call `get_port_pids()` once before the TCP probe loop. Inside the loop, look up the
PID for each service's `internal_port`, call `get_systemd_unit(pid)`, and include
`systemd_unit` in the service dict (before `overlay_manifests`).

**Updated `/api/services` response shape:**
```json
{
  "name": "Muxplex",
  "url": "https://ambrose.tail09557f.ts.net:8448",
  "status": "up",
  "systemd_unit": "muxplex.service"
}
```

Services without a systemd unit get `"systemd_unit": null`.

---

## 5. Privilege Escalation

`POST /api/admin/apps`, `DELETE /api/admin/apps/{slug}`, `POST /api/admin/known-apps/{appname}/install`,
and service restart operations require writing to or controlling resources owned by root:
`/etc/caddy/conf.d/`, `/etc/systemd/system/`, and systemd unit states.

### `frontdoor-priv` Helper

**Location:** `frontdoor/bin/frontdoor-priv`  
**Installed to:** `/opt/frontdoor/bin/frontdoor-priv` (or uv tool equivalent)

A small Python script (shipped with frontdoor, installed as a data file) that:

1. Reads a JSON operation payload from stdin
2. Validates `operation` is one of an explicit allowlist
3. Validates `slug` matches `^[a-z0-9][a-z0-9-]*[a-z0-9]$` (no path traversal)
4. Validates file content is a non-empty string
5. Executes the operation

**Allowed operations:**

| Operation | What it does |
|---|---|
| `write-caddy` | Writes `content` to `/etc/caddy/conf.d/{slug}.caddy` |
| `delete-caddy` | Removes `/etc/caddy/conf.d/{slug}.caddy` |
| `write-service` | Writes `content` to `/etc/systemd/system/{slug}.service` |
| `delete-service` | Removes `/etc/systemd/system/{slug}.service` |
| `systemctl` | Runs `systemctl {action} {unit}` where action ∈ {restart, enable, disable, daemon-reload} |
| `caddy-reload` | Runs `systemctl reload caddy` |

**Sudoers entry** (added by `deploy/install.sh`):

```
<SERVICE_USER> ALL=(root) NOPASSWD: /opt/frontdoor/bin/frontdoor-priv
```

One line covers all privileged operations. With uv tool migration, `<SERVICE_USER>`
becomes `robotdad` — same principle.

**Module:** `frontdoor/service_control.py`

```python
def run_privileged(operation: str, **kwargs) -> None:
    """Call frontdoor-priv via sudo with a JSON payload on stdin."""
```

**Module:** `frontdoor/app_registration.py`

Generates Caddy and systemd content from the request body and templates, then calls
`run_privileged`. Contains:

```python
def render_caddy_config(slug, fqdn, cert_path, key_path,
                        internal_port, external_port,
                        websocket_paths) -> str

def render_service_unit(slug, exec_start, service_user,
                        kill_mode, description) -> str

def register_app(req: AppRegistrationRequest) -> AppRegistrationResult
def unregister_app(slug: str) -> None
def install_known_app(appname: str, service_user: str) -> AppRegistrationResult
```

---

## 6. `frontdoor-admin` CLI

### Installation

Entry point in `pyproject.toml`:

```toml
[project.scripts]
frontdoor-admin = "frontdoor.cli:main"
```

Installed alongside frontdoor automatically. No separate install step.

**Dependency:** `click` added to `[project.dependencies]`.

### Box Config

`~/.config/frontdoor/cli.toml` — named aliases for fleet management:

```toml
[defaults]
box = "local"

[boxes.local]
url = "http://localhost:8420"
# localhost bypass — no token needed

[boxes.ambrose]
url = "https://ambrose.tail09557f.ts.net"
token = "ft_..."

[boxes.dyad]
url = "https://dyad.tail09557f.ts.net"
token = "ft_..."
```

**Resolution order** for target host:
1. `--box <name>` CLI flag
2. `--url` + `--token` CLI flags (one-off remote)
3. `FRONTDOOR_BOX`, `FRONTDOOR_URL`, `FRONTDOOR_TOKEN` env vars
4. `[defaults] box` from config file
5. `http://localhost:8420` (hardcoded fallback)

### Help System

Two tiers, always available on every command and subcommand:

- **`-h`** — traditional short-form help: usage line, brief description, flags list.
  Fits one terminal screen. For humans scanning quickly.

- **`--help`** — rich skill-format help designed for agent progressive discovery.
  Structured with consistent section headers:

```
WHAT THIS DOES      concrete description of state changes and artifacts created
WHEN TO USE         vs. alternatives (known-apps vs. app register, etc.)
REQUIRED ARGS       each with full explanation and valid values
OPTIONAL ARGS       same, with when/why to use each flag
OUTPUT              JSON shape — agents need to know what to parse
EXAMPLES            real shell patterns including agent composition (jq, $())
ERRORS              HTTP codes with plain-language meaning
SEE ALSO            related subcommands for progressive discovery
```

The top-level `--help` explains the full workflow and points agents to the right
first command (`ports next` before `app register`, `known-apps list` to check
for pre-built configs).

**Implementation:** `context_settings=dict(help_option_names=['--help'])` registers
only `--help` for rich text. `-h` is a separate `is_eager=True` callback on each
command printing a condensed summary. A shared `format_rich_help()` utility enforces
consistent section structure across all commands.

**All commands output JSON by default** — designed for agent parsing. `--human` flag
on applicable commands switches to a readable table format.

### Full Command Surface

```
frontdoor-admin [--box NAME | --url URL --token TOKEN]

Commands:
  ports
    next [--start N] [--json]           Get next free internal+external port pair
         [--show-used]                  Also print all ports frontdoor considers taken

  manifest
    list                                List installed manifests
    set SLUG --name N [--desc D] [--icon I]   Create or update manifest
    delete SLUG                         Remove manifest

  services
    list                                List services with systemd_unit column
    restart SLUG                        Restart one service by slug
    restart-all                         Restart all (warns about frontdoor exclusion)

  app
    register SLUG --internal-port N --external-port N --exec-start CMD
             [--name N] [--description D] [--icon I]
             [--service-user U] [--kill-mode process]
             [--ws-path PATH]...         Register a new app (repeatable --ws-path)
    unregister SLUG                     Remove a registered app

  known-apps
    list                                List available known-app configs
    install APPNAME [--service-user U]  Apply a known-app config

  token
    create --name NAME                  Create API token (local/PAM only)
    list                                List tokens (never shows hashes)
    revoke TOKEN_ID                     Revoke a token

  box
    add NAME --url URL [--token T]      Add a named host alias
    list                                List configured boxes
    remove NAME                         Remove a box alias
```

---

## 7. Updated Bundle Skills

### `web-app-setup`

Phase 2 (per-app provisioning) is rewritten to use `frontdoor-admin`. The LLM's job
becomes: gather the inputs, run the right command. No more LLM-generated Caddy or
systemd file content.

**New Phase 2 flow:**

```bash
# Step 1 — allocate ports (replaces manual ss scanning + /etc/app-ports.conf)
PORTS=$(frontdoor-admin ports next --json)
INTERNAL=$(echo $PORTS | jq .internal_port)
EXTERNAL=$(echo $PORTS | jq .external_port)

# Step 2a — custom app
frontdoor-admin app register myapp \
  --name "My App" \
  --internal-port $INTERNAL \
  --external-port $EXTERNAL \
  --exec-start "/opt/myapp/.venv/bin/uvicorn myapp.main:app"

# Step 2b — known app (check known-apps list first)
frontdoor-admin known-apps list
frontdoor-admin known-apps install muxplex --service-user robotdad

# Step 3 — verify
frontdoor-admin services list
```

Phase 1 (shared infra: Caddy install, certs, conf.d wiring) remains shell-based —
that work predates frontdoor being available and doesn't change.

Phase 3 (frontdoor integration) is now fully automated by `app register` — sections
3b (Caddy with forward_auth), 3c (manifest), 3d (signout pattern documentation) are
replaced by the CLI call. The `--ws-path` flag handles section 3b's WebSocket bypass.

### `host-infra-discovery`

Section 4 (port inventory) is updated:

```bash
# Old: manual ss + /etc/app-ports.conf parsing
# New:
frontdoor-admin ports next --show-used    # shows all ports frontdoor knows are taken
```

The skill still instructs a full `ss -tlnp` scan as a reality check (live sockets
vs. frontdoor's view), but the primary port allocation path moves to the CLI.

---

## 8. Files Changed

### New Files

| File | Purpose |
|---|---|
| `frontdoor/cli.py` | `frontdoor-admin` CLI entry point |
| `frontdoor/routes/admin.py` | Admin API router (all `/api/admin/*` endpoints) |
| `frontdoor/tokens.py` | Token storage, creation, validation, revocation |
| `frontdoor/service_control.py` | systemctl wrapper via `frontdoor-priv` |
| `frontdoor/app_registration.py` | Caddy/systemd template generation + file writes |
| `frontdoor/bin/frontdoor-priv` | Privileged helper (sudoers target) |

### Modified Files

| File | Change |
|---|---|
| `frontdoor/discovery.py` | Add `get_port_pids()`, `get_systemd_unit()` |
| `frontdoor/routes/services.py` | Enrich `_collect_services` with `systemd_unit` |
| `frontdoor/config.py` | Add `tokens_file`, `allow_localhost_admin`, `self_unit` |
| `frontdoor/auth.py` | Add `require_admin_auth` dependency |
| `frontdoor/main.py` | Include admin router |
| `pyproject.toml` | Add `frontdoor-admin` entry point, `click` dependency |
| `deploy/install.sh` | Add sudoers entry for `frontdoor-priv` |
| `skills/web-app-setup.md` | Rewrite Phase 2 + Phase 3 to use `frontdoor-admin` |
| `skills/host-infra-discovery.md` | Update port inventory section |

---

## 9. Testing

Each new module gets a corresponding test file following the existing `frontdoor/tests/`
structure:

| Test file | Covers |
|---|---|
| `tests/test_tokens.py` | Token creation, hashing, validation, revocation, file I/O |
| `tests/test_admin_routes.py` | All `/api/admin/*` endpoints with mocked filesystem + subprocess |
| `tests/test_service_control.py` | `run_privileged` with mocked subprocess |
| `tests/test_app_registration.py` | Caddy/systemd template rendering, slug validation |
| `tests/test_discovery_enrichment.py` | `get_port_pids()`, `get_systemd_unit()` with mocked `/proc` |
| `tests/test_cli.py` | CLI commands using Click's `CliRunner` |

Existing tests must continue to pass unchanged. The new `systemd_unit` field in
`/api/services` is additive — existing test fixtures need the field added as `null`.

---

## 10. Incremental Delivery Order

The features compose but can be delivered independently. Suggested order:

1. **Discovery enrichment** — `systemd_unit` in `/api/services` (no privilege needed,
   pure read path, immediately useful)
2. **Auth model + tokens** — `require_admin_auth`, `tokens.py`, token endpoints
3. **Service control** — restart endpoints + `frontdoor-priv` sudoers setup
4. **Port allocation + manifests** — low-privilege admin endpoints
5. **Full app registration** — `app_registration.py`, write-caddy/write-service ops
6. **Known-app install** — template substitution + known-apps endpoint
7. **`frontdoor-admin` CLI** — wraps everything above
8. **Bundle skill updates** — web-app-setup + host-infra-discovery rewrites
