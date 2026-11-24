# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Background colors for the launcher.

Each theme is a soft glow at the top of the screen fading into a dark base:
(glow, middle, base). Dark bases keep the text readable and avoid lighting up
the room at night. "background" in apps.json picks one by its id.
"""

DEFAULT_THEME = "midnight"

THEMES = {
    "midnight": ("#1f2b47", "#111726", "#0a0d14"),
    "ocean":    ("#0e3d4f", "#0a1f2a", "#061116"),
    "forest":   ("#1c3d2c", "#0e2018", "#07110c"),
    "aurora":   ("#123f3b", "#14213a", "#0a0d18"),
    "plum":     ("#3b2152", "#1b1228", "#0d0913"),
    "wine":     ("#4d1e2a", "#231015", "#11080a"),
    "ember":    ("#4f3216", "#22170c", "#100b06"),
    "graphite": ("#2e3138", "#17191e", "#0c0d10"),
    "black":    ("#121212", "#060606", "#000000"),
}


def css(theme_id):
    """CSS for the window background, plus one swatch class per theme for the picker."""
    glow, middle, base = THEMES.get(theme_id) or THEMES[DEFAULT_THEME]
    rules = [
        "window.htpc {"
        f" background-color: {base};"
        f" background-image: radial-gradient(ellipse at 50% -10%, {glow} 0%, {middle} 45%, {base} 80%); }}"
    ]
    for tid, (g, m, b) in THEMES.items():
        rules.append(f".swatch-{tid} {{ background-color: {b};"
                     f" background-image: radial-gradient(ellipse at 50% -20%, {g} 0%, {m} 55%, {b} 95%); }}")
    return "\n".join(rules)
