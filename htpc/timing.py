# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Doing something at most once every so many seconds."""

import time


class Throttle:
    """ready() is True at most once every `every` seconds (the first call always is).

    The clock is injectable so tests can move time by hand."""

    def __init__(self, every, clock=time.monotonic):
        self.every = every
        self.clock = clock
        self.last = None

    def ready(self):
        now = self.clock()
        if self.last is not None and now - self.last < self.every:
            return False
        self.last = now
        return True

    def touch(self):
        """Count it as done now (something else already did the job)."""
        self.last = self.clock()

    def reset(self):
        """The next ready() is True whatever the time."""
        self.last = None
