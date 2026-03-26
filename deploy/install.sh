#!/bin/bash
set -euo pipefail

echo "=== Frontdoor Installer ==="

# --- Detect environment ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# When run via sudo, whoami returns root. Use SUDO_USER to get the real user.
USER="${SUDO_USER:-$(whoami)}"
INSTALL_DIR="/opt/frontdoor"
CERT_DIR="/etc/ssl/tailscale"
FILEBROWSER_NEW_PORT=8447
HTTPS=false

# --- Detect Tailscale FQDN ---
echo "Detecting Tailscale FQDN..."
FQDN=$(tailscale status --json | python3 -c "import sys, json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))")
echo "  FQDN: $FQDN"

SHORT_HOSTNAME=$(hostname -s)
echo "  Short hostname: $SHORT_HOSTNAME"

CERT_PATH="$CERT_DIR/$FQDN.crt"
KEY_PATH="$CERT_DIR/$FQDN.key"

# --- Generate secret key (idempotent: read from file if exists) ---
echo "Setting up secret key..."
SECRET_FILE="$INSTALL_DIR/.secret_key"
if [ -f "$SECRET_FILE" ]; then
    SECRET_KEY=$(cat "$SECRET_FILE")
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

# Save secret key
mkdir -p "$INSTALL_DIR"
echo "$SECRET_KEY" > "$SECRET_FILE"
chmod 600 "$SECRET_FILE"

# --- Create venv and install ---
echo "Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet "$INSTALL_DIR"

# --- Try to generate Tailscale cert (requires paid plan) ---
echo "Attempting Tailscale certificate generation..."
mkdir -p "$CERT_DIR"
if tailscale cert --cert-file "$CERT_PATH" --key-file "$KEY_PATH" "$FQDN" 2>/dev/null; then
    echo "  Certificate generated (HTTPS enabled)"
    chown root:caddy "$KEY_PATH"
    chmod 640 "$KEY_PATH"
    HTTPS=true
else
    echo "  Certificate unavailable (free Tailscale plan) -- using HTTP"
    echo "  Note: Tailscale encrypts traffic between devices, so HTTP is safe on your tailnet"
fi

# --- Install Caddy ---
if ! command -v caddy &>/dev/null; then
    echo "Installing Caddy..."
    apt-get update -qq && apt-get install -y -qq caddy
else
    echo "Caddy already installed"
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
        uri /auth/verify
        copy_headers Remote-User Remote-Groups Remote-Name Remote-Email
    }

    reverse_proxy localhost:58080
}
EOF
    else
        cat > /etc/caddy/conf.d/filebrowser.caddy <<EOF
http://$FQDN:$FILEBROWSER_NEW_PORT {
    forward_auth localhost:8420 {
        uri /auth/verify
        copy_headers Remote-User Remote-Groups Remote-Name Remote-Email
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

# Short hostname redirect: http://SHORT_HOSTNAME -> https://FQDN
http://$SHORT_HOSTNAME {
    redir https://$FQDN{uri} permanent
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

# Short hostname redirect: http://SHORT_HOSTNAME -> http://FQDN
http://$SHORT_HOSTNAME {
    redir http://$FQDN{uri} permanent
}

# Import per-service snippets
import /etc/caddy/conf.d/*.caddy
EOF
fi

# --- Write systemd unit ---
echo "Installing systemd unit..."
sed \
    -e "s|FRONTDOOR_USER|$USER|g" \
    -e "s|FRONTDOOR_DIR|$INSTALL_DIR|g" \
    -e "s|FRONTDOOR_SECRET|$SECRET_KEY|g" \
    -e "s|FRONTDOOR_HTTPS_ENABLED|$HTTPS|g" \
    -e "s|FRONTDOOR_FQDN|$FQDN|g" \
    "$INSTALL_DIR/deploy/frontdoor.service" \
    > /etc/systemd/system/frontdoor.service
chmod 600 /etc/systemd/system/frontdoor.service

# --- Enable and start services ---
echo "Starting services..."
systemctl daemon-reload
systemctl enable frontdoor
systemctl restart frontdoor
systemctl enable caddy
systemctl reload caddy

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
