# SPDX-License-Identifier: GPL-3.0-or-later
from htpc.i18n import Translator, glyphs


def test_playstation_glyphs_take_the_same_places():
    assert glyphs("Ⓐ open  Ⓑ back  Ⓧ delete  Ⓨ space", "playstation") == "✕ open  ○ back  □ delete  △ space"
    assert glyphs("Ⓐ open", "xbox") == "Ⓐ open"


def test_translator_follows_the_pad():
    t = Translator("en")
    assert "Ⓐ" in t("house_note", n=2)
    t.buttons = "playstation"
    assert "✕" in t("house_note", n=2) and "Ⓐ" not in t("house_note", n=2)
