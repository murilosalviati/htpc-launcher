# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Picks the backend for the running operating system."""

import sys

_backend = None


def get_backend():
    global _backend
    if _backend is None:
        if sys.platform.startswith("linux"):
            from .linux import LinuxBackend
            _backend = LinuxBackend()
        elif sys.platform.startswith("win"):
            from .windows import WindowsBackend
            _backend = WindowsBackend()
        else:
            raise RuntimeError(f"HTPC Launcher does not support {sys.platform} yet")
    return _backend


def set_backend(backend):
    """Use a specific backend (tests, or forcing one by hand)."""
    global _backend
    _backend = backend
