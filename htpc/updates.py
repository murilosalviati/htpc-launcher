# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Updates from the launcher's Settings: the launcher itself (GitHub releases)
and the Flatpak apps.

The launcher: the newest release on GitHub (pre-releases included, since every
version so far is a beta) is compared with the running version; installing it
downloads the release's .tar.gz, extracts it next to the other data and runs
its install.sh, which keeps apps.json and restarts the background service. The
launcher then restarts itself; a new GNOME extension version still needs a new
login.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import urllib.request

from . import __version__, paths

log = logging.getLogger("htpc")

REPO = "murilosalviati/htpc-launcher"
API = f"https://api.github.com/repos/{REPO}/releases"
TIMEOUT = 15
INSTALL_TIMEOUT = 300


def version_key(text):
    """Sortable key for "0.1.0-beta.5" style versions (a final release sorts after its betas)."""
    text = str(text).lstrip("v")
    core, _, pre = text.partition("-")
    numbers = tuple(int(n) for n in re.findall(r"\d+", core)[:3])
    numbers += (0,) * (3 - len(numbers))
    if not pre:
        return numbers + ((1, "", 0),)
    name = re.sub(r"[\d.]+$", "", pre).rstrip(".") or pre
    n = re.findall(r"\d+", pre)
    return numbers + ((0, name, int(n[-1]) if n else 0),)


def is_newer(candidate, current=__version__):
    try:
        return version_key(candidate) > version_key(current)
    except ValueError:
        return False


def http_get_json(url):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"htpc-launcher/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_release(get=None):
    """{"version", "tag", "url" (the .tar.gz), "notes", "page"} of the newest
    published release, or None if there is none."""
    for release in (get or http_get_json)(API):
        if release.get("draft"):
            continue
        assets = [a for a in release.get("assets", []) if a.get("name", "").endswith(".tar.gz")]
        if not assets:
            continue
        return {"version": release["tag_name"].lstrip("v"), "tag": release["tag_name"],
                "url": assets[0]["browser_download_url"], "notes": release.get("body") or "",
                "page": release.get("html_url", "")}
    return None


def download(url, target):
    request = urllib.request.Request(url, headers={"User-Agent": f"htpc-launcher/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(target, "wb") as f:
        shutil.copyfileobj(response, f)


def extension_version(folder):
    """The "version" in a GNOME extension's metadata.json, or None."""
    try:
        with open(os.path.join(folder, "metadata.json"), encoding="utf-8") as f:
            return json.load(f).get("version")
    except (OSError, ValueError):
        return None


def installed_extension_dir():
    return os.path.expanduser("~/.local/share/gnome-shell/extensions/htpc-launcher@htpc")


def install_release(release, fetch=None, run=None, workdir=None):
    """Download, extract and install a release. Returns {"version", "extension_changed"}.
    Raises with the installer's last lines if it fails."""
    workdir = workdir or os.path.join(paths.data_dir(), "update")
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir)
    archive = os.path.join(workdir, "release.tar.gz")
    (fetch or download)(release["url"], archive)
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(workdir, filter="data")   # no paths outside workdir, no devices
        except TypeError:                            # Python before 3.12
            for member in tar.getmembers():
                if member.name.startswith(("/", "..")) or ".." in member.name.split("/"):
                    raise RuntimeError(f"unsafe path in the archive: {member.name}")
            tar.extractall(workdir)
    folders = [os.path.join(workdir, d) for d in os.listdir(workdir)
               if os.path.isfile(os.path.join(workdir, d, "install.sh"))]
    if not folders:
        raise RuntimeError("the release has no install.sh")
    source = folders[0]
    before = extension_version(installed_extension_dir())
    after = extension_version(os.path.join(source, "gnome-extension", "htpc-launcher@htpc"))
    log.info("installing %s from %s", release["version"], source)
    result = (run or subprocess.run)(["bash", "install.sh"], cwd=source, capture_output=True, text=True,
                                     timeout=INSTALL_TIMEOUT, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-4:])
        raise RuntimeError(tail or f"install.sh failed ({result.returncode})")
    return {"version": release["version"], "extension_changed": before is not None and after != before}


# --- Flatpak ---------------------------------------------------------------------------

def flatpak_updates(run=None):
    """[(app id, name)] of the Flatpaks (user and system) with an update waiting."""
    if not (run or shutil.which("flatpak")):
        return []
    found = {}
    for scope in ("--user", "--system"):
        result = (run or subprocess.run)(
            ["flatpak", "remote-ls", "--updates", scope, "--columns=application,name"],
            capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if parts and parts[0] and parts[0] != "Application ID":
                found[parts[0]] = parts[1] if len(parts) > 1 and parts[1] else parts[0]
    return sorted(found.items(), key=lambda item: item[1].lower())


def flatpak_update(run=None):
    """Update every Flatpak (user and system). Raises with the last lines on failure."""
    result = (run or subprocess.run)(["flatpak", "update", "-y", "--noninteractive"],
                                     capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-3:])
        raise RuntimeError(tail or f"flatpak update failed ({result.returncode})")
