# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Shared, platform-independent parts of HTPC Launcher.

  config     apps.json reading, writing and migration
  paths      where configuration and data live on each OS
  i18n       on-screen text per language
  themes     background colors
  shortcuts  what the guide button and the close combo do
  backends   everything that talks to the operating system (one package per OS)

Nothing in here imports a UI toolkit or an OS-specific library at module level;
those live in htpc.backends.<os> and in the launcher UI.
"""

__version__ = "0.1.0-beta.4"
