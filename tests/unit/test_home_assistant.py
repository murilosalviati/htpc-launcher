from types import SimpleNamespace

from htpc import home_assistant as ha


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def press(device="pad"):
    return SimpleNamespace(kind="button", device=device, name="a", value=1)


def test_activity_is_sent_at_most_once_a_minute(tmp_path):
    clock, sent = Clock(), []
    h = ha.HomeAssistant(SimpleNamespace(devs={}), settings=lambda: {}, clock=clock, background=False,
                         marker=lambda: tmp_path / "no-marker")
    h._send = lambda event, gamepad="": sent.append(event)
    h.button(press())
    clock.now += 30
    h.button(press())
    clock.now += 31
    h.button(press())
    assert sent == ["gamepad_activity", "gamepad_activity"]


def test_a_wake_press_counts_as_activity(tmp_path):
    clock, sent = Clock(), []
    h = ha.HomeAssistant(SimpleNamespace(devs={}), settings=lambda: {}, clock=clock, background=False,
                         marker=lambda: tmp_path / "no-marker")
    h._send = lambda event, gamepad="": sent.append(event)
    h.wake(press())
    h.button(press())
    assert sent == ["gamepad_activity"]


def test_the_gate_file_is_written_once_while_open_and_kept_fresh_while_closed():
    writes, tv = [], {"state": "on"}
    cfg = {"home_assistant": {"url": "http://ha", "token": "t", "tv_entity": "media_player.tv"}}
    gate = ha.TvGate(lambda: cfg, lambda event: None, get=lambda url, token: {"state": tv["state"]},
                     gate=writes.append)
    for state, checks in (("on", 3), ("off", 2), ("on", 2)):
        tv["state"] = state
        for _ in range(checks):
            gate.check()
    assert writes == [False, True, True, False]


def test_app_events_are_checked_at_most_every_couple_of_seconds():
    clock, asked = Clock(), []
    events = ha.AppEvents(SimpleNamespace(windows=lambda: asked.append(1) or []),
                          SimpleNamespace(playback=lambda: "stopped"),
                          settings=lambda: {"home_assistant": {"url": "http://ha", "events_webhook_id": "x"}},
                          post=lambda url, payload: None, clock=clock, background=False)
    events.tick()
    events.tick()
    clock.now += ha.EVENTS_EVERY
    events.tick()
    assert len(asked) == 2
