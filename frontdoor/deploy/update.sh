#!/bin/bash
set -euo pipefail

echo "=== Frontdoor Update ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="/opt/frontdoor"

if [ ! -d "$INSTALL_DIR/.venv" ]; then
    echo "ERROR: $INSTALL_DIR not found. Run deploy/install.sh first."
    exit 1
fi

echo "Syncing code to $INSTALL_DIR..."
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
    "$PROJECT_DIR/" "$INSTALL_DIR/"

echo "Reinstalling package..."
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade "$INSTALL_DIR"

echo "Restarting service..."
systemctl restart frontdoor
systemctl status frontdoor --no-pager -l

echo ""
echo "=== Update complete ==="
