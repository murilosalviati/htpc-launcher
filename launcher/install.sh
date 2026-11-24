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
# Before 0.1.0-beta.3 the shared modules were loose files; they now live in the htpc package.
rm -f "$DATA/htpc_config.py" "$DATA/i18n.py" "$DATA/themes.py"

cp "$HERE/launcher.py" "$HERE/editor.py" "$HERE/settings.py" "$HERE/launcher.css" "$DATA/"
rm -rf "$DATA/htpc"
cp -r "$HERE/../htpc" "$DATA/"
find "$DATA/htpc" -name __pycache__ -prune -exec rm -rf {} +
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
from htpc import config
cfg, _ = config.load(config_path)
cfg.setdefault("launcher", {})["launch"] = ["python3", launcher]
cfg["launcher"].setdefault("id", "htpc-launcher")
config.save(cfg, config_path)
print("apps.json is up to date (language: %s)" % cfg.get("language"))
EOF

# Some Flatpaks ship without access to gamepads, so their own gamepad support
# (SDL) finds none. Jellyfin Desktop is one: let it see input devices.
# "--device=input" needs Flatpak 1.15.6 or later; older ones only have "all".
grant_input() {
    local app="$1"
    flatpak info "$app" >/dev/null 2>&1 || return 0
    if flatpak info --show-permissions "$app" | grep -qE '^devices=.*\b(all|input)\b'; then
        return 0
    fi
    local device=input
    if [ "$(printf '%s\n' "1.15.6" "$(flatpak --version | awk '{print $2}')" | sort -V | head -1)" != "1.15.6" ]; then
        device=all
    fi
    flatpak override --user --device="$device" "$app"
    echo "Gave $app access to gamepads (--device=$device)."
}
if command -v flatpak >/dev/null; then
    grant_input org.jellyfin.JellyfinDesktop
fi

# Jellyfin Desktop's own Xbox map only matches "Xbox One"; ours matches any Xbox
# controller and leaves the guide button to the launcher. Profiles only exist
# after Jellyfin's first start: run this script again after that.
JF_PROFILES="$HOME/.var/app/org.jellyfin.JellyfinDesktop/data/jellyfin-desktop/profiles"
for profile in "$JF_PROFILES"/*/; do
    [ -d "$profile" ] || continue
    mkdir -p "$profile/inputmaps"
    cp "$HERE/../extras/jellyfin/xbox-series.json" "$profile/inputmaps/xbox-series.json"
    echo "Installed the Xbox gamepad map for Jellyfin Desktop in $profile"
done

sed "s|@DATA@|$DATA|g" "$HERE/htpc-launcher.desktop.in" > "$HOME/.local/share/applications/htpc-launcher.desktop"
cp "$HOME/.local/share/applications/htpc-launcher.desktop" "$HOME/.config/autostart/"

echo "Launcher installed. It starts by itself on the next login."
echo "To start it now, in the TV session: gtk-launch htpc-launcher"
