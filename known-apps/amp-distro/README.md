# amp-distro — frontdoor Integration

[amp-distro](https://github.com/microsoft/amplifier-distro) is the Amplifier Experience
Server — web chat, Slack bridge, voice, and the Amplifier CLI web interface. It bundles
`amplifierd` as a standalone service.

---

## Prerequisites

`amp-distro` is installed via uv:

```bash
uv tool install git+https://github.com/microsoft/amplifier-distro
```

Binary lands at `~/.local/share/uv/tools/amp-distro/bin/amp-distro`.

---

## Integration Quirks

### uv must be on the service PATH

`amplifierd` calls `uv` at startup to install bundle dependencies. systemd runs with a
stripped PATH that does not include `~/.local/bin`. Without a PATH fix, the service starts
but throws `FileNotFoundError: 'uv'` during bundle prewarm.

Fix: use a systemd drop-in that extends PATH (see Deployment below).

### External and internal ports must differ

Caddy binds the external port on all interfaces (`:EXTERNAL_PORT`). amp-distro binds its
internal port on loopback only (`127.0.0.1:INTERNAL_PORT`). If both ports are the same,
Caddy's bind fails with `address already in use`.

Always allocate two separate ports — one for Caddy's vhost, one for the app. Check all
three sources before choosing:

```bash
cat /etc/app-ports.conf
ss -tlnp | awk '/127\.0\.0\.1/{print $4}' | sort
grep -r 'ts.net:' /etc/caddy/conf.d/
```

### `serve` subcommand removed (v0.3.0+)

`amp-distro serve` no longer exists. Use `amp-distro --host 127.0.0.1 --port INTERNAL_PORT
--tls off` directly. Behind frontdoor, `--tls off` is correct — Caddy terminates TLS.

### `AMPLIFIERD_TRUST_PROXY_AUTH`

Set `AMPLIFIERD_TRUST_PROXY_AUTH=true` so `amplifierd` trusts the `X-Authenticated-User`
header injected by Caddy's `copy_headers` directive instead of running its own PAM auth.
Without this, users see a second login prompt from amplifierd behind frontdoor's session.

---

## Deployment

**1. Choose ports** — check all three sources above, then pick:

- `INTERNAL_PORT`: what amp-distro listens on
- `EXTERNAL_PORT`: what Caddy listens on — must be different from `INTERNAL_PORT`

**2. Write the Caddy config** — substitute all placeholders in `amp-distro.caddy`, then:

```bash
sudo cp amp-distro.caddy /etc/caddy/conf.d/amp-distro.caddy
sudo systemctl reload caddy
```

**3. Write the systemd service** — substitute `SERVICE_USER` and `INTERNAL_PORT` in
`amp-distro.service`, then install with a drop-in for PATH and proxy auth:

```bash
sudo cp amp-distro.service /etc/systemd/system/amp-distro.service
sudo mkdir -p /etc/systemd/system/amp-distro.service.d
sudo tee /etc/systemd/system/amp-distro.service.d/frontdoor-trust.conf << EOF
[Service]
Environment=PATH=/home/SERVICE_USER/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=AMPLIFIERD_TRUST_PROXY_AUTH=true
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now amp-distro
```

**4. Install the frontdoor manifest:**

```bash
sudo cp amp-distro.json /opt/frontdoor/manifests/amp-distro.json
```

**5. Register ports** in `/etc/app-ports.conf`:

```ini
[amp-distro]
internal=INTERNAL_PORT
external=EXTERNAL_PORT
```

---

## Verify

```bash
systemctl status amp-distro
journalctl -u amp-distro -n 20   # look for "Application startup complete" and providers loading
curl -sf https://FQDN:EXTERNAL_PORT/ -o /dev/null -w "%{http_code}\n"
# Expected: 401 — frontdoor rejects unauthenticated curl, confirming the full chain works
```
