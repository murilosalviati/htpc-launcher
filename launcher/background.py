# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Work that must not freeze the screen: network, D-Bus, installers.

GTK may only be touched from its own thread, so the job runs in a thread and its
answer comes back on the GTK main loop."""

import threading

from gi.repository import GLib


def in_background(job, done):
    """Run job() in a thread, then done(result) on the GTK main loop. If job()
    raised, done gets the exception instead of a result."""
    def work():
        try:
            result = job()
        except Exception as e:  # noqa: BLE001 - handed to done(), which shows it
            result = e
        GLib.idle_add(lambda: (done(result), False)[1])

    threading.Thread(target=work, daemon=True).start()
