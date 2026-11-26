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


def test_playstation_shoulders_and_triggers():
    assert glyphs("LB ‹ 1 de 3 › RB   LT ‹ categorias › RT", "playstation") == "L1 ‹ 1 de 3 › R1   L2 ‹ categorias › R2"
    assert glyphs("LB RB mover", "xbox") == "LB RB mover"
    assert glyphs("BLT sandwich", "playstation") == "BLT sandwich"   # whole words only
