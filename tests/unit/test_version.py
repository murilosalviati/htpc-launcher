# SPDX-License-Identifier: GPL-3.0-or-later
"""The VERSION file (checked by the release workflow) and htpc.__version__ (what
the updater compares releases with) must say the same thing."""
from pathlib import Path

import htpc


def test_version_file_matches_package():
    version = (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
    assert htpc.__version__ == version
