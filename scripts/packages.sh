# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
# shellcheck shell=bash
# Sourced by the install scripts: installs what the launcher and the controller
# need from the distribution's own packages, on Debian/Ubuntu (apt), Fedora (dnf),
# Arch (pacman) and openSUSE (zypper).
#
#   need_packages gtk evdev jeepney
#
# installs the missing ones (asking for the sudo password) and stops the install
# with a clear message where it can't: an unknown distribution, or an immutable
# one (Fedora Silverblue / Kinoite, Bazzite...), where packages are layered by hand.

# What is checked, by the name used in need_packages.
_check_gtk()     { python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' 2>/dev/null; }
_check_evdev()   { python3 -c 'import evdev' 2>/dev/null; }
_check_jeepney() { python3 -c 'import jeepney' 2>/dev/null; }

# The package manager: apt, dnf, pacman, zypper or "" when none of those.
package_manager() {
    if [ -e /run/ostree-booted ]; then
        echo ostree
        return
    fi
    local pm
    for pm in apt-get dnf pacman zypper; do
        if command -v "$pm" >/dev/null 2>&1; then
            [ "$pm" = apt-get ] && pm=apt
            echo "$pm"
            return
        fi
    done
    echo ""
}

# The distribution's package names for one of ours.
package_names() {   # package_names PM NAME
    case "$1:$2" in
        apt:gtk)        echo "python3-gi gir1.2-gtk-4.0" ;;
        apt:evdev)      echo "python3-evdev" ;;
        apt:jeepney)    echo "python3-jeepney" ;;
        dnf:gtk)        echo "python3-gobject gtk4" ;;
        dnf:evdev)      echo "python3-evdev" ;;
        dnf:jeepney)    echo "python3-jeepney" ;;
        pacman:gtk)     echo "python-gobject gtk4" ;;
        pacman:evdev)   echo "python-evdev" ;;
        pacman:jeepney) echo "python-jeepney" ;;
        zypper:gtk)     echo "python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0" ;;
        zypper:evdev)   echo "python3-evdev" ;;
        zypper:jeepney) echo "python3-jeepney" ;;
        *) return 1 ;;
    esac
}

need_packages() {   # need_packages NAME...
    local name missing=() packages=() pm
    for name in "$@"; do
        "_check_$name" || missing+=("$name")
    done
    [ ${#missing[@]} -eq 0 ] && return 0

    pm="$(package_manager)"
    for name in "${missing[@]}"; do
        # shellcheck disable=SC2207
        packages+=($(package_names "$pm" "$name" 2>/dev/null || true))
    done
    if [ "$pm" = ostree ]; then
        echo "This is an immutable system (Fedora Silverblue, Kinoite, Bazzite...): missing ${missing[*]}." >&2
        echo "Add them with:  rpm-ostree install $(for n in "${missing[@]}"; do package_names dnf "$n"; done | tr '\n' ' ')" >&2
        echo "then restart the computer and run this install again." >&2
        exit 1
    fi
    if [ -z "$pm" ] || [ ${#packages[@]} -eq 0 ]; then
        echo "Missing: ${missing[*]} (Python 3 with GTK 4, python-evdev, jeepney)." >&2
        echo "Install them with your distribution's package manager, then run this install again." >&2
        exit 1
    fi

    local sudo=()
    [ "$(id -u)" -ne 0 ] && sudo=(sudo)
    echo "Installing ${packages[*]} (asks for the sudo password)..."
    case "$pm" in
        apt)    "${sudo[@]}" apt-get install -y "${packages[@]}" ;;
        dnf)    "${sudo[@]}" dnf install -y "${packages[@]}" ;;
        pacman) "${sudo[@]}" pacman -S --needed --noconfirm "${packages[@]}" ;;
        zypper) "${sudo[@]}" zypper --non-interactive install "${packages[@]}" ;;
    esac
    for name in "${missing[@]}"; do
        if ! "_check_$name"; then
            echo "Still missing after installing: $name. Check the messages above." >&2
            exit 1
        fi
    done
}
