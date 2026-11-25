# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Builds the HOME that tests/test_launcher.py expects for its icon checks,
with plain colored placeholder images (no third-party logos).

Run: python3 tests/make_test_home.py /tmp/test-home
"""
import pathlib
import struct
import sys
import zlib


def png(path, rgb, size=64):
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def main(home):
    home = pathlib.Path(home)
    icons = home / ".local/share/htpc-launcher/app-icons"
    icons.mkdir(parents=True, exist_ok=True)
    for name, rgb in (("jellyfin", (90, 60, 170)), ("moonlight", (40, 90, 160)),
                      ("steam", (30, 50, 80)), ("youtube", (200, 30, 30))):
        png(icons / f"{name}.png", rgb)
    apps = home / ".local/share/applications"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / "org.example.Player.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Example Player\nExec=true\n"
        "Icon=multimedia-player\nStartupWMClass=example-player\n")
    # Two "installed Flatpaks", as the app list finds them.
    exports = home / ".local/share/flatpak/exports/share"
    (exports / "applications").mkdir(parents=True, exist_ok=True)
    (exports / "icons/hicolor/scalable/apps").mkdir(parents=True, exist_ok=True)
    for app_id in ("rocks.shy.VacuumTube", "com.moonlight_stream.Moonlight"):
        (exports / "applications" / f"{app_id}.desktop").write_text(
            f"[Desktop Entry]\nType=Application\nName={app_id}\nExec=true\nIcon={app_id}\n")
        (exports / "icons/hicolor/scalable/apps" / f"{app_id}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<circle cx="32" cy="32" r="30" fill="#5577aa"/></svg>')


if __name__ == "__main__":
    main(sys.argv[1])
