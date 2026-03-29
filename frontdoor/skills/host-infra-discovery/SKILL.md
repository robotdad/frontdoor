---
name: host-infra-discovery
description: Use when setting up a new web app on a Linux or macOS host, or when asked what's already running on monad, dyad, or any host — before writing Caddy configs, allocating ports, or creating systemd/launchd services. Determines what shared infra exists to reuse vs. what to install fresh.
---

# Host Infrastructure Discovery

## Overview

Before touching a host, inventory it. Running this prevents overwriting existing Caddy configs, allocating duplicate ports, installing duplicate cert timers, and repeating shadow group setup that's already done.

Prefix every command with `ssh <hostname>` when running against a remote host.

---

## 0. Platform and Network Overlay Detection (Run First)

These two checks gate everything below.

### Platform

```bash
uname -s   # "Linux" or "Darwin"
```

Commands vary in several checks below — macOS variants are marked `# macOS`.

### Network overlay

```bash
# Is Tailscale present?
tailscale status 2>/dev/null && echo "TAILSCALE_PRESENT" || echo "TAILSCALE_ABSENT"

# Any other overlay indicators?
# Linux:
ip link show type wireguard 2>/dev/null | grep -q 'wg' && echo "WIREGUARD_DETECTED" || true
ip link 2>/dev/null | grep -qE '^[0-9]+: zt' && echo "ZEROTIER_DETECTED" || true
# macOS:
ifconfig 2>/dev/null | grep -E '^utun[2-9]' | head -3
# Either platform:
which cloudflared 2>/dev/null && echo "CLOUDFLARE_TUNNEL_DETECTED" || true
```

| Result | What it means for the rest of this skill |
|--------|------------------------------------------|
| `TAILSCALE_PRESENT` | Full skill applies — all checks below are relevant |
| WireGuard / ZeroTier / utun detected | Network isolation present but outside scope — skip cert and identity sections; see Non-Tailscale Notes |
| `CLOUDFLARE_TUNNEL_DETECTED` | Cloudflare handles TLS and outer auth — skip cert sections; see Non-Tailscale Notes |
| Nothing detected | No overlay — cert and auth are fully your responsibility; see Non-Tailscale Notes |

---

## Checklist: Run These, Then Interpret

*Skip sections flagged as Tailscale-only if overlay detection showed something else.*

### 1. FQDN and TLS certs

```bash
# Detect FQDN — Tailscale if present, system hostname otherwise
command -v tailscale > /dev/null 2>&1 \
    && tailscale status --json | python3 -c \
        "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" \
    || { hostname -f; echo "TAILSCALE_NOT_INSTALLED"; }

# Tailscale-managed certs
ls /etc/ssl/tailscale/ 2>/dev/null || echo "NO_TAILSCALE_CERTS"

# Self-signed certs
ls /etc/ssl/self-signed/ 2>/dev/null || echo "NO_SELF_SIGNED_CERTS"
```

| Result | Meaning |
|--------|---------|
| Tailscale FQDN printed (e.g. `host.ts.net`) | Use as Caddy vhost name; cert type = **tailscale** |
| `TAILSCALE_NOT_INSTALLED` + `hostname -f` output | No Tailscale; use system FQDN; cert type = self-signed or none |
| Tailscale certs present (`.crt` + `.key` in `/etc/ssl/tailscale/`) | Skip cert generation; cert type = **tailscale** |
| Self-signed certs present (files in `/etc/ssl/self-signed/`) | Skip cert generation; cert type = **self-signed** |
| Neither cert dir has files | Need `tailscale cert` (if Tailscale) or generate self-signed; cert type = **none** |

### 2. Cert renewal timer *(Tailscale only)*

*Skip this section entirely if cert type is **self-signed** or **none** — self-signed certs carry 10-year validity and do not require a renewal timer.*

```bash
# Linux
systemctl is-enabled tailscale-cert-renew.timer 2>/dev/null || echo "NOT_INSTALLED"
# macOS
launchctl list 2>/dev/null | grep -q tailscale-cert-renew && echo "enabled" || echo "NOT_INSTALLED"
```

`enabled` → skip. `NOT_INSTALLED` → install it now (web-app-setup handles this).

### 3. Caddy — installed, running, conf.d wired

```bash
caddy version 2>/dev/null || echo "NOT_INSTALLED"
# Linux
systemctl is-active caddy 2>/dev/null || echo "NOT_RUNNING"
# macOS
brew services list 2>/dev/null | grep caddy || echo "NOT_RUNNING"

grep -c 'import.*conf.d' /etc/caddy/Caddyfile 2>/dev/null || echo "0"
ls /etc/caddy/conf.d/ 2>/dev/null || echo "NO_CONFD"
```

| Result | Action |
|--------|--------|
| `NOT_INSTALLED` | `apt-get install -y caddy` (Linux) or `brew install caddy` (macOS) |
| `NOT_RUNNING` | `systemctl enable --now caddy` (Linux) or `brew services start caddy` (macOS) |
| grep returns `0` | Append `import /etc/caddy/conf.d/*.caddy` to Caddyfile |
| `NO_CONFD` | `mkdir -p /etc/caddy/conf.d` |

### 4. Port inventory — what's already allocated

```bash
cat /etc/app-ports.conf 2>/dev/null || echo "NO_REGISTRY"
# Linux
ss -tlnp | awk '/127\.0\.0\.1/{print $4, $6}' | sort
# macOS
netstat -an | awk '/tcp.*127\.0\.0\.1.*LISTEN/{print $4}' | sort
```

Read the registry for intent; the socket scan for reality. Any port in the output is taken. amplifierd is always `8410` — never reassign it.

### 5. Existing app services

```bash
# Linux
systemctl list-units --type=service --state=active --no-legend \
    | grep -E 'filebrowser|amplifierd|amp-|amplifier'
# macOS
launchctl list 2>/dev/null | grep -E 'filebrowser|amplifierd|amplifier'
```

Each running service already has a Caddy snippet — don't duplicate its vhost entry.

### 6. PAM / shadow group *(Linux + Tailscale auth only)*

```bash
# Linux only — not applicable on macOS
getent group shadow
```

If the app's service user already appears, skip `usermod`. On macOS this check does not apply — auth uses Tailscale identity (see web-app-setup).

---

## Interpreting the Readout

Build this table from the checks before writing any config:

| Component | Found | Action |
|-----------|-------|--------|
| Tailscale FQDN | `hostname.ts.net` | Use as vhost name |
| FQDN (no Tailscale) | `hostname -f` output | Use as vhost name; cert type = self-signed or none |
| Cert type | tailscale / self-signed / none | Determines cert commands and renewal timer |
| TLS certs | tailscale present / self-signed present / absent | Skip / skip / provision |
| Cert renewal timer | enabled / not installed / n/a (self-signed or none) | Skip / install / skip |
| Caddy | running + conf.d wired / partial / absent | Drop snippet / fix gaps / full install |
| Open port (8444+) | e.g. `8445` not in socket scan | Use in snippet + registry |
| Shadow group (Linux) | user present / absent | Skip / `usermod -aG shadow` |

---

## What Never Gets Shared (Quick Reference)

| Thing | Rule |
|-------|------|
| Signing keys | Per-app at `/opt/<appname>/.secret_key` (Linux) or `~/.config/<appname>/secret_key` (macOS) |
| Cookie names | Must be unique: `<appname>_session` — browsers don't scope by port |
| Cert renewal timer | One per host |
| Caddyfile | Never overwrite — always use `conf.d/` snippets |
| Shadow group (Linux) | One `usermod` per user, covers all apps |

---

## Non-Tailscale Notes

This skill fully specifies the Tailscale path. If overlay detection showed something else, here are things to consider — not instructions, as these paths haven't been validated:

**Other mesh VPNs (WireGuard, ZeroTier):** You have network isolation but no built-in cert provisioning or identity API. You'll need to source TLS certs separately — Caddy's automatic ACME works if you have a real domain pointed at the host; `mkcert` is an option for LAN-only without a domain. Auth falls to the app layer; the forward_auth SSO approach in the guidance doc applies here.

**Cloudflare Tunnel (`cloudflared`):** Cloudflare terminates TLS at their edge — skip the cert and renewal sections. Cloudflare Access can handle outer auth and passes identity in a request header (`Cf-Access-Authenticated-User-Email`). Caddy still useful for local routing but needs no `tls` directive.

**No overlay (LAN or public):** Caddy's built-in ACME handles Let's Encrypt automatically if you have a domain (`tls your@email.com` in the site block). For LAN-only without a domain, `mkcert` generates locally-trusted certs. Auth carries full weight — the cookie/session model still applies but you need a real password mechanism since there's no network-layer trust.
