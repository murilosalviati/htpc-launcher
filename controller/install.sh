#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
# Installs (or updates) the HTPC controller service for the current user.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="$HOME/.local/share/htpc-launcher"
CONFIG="$HOME/.config/htpc-launcher"
UNITS="$HOME/.config/systemd/user"

# Never leave the installed copy missing or half-written (a failure or a power
# cut mid-install would leave the TV without launcher and without the gamepad
# service, and nothing on screen to fix it): copy next to it, then rename over.
# The previous version stays as <name>.old.
put_dir() {   # put_dir SRC DEST
    rm -rf "$2.new"
    cp -r "$1" "$2.new"
    find "$2.new" -name __pycache__ -prune -exec rm -rf {} +
    if [ -e "$2" ]; then
        rm -rf "$2.old"
        mv "$2" "$2.old"
    fi
    mv "$2.new" "$2"
}
put_file() {  # put_file SRC DESTDIR
    cp "$1" "$2/.$(basename "$1").new"
    mv -f "$2/.$(basename "$1").new" "$2/$(basename "$1")"
}

if ! python3 -c 'import evdev, jeepney' 2>/dev/null; then
    echo "Installing python3-evdev and python3-jeepney (asks for the sudo password)..."
    sudo apt install -y python3-evdev python3-jeepney
fi

mkdir -p "$DATA" "$CONFIG" "$UNITS"
put_dir "$HERE/../htpc" "$DATA/htpc"
put_file "$HERE/controller.py" "$DATA"
rm -f "$DATA/htpc_config.py"

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

put_file "$HERE/htpc-controller.service" "$UNITS"
systemctl --user daemon-reload
systemctl --user enable htpc-controller.service
systemctl --user restart htpc-controller.service

echo
echo "Service running. To follow what it does:"
echo "  journalctl --user -fu htpc-controller"
