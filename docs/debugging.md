# Debugging Frontdoor

## Backend Logging

Logging is configured in `frontdoor/main.py` using `logging.basicConfig()` with `force=True` (overrides any existing root logger config). The log level is controlled by an environment variable:

- **Env var**: `FRONTDOOR_LOG_LEVEL`
- **Default**: `info`
- **Options**: `debug`, `info`, `warning`, `error`

To change it: edit the env file at the deployed location and restart the service (`sudo systemctl restart frontdoor`).

**Log format**:
```
%(asctime)s %(levelname)s %(name)s: %(message)s
```
Example output: `2025-03-15 14:22:01,234 INFO frontdoor.auth: Login success user=alice client=192.168.1.5`

**Where logs go**: stderr, which systemd captures into the journal.

**Viewing logs**:
```bash
# Live tail
journalctl -u frontdoor -f

# Recent logs
journalctl -u frontdoor --since "10 min ago"
```

**Third-party noise**: The `python_multipart` logger is pinned to INFO even when frontdoor runs at DEBUG, so form-parsing internals don't flood the output.

### Log Level Guide

- **DEBUG**: Auth flow tracing (session cookie checks, token validation, PAM success), service discovery detail (Caddy parse decisions, skipped blocks, TCP probe counts, process scan counts, manifest loading). High-frequency, suppressed at INFO.
- **INFO**: Login success (with user + client IP), logout (with user + client IP), service discovery summary (N configured, M unregistered), Caddy config parse count, app startup.
- **WARNING**: Security events — login failures, bad session signatures (possible tampering), auth rejections (invalid tokens, no cookies). Operational warnings — subprocess failures in process scanning (ss command errors). These always appear at INFO level and above.
- **EXCEPTION**: Unhandled exceptions with full tracebacks via the global exception handler in `main.py`. These log at ERROR level with a stack trace for any request that hits an uncaught exception.

### What Gets Logged Where

| Module | What it covers |
|---|---|
| `frontdoor.auth` | PAM auth results, token validation (expired vs tampered), `require_auth` decisions |
| `frontdoor.routes.auth` | Login success/failure, logout, WebSocket validation |
| `frontdoor.routes.services` | Service list requests, discovery pipeline phases |
| `frontdoor.discovery` | Caddy config parsing, manifest overlays, process scanning |

## Frontend

Frontdoor's frontend is a lightweight inline Preact app with no external JS modules. There's no client-side logging infrastructure. Errors surface as UI banners or redirects.

For frontend debugging, use browser DevTools — the Network tab to inspect API calls (`/api/auth/validate`, `/api/services`, `/api/auth/login`, `/api/auth/logout`) and their responses.

## Useful Commands

```bash
# Live tail backend logs
journalctl -u frontdoor -f

# Recent logs
journalctl -u frontdoor --since "10 min ago"

# Filter by level
journalctl -u frontdoor | grep WARNING

# Filter by module
journalctl -u frontdoor | grep frontdoor.auth

# Auth events only
journalctl -u frontdoor | grep -E "(Login|Logout|Auth rejected|PAM auth)"

# Service discovery
journalctl -u frontdoor | grep -E "(Services|Parsed|TCP probes|Process scan)"
```
