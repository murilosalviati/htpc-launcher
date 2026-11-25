#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
# Installs (or updates) everything: the GNOME extension, the controller service and the launcher.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== GNOME extension =="
"$HERE/gnome-extension/install.sh"
echo
echo "== Controller service =="
"$HERE/controller/install.sh"
echo
echo "== Launcher =="
"$HERE/launcher/install.sh"

echo
if gnome-extensions info htpc-launcher@htpc 2>/dev/null | grep -Eq '^[[:space:]]*State:[[:space:]]*ACTIVE[[:space:]]*$'; then
    echo "All set. Start the launcher now with: gtk-launch htpc-launcher"
else
    echo "Almost done: log out and back in so GNOME loads the extension,"
    echo "then run: gnome-extensions enable htpc-launcher@htpc"
    echo "The launcher starts by itself on that login."
fi
