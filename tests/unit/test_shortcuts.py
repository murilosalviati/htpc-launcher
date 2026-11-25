from types import SimpleNamespace

from htpc import shortcuts as sc


def test_app_ids_tolerate_hand_edited_entries():
    assert sc.app_ids({"id": "Org.App", "extra_ids": ["Other"]}) == ["org.app", "other"]
    assert sc.app_ids({"id": "a", "extra_ids": None}) == ["a"]
    assert sc.app_ids({"id": "a", "extra_ids": "b"}) == ["a", "b"]
    assert sc.app_ids({"name": "no id"}) == []
    assert sc.app_ids("not a dict") == []


def test_app_for_window_matches_any_of_the_window_names():
    cfg = {"apps": [{"id": "org.jellyfin.JellyfinDesktop"}, {"id": "steam", "extra_ids": ["steamwebhelper"]}]}
    window = SimpleNamespace(ids=["steamwebhelper"], app_id="")
    assert sc.app_for_window(cfg, window)["id"] == "steam"
    assert sc.app_for_window(cfg, SimpleNamespace(ids=[], app_id="unknown")) is None


def test_unusable_custom_combos_fall_back_to_the_defaults():
    assert sc.combos({"shortcuts": {"home": ["guide", "a"]}})["home"] == frozenset({"guide", "a"})
    overlapping = {"shortcuts": {"home": ["start", "select"], "close": ["start", "select", "a"]}}
    assert sc.combos(overlapping) == sc.DEFAULT_COMBOS


def test_combo_problems():
    assert sc.combo_problem({"guide"}, sc.CLOSE_COMBO) == "too_short"
    assert sc.combo_problem({"guide", "up"}, sc.CLOSE_COMBO) == "bad_button"
    assert sc.combo_problem({"start", "select"}, sc.CLOSE_COMBO) == "overlap"
    assert sc.combo_problem({"guide", "a"}, sc.CLOSE_COMBO) is None


def test_the_pointer_is_hidden_at_most_once_per_interval():
    hidden = []
    stub = SimpleNamespace(windows=SimpleNamespace(hide_pointer=lambda: hidden.append(1)),
                           guide=lambda: None, close=lambda: None)
    gs = sc.GamepadShortcuts(stub, settings=lambda: {})
    press = SimpleNamespace(kind="button", device="p", name="a", value=1)
    gs.handle(press)
    gs.handle(press)
    assert hidden == [1]
    gs.pointer.reset()
    gs.handle(press)
    assert hidden == [1, 1]
