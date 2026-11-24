#!/usr/bin/env bash
# Installs (or updates) the HTPC controller service for the current user.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="$HOME/.local/share/htpc-launcher"
CONFIG="$HOME/.config/htpc-launcher"
UNITS="$HOME/.config/systemd/user"

if ! python3 -c 'import evdev, jeepney' 2>/dev/null; then
    echo "Installing python3-evdev and python3-jeepney (asks for the sudo password)..."
    sudo apt install -y python3-evdev python3-jeepney
fi

mkdir -p "$DATA" "$CONFIG" "$UNITS"
cp "$HERE/controller.py" "$HERE/../common/htpc_config.py" "$DATA/"

if [ -f "$CONFIG/apps.json" ]; then
    echo "Kept the existing $CONFIG/apps.json."
else
    cp "$HERE/../config/apps.json" "$CONFIG/"
    echo "Created $CONFIG/apps.json"
fi

# Older versions installed the service as htpc-controle.
if [ -f "$UNITS/htpc-controle.service" ]; then
    systemctl --user disable --now htpc-controle.service 2>/dev/null || true
    rm -f "$UNITS/htpc-controle.service" "$DATA/controle.py"
    echo "Removed the old htpc-controle service."
fi

cp "$HERE/htpc-controller.service" "$UNITS/"
systemctl --user daemon-reload
systemctl --user enable htpc-controller.service
systemctl --user restart htpc-controller.service

echo
echo "Service running. To follow what it does:"
echo "  journalctl --user -fu htpc-controller"
