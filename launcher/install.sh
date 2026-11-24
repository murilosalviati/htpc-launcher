#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
# Installs (or updates) the HTPC launcher and makes it start on login.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="$HOME/.local/share/htpc-launcher"
CONFIG="$HOME/.config/htpc-launcher"

missing=()
python3 -c 'import gi; gi.require_version("Gtk", "4.0")' 2>/dev/null || missing+=(python3-gi gir1.2-gtk-4.0)
python3 -c 'import evdev' 2>/dev/null || missing+=(python3-evdev)
if [ ${#missing[@]} -gt 0 ]; then
    echo "Installing ${missing[*]} (asks for the sudo password)..."
    sudo apt install -y "${missing[@]}"
fi

mkdir -p "$DATA" "$CONFIG" "$HOME/.local/share/applications" "$HOME/.config/autostart"

# Older versions used Portuguese file names; move the user's icons and drop the rest.
if [ -d "$DATA/icones-apps" ]; then
    mkdir -p "$DATA/app-icons"
    cp -n "$DATA/icones-apps/"* "$DATA/app-icons/" 2>/dev/null || true
    rm -rf "$DATA/icones-apps"
    echo "Moved your icons from icones-apps/ to app-icons/."
fi
rm -rf "$DATA/icones" "$DATA/edicao.py"

cp "$HERE/launcher.py" "$HERE/editor.py" "$HERE/i18n.py" "$HERE/themes.py" "$HERE/launcher.css" \
   "$HERE/../common/htpc_config.py" "$DATA/"
rm -rf "$DATA/icons"
cp -r "$HERE/icons" "$DATA/"
# Icons chosen by you (kept out of the public repository).
if [ -d "$HERE/../app-icons" ]; then
    mkdir -p "$DATA/app-icons"
    cp "$HERE/../app-icons/"* "$DATA/app-icons/"
fi

if [ ! -f "$CONFIG/apps.json" ]; then
    cp "$HERE/../config/apps.json" "$CONFIG/"
    echo "Created $CONFIG/apps.json"
fi

# The controller service uses this command to start the launcher when it is not running.
# This also converts an apps.json from an older version to the current format.
python3 - "$CONFIG/apps.json" "$DATA/launcher.py" "$DATA" <<'EOF'
import sys
config_path, launcher, data = sys.argv[1:]
sys.path.insert(0, data)
import htpc_config
cfg, _ = htpc_config.load(config_path)
cfg.setdefault("launcher", {})["launch"] = ["python3", launcher]
cfg["launcher"].setdefault("id", "htpc-launcher")
htpc_config.save(cfg, config_path)
print("apps.json is up to date (language: %s)" % cfg.get("language"))
EOF

sed "s|@DATA@|$DATA|g" "$HERE/htpc-launcher.desktop.in" > "$HOME/.local/share/applications/htpc-launcher.desktop"
cp "$HOME/.local/share/applications/htpc-launcher.desktop" "$HOME/.config/autostart/"

echo "Launcher installed. It starts by itself on the next login."
echo "To start it now, in the TV session: gtk-launch htpc-launcher"
