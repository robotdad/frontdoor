# Muxplex — frontdoor Integration

[muxplex](https://github.com/bkrabach/muxplex) is a web-based tmux session dashboard with
an interactive terminal. It is not our repo — these files capture everything needed to run
it cleanly behind frontdoor without modifying muxplex itself.

---

## Prerequisites

```bash
# tmux — session management
sudo apt install tmux          # Ubuntu/Debian
brew install tmux              # macOS

# ttyd — required for the interactive terminal tab
sudo apt install ttyd          # Ubuntu/Debian
brew install ttyd              # macOS
```

---

## Install

```bash
uv tool install git+https://github.com/bkrabach/muxplex
```

Binary lands at `~/.local/bin/muxplex`. muxplex defaults to `127.0.0.1:8088` with no
flags required.

---

## How Auth Works (No Double Login)

muxplex has its own auth system, but it includes a **localhost bypass**: any request
arriving from `127.0.0.1` skips auth entirely. When Caddy proxies requests from the same
machine to `localhost:8088`, the connection arrives at muxplex from `127.0.0.1`, so the
bypass fires and muxplex never prompts for credentials.

frontdoor's `forward_auth` handles the actual login — users authenticate once and muxplex
is transparent.

---

## Critical: `header_up -X-Forwarded-For`

Caddy adds an `X-Forwarded-For: <original client IP>` header when proxying. Uvicorn (which
muxplex runs on) trusts this header from localhost connections and replaces
`request.client.host` with the original client's IP (e.g. a Tailscale address). muxplex's
localhost bypass checks `request.client.host` — if it sees a Tailscale IP instead of
`127.0.0.1`, it redirects to its own login page.

Fix: add `header_up -X-Forwarded-For` to every `reverse_proxy` block pointing at muxplex.
This strips the header before it reaches uvicorn, so `request.client.host` stays `127.0.0.1`.

---

## WebSocket Bypass

The terminal uses a WebSocket at `/terminal/ws`. Caddy 2.6 cannot proxy WebSocket
connections to the backend after `forward_auth` validation (a known Caddy 2.6 limitation).
The Caddy config routes `/terminal*` directly to muxplex, bypassing `forward_auth`.
muxplex's localhost bypass handles auth for that path instead.

---

## Deployment

**1. Allocate a port** (8448 if free):

```bash
ss -tlnp | grep 8448   # confirm free
```

**2. Write the Caddy config** — substitute `MUXPLEX_FQDN`, `MUXPLEX_PORT`, `CERT_PATH`,
`KEY_PATH`, and `FRONTDOOR_PORT` in `muxplex.caddy`, then:

```bash
sudo cp muxplex.caddy /etc/caddy/conf.d/muxplex.caddy
sudo systemctl reload caddy
```

**3. Write the systemd service** — substitute `SERVICE_USER` in `muxplex.service`, then:

```bash
sudo cp muxplex.service /etc/systemd/system/muxplex.service
sudo systemctl daemon-reload
sudo systemctl enable --now muxplex
```

**4. Install the frontdoor manifest:**

```bash
sudo cp muxplex.json /opt/frontdoor/manifests/muxplex.json
```

The frontdoor dashboard will display muxplex with its logo (served from
`/muxplex-icon.png` in frontdoor's static directory).

---

## Verify

```bash
systemctl status muxplex
curl -sf https://MUXPLEX_FQDN:MUXPLEX_PORT/ -o /dev/null -w "%{http_code}\n"
# Expected: 200 (if frontdoor session cookie is present) or 302 to frontdoor /login
```
