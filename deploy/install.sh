#!/bin/bash
set -euo pipefail

echo "=== Frontdoor Installer ==="

# --- Detect environment ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# When run via sudo, whoami returns root. Use SUDO_USER to get the real user.
USER="${SUDO_USER:-$(whoami)}"
INSTALL_DIR="/opt/frontdoor"
FILEBROWSER_NEW_PORT=8447
HTTPS=false

# --- Detect FQDN (Tailscale preferred, hostname -f fallback) ---
echo "Detecting FQDN..."
FQDN=""

# Try Tailscale first
if command -v tailscale &>/dev/null; then
    FQDN=$(tailscale status --json 2>/dev/null \
        | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['Self']['DNSName'].rstrip('.'))" \
        2>/dev/null) || true
fi

# Fall back to hostname -f if Tailscale didn't provide an FQDN
if [ -z "$FQDN" ]; then
    FQDN=$(hostname -f 2>/dev/null) || true
fi

echo "  FQDN: $FQDN"

SHORT_HOSTNAME=$(hostname -s)
echo "  Short hostname: $SHORT_HOSTNAME"

# Validate FQDN and SHORT_HOSTNAME before use in config generation
if [ -z "$FQDN" ] || [[ "$FQDN" =~ [^a-zA-Z0-9.\-] ]]; then
    echo "ERROR: Invalid or empty FQDN detected: '$FQDN'" >&2
    exit 1
fi
if [ -z "$SHORT_HOSTNAME" ] || [[ "$SHORT_HOSTNAME" =~ [^a-zA-Z0-9\-] ]]; then
    echo "ERROR: Invalid or empty SHORT_HOSTNAME detected: '$SHORT_HOSTNAME'" >&2
    exit 1
fi

# --- Generate secret key (idempotent: read from frontdoor.env if exists) ---
echo "Setting up secret key..."
ENV_FILE="$INSTALL_DIR/frontdoor.env"
if [ -f "$ENV_FILE" ]; then
    SECRET_KEY=$(grep '^FRONTDOOR_SECRET_KEY=' "$ENV_FILE" | cut -d= -f2-)
    echo "  Using existing secret key"
else
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "  Generated new secret key"
fi

# --- Ensure PAM access ---
echo "Ensuring PAM access (shadow group)..."
if ! groups "$USER" | grep -q '\bshadow\b'; then
    usermod -aG shadow "$USER"
    echo "  Added $USER to shadow group"
else
    echo "  $USER already in shadow group"
fi

# --- Install application ---
echo "Installing application to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
chown "$USER:$USER" "$INSTALL_DIR"
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='.git' "$PROJECT_DIR/" "$INSTALL_DIR/"

# --- Create venv and install ---
echo "Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet "$INSTALL_DIR"

# --- Install Caddy ---
# Install before the Tailscale cert section: the cert key requires root:caddy
# ownership, and the 'caddy' group only exists after Caddy is installed.
if ! command -v caddy &>/dev/null; then
    echo "Installing Caddy..."
    apt-get update -qq && apt-get install -y -qq caddy
else
    echo "Caddy already installed"
fi

# --- Three-tier TLS provisioning ---
# Tier 1: Tailscale cert (requires paid plan)
# Tier 2: Self-signed cert (HTTPS with browser warning)
# Tier 3: HTTP fallback (Tailscale encrypts in transit)
echo "Attempting TLS certificate provisioning..."
CERT_DIR="/etc/ssl/tailscale"
CERT_PATH="$CERT_DIR/$FQDN.crt"
KEY_PATH="$CERT_DIR/$FQDN.key"
mkdir -p "$CERT_DIR"
if command -v tailscale &>/dev/null && tailscale cert --cert-file "$CERT_PATH" --key-file "$KEY_PATH" "$FQDN" 2>/dev/null; then
    echo "  Tier 1: Tailscale certificate obtained (HTTPS enabled)"
    chown root:caddy "$KEY_PATH"
    chmod 640 "$KEY_PATH"
    HTTPS=true
else
    CERT_DIR="/etc/ssl/self-signed"
    CERT_PATH="/etc/ssl/self-signed/$FQDN.crt"
    KEY_PATH="/etc/ssl/self-signed/$FQDN.key"
    mkdir -p "$CERT_DIR"
    if openssl req -x509 -newkey rsa:2048 -days 3650 -nodes -subj "/CN=$FQDN" \
        -keyout "$KEY_PATH" -out "$CERT_PATH" 2>/dev/null; then
        echo "  Tier 2: Self-signed certificate generated (HTTPS enabled)"
        chown root:caddy "$KEY_PATH"
        chmod 640 "$KEY_PATH"
        HTTPS=true
    else
        echo "  Tier 3: TLS unavailable -- falling back to HTTP"
        echo "  Note: Tailscale encrypts traffic between devices, so HTTP is safe on your tailnet"
    fi
fi

# --- Create conf.d directory ---
echo "Creating Caddy conf.d directory..."
mkdir -p /etc/caddy/conf.d

# --- Create manifests directory ---
echo "Creating manifests directory..."
mkdir -p /opt/frontdoor/manifests
chown "$USER:$USER" /opt/frontdoor/manifests

# --- One-time Caddy migration: move filebrowser from main Caddyfile to conf.d/ ---
echo "Checking for filebrowser Caddy migration..."
if [ -f /etc/caddy/Caddyfile ] && grep -q 'reverse_proxy localhost:58080' /etc/caddy/Caddyfile; then
    echo "  Migrating filebrowser from main Caddyfile to conf.d/filebrowser.caddy..."
    if [ "$HTTPS" = true ]; then
        cat > /etc/caddy/conf.d/filebrowser.caddy <<EOF
$FQDN:$FILEBROWSER_NEW_PORT {
    tls $CERT_PATH $KEY_PATH

    forward_auth localhost:8420 {
        uri /api/auth/validate
        copy_headers X-Authenticated-User
    }

    reverse_proxy localhost:58080
}
EOF
    else
        cat > /etc/caddy/conf.d/filebrowser.caddy <<EOF
http://$FQDN:$FILEBROWSER_NEW_PORT {
    forward_auth localhost:8420 {
        uri /api/auth/validate
        copy_headers X-Authenticated-User
    }

    reverse_proxy localhost:58080
}
EOF
    fi
    echo "  Filebrowser migrated to /etc/caddy/conf.d/filebrowser.caddy on port $FILEBROWSER_NEW_PORT"
else
    echo "  No filebrowser migration needed"
fi

# --- Write main Caddyfile ---
echo "Writing Caddy configuration..."
if [ "$HTTPS" = true ]; then
    cat > /etc/caddy/Caddyfile <<EOF
# Frontdoor — main entry point on port 443
$FQDN:443 {
    tls $CERT_PATH $KEY_PATH

    reverse_proxy localhost:8420
}

# Short hostname redirect: http://SHORT_HOSTNAME -> https://FQDN (301 Moved Permanently)
http://$SHORT_HOSTNAME {
    redir https://$FQDN{uri} 301
}

# Import per-service snippets
import /etc/caddy/conf.d/*.caddy
EOF
else
    cat > /etc/caddy/Caddyfile <<EOF
# Frontdoor — main entry point (HTTP mode, Tailscale encrypts in transit)
http://$FQDN {
    reverse_proxy localhost:8420
}

# Short hostname redirect: http://SHORT_HOSTNAME -> http://FQDN (301 Moved Permanently)
http://$SHORT_HOSTNAME {
    redir http://$FQDN{uri} 301
}

# Import per-service snippets
import /etc/caddy/conf.d/*.caddy
EOF
fi

# --- Write environment file ---
echo "Writing environment file..."
(umask 177; cat > "$ENV_FILE" <<EOF
FRONTDOOR_SECRET_KEY=$SECRET_KEY
FRONTDOOR_SECURE_COOKIES=$HTTPS
FRONTDOOR_COOKIE_DOMAIN=$FQDN
EOF
)

# --- Write systemd unit ---
echo "Installing systemd unit..."
# Values are delivered via EnvironmentFile=/opt/frontdoor/frontdoor.env — not injected inline.
# Unit file is created atomically with restrictive permissions (umask 177 = mode 0600).
(umask 177; sed \
    -e "s|FRONTDOOR_USER|$USER|g" \
    -e "s|FRONTDOOR_DIR|$INSTALL_DIR|g" \
    "$INSTALL_DIR/deploy/frontdoor.service" \
    > /etc/systemd/system/frontdoor.service)

# --- Enable and start services ---
echo "Starting services..."
systemctl daemon-reload
systemctl enable frontdoor
systemctl restart frontdoor
systemctl enable caddy
systemctl restart caddy

echo ""
echo "=== Installation complete ==="
if [ "$HTTPS" = true ]; then
    echo "Frontdoor is running at: https://$FQDN"
else
    echo "Frontdoor is running at: http://$FQDN"
    echo "(or http://$SHORT_HOSTNAME/)"
fi
echo ""
echo "To check status:"
echo "  systemctl status frontdoor"
echo "  systemctl status caddy"
