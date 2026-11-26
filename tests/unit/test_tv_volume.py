import pytest

from htpc import home_assistant as ha

CFG = {"home_assistant": {"url": "http://ha:8123", "token": "T", "tv_entity": "media_player.tv", "volume": "tv"}}


def tv(features, level=0.3, muted=False):
    attrs = {"supported_features": features, "is_volume_muted": muted}
    if level is not None:
        attrs["volume_level"] = level
    return lambda url, token: {"state": "on", "attributes": attrs}


def test_volume_goes_to_the_tv_only_when_chosen_and_set_up():
    assert ha.volume_target(CFG) == "tv"
    assert ha.volume_target({"home_assistant": {**CFG["home_assistant"], "volume": "computer"}}) == "computer"
    assert ha.volume_target({"home_assistant": {"volume": "tv"}}) == "computer"   # no address or token


def test_a_tv_that_takes_a_level_gets_one_step_more():
    posts = []
    result = ha.change_tv_volume(CFG, 1, get=tv(ha.VOLUME_SET | ha.VOLUME_STEP, 0.30),
                                 post=lambda url, token, payload: posts.append((url, payload)))
    assert result == (0.32, False)
    assert posts == [("http://ha:8123/api/services/media_player/volume_set",
                      {"entity_id": "media_player.tv", "volume_level": 0.32})]


def test_the_level_stays_between_0_and_1():
    posts = []
    ha.change_tv_volume(CFG, -1, get=tv(ha.VOLUME_SET, 0.01), post=lambda u, t, p: posts.append(p))
    assert posts[0]["volume_level"] == 0.0


def test_a_tv_with_only_steps_gets_volume_up_or_down():
    posts = []
    result = ha.change_tv_volume(CFG, -1, get=tv(ha.VOLUME_STEP, None), post=lambda u, t, p: posts.append(u))
    assert result is None and posts == ["http://ha:8123/api/services/media_player/volume_down"]


def test_a_tv_without_volume_control_says_so():
    with pytest.raises(ValueError):
        ha.change_tv_volume(CFG, 1, get=tv(0), post=lambda u, t, p: None)
    assert not ha.tv_volume_support(CFG, get=tv(ha.VOLUME_MUTE))
    assert ha.tv_volume_support(CFG, get=tv(ha.VOLUME_STEP))


def test_wake_on_lan_with_a_button_or_a_mac():
    posts = []
    post = lambda url, token, payload: posts.append((url.split("/api/")[1], payload))   # noqa: E731
    ha.wake_on_lan(CFG, "button.wake_on_lan_04_d9_f5_09_f3_12", post)
    ha.wake_on_lan(CFG, "04-D9-F5-09-F3-12", post)
    ha.wake_on_lan(CFG, "automation.ligar_pc", post)
    ha.wake_on_lan(CFG, "script.ligar_pc", post)
    assert posts == [("services/button/press", {"entity_id": "button.wake_on_lan_04_d9_f5_09_f3_12"}),
                     ("services/wake_on_lan/send_magic_packet", {"mac": "04:D9:F5:09:F3:12"}),
                     ("services/automation/trigger", {"entity_id": "automation.ligar_pc"}),
                     ("services/script/turn_on", {"entity_id": "script.ligar_pc"})]
    with pytest.raises(ValueError):
        ha.wake_on_lan(CFG, "light.desk", post)
