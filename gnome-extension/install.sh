#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
# Installs (or updates) the HTPC Launcher Bridge extension for the current user.
set -euo pipefail

UUID="htpc-launcher@htpc"
SRC="$(cd "$(dirname "$0")" && pwd)/$UUID"
DEST="$HOME/.local/share/gnome-shell/extensions/$UUID"

mkdir -p "$DEST"
cp "$SRC/metadata.json" "$SRC/extension.js" "$DEST/"
echo "Files copied to $DEST"

if gnome-extensions info "$UUID" >/dev/null 2>&1; then
    gnome-extensions enable "$UUID"
    echo "Extension enabled."
    echo "If this was an update with code changes: log out and back in for GNOME to load it."
else
    echo
    echo "On Wayland, GNOME only sees new extensions after a new login."
    echo "1. Log out and back in (with auto-login, restarting the computer does it)."
    echo "2. Run: gnome-extensions enable $UUID"
fi
