import json

from htpc import home_assistant as ha

CFG = {"home_assistant": {"url": "http://ha:8123/", "token": "T"}}

STATES = [
    {"entity_id": "light.sala", "state": "on",
     "attributes": {"friendly_name": "Luz da sala", "brightness": 204, "supported_color_modes": ["brightness"]}},
    {"entity_id": "light.quarto", "state": "off",
     "attributes": {"friendly_name": "Abajur", "supported_color_modes": ["onoff"]}},
    {"entity_id": "light.varanda", "state": "unavailable", "attributes": {"friendly_name": "Varanda"}},
    {"entity_id": "switch.som", "state": "on", "attributes": {"friendly_name": "Tomada do som"}},
    {"entity_id": "scene.cinema", "state": "scening", "attributes": {"friendly_name": "Cinema"}},
    {"entity_id": "media_player.tv", "state": "on", "attributes": {}},
]


def get(url, token):
    assert token == "T" and url == "http://ha:8123/api/states"
    return STATES


class Post:
    def __init__(self, areas=None, fail=False):
        self.calls, self.areas, self.fail = [], areas or {}, fail

    def __call__(self, url, token, payload):
        self.calls.append((url, payload))
        if url.endswith("/api/template"):
            if self.fail:
                raise OSError("no")
            return json.dumps(self.areas)
        return "[]"


def test_home_ready():
    assert ha.home_ready(CFG)
    assert not ha.home_ready({"home_assistant": {"url": "x"}})
    assert not ha.home_ready({"home_assistant": {**CFG["home_assistant"], "home_screen": False}})
    assert not ha.home_ready({"home_assistant": {**CFG["home_assistant"], "enabled": False}})


def test_without_a_choice_every_light_by_room():
    post = Post({"light.sala": "Sala", "light.quarto": "Quarto", "light.varanda": None})
    h = ha.house(CFG, get, post)
    assert [d["entity"] for d in h["devices"]] == ["light.quarto", "light.sala", "light.varanda"]
    sala = h["devices"][1]
    assert sala["on"] and sala["brightness"] == 80 and sala["dimmable"] and sala["area"] == "Sala"
    quarto = h["devices"][0]
    assert not quarto["on"] and quarto["brightness"] is None and not quarto["dimmable"]
    assert not h["devices"][2]["available"]
    assert h["scenes"] == [{"entity": "scene.cinema", "name": "Cinema"}]
    template = post.calls[0][1]["template"]
    assert 'area_name("light.sala")' in template and template.endswith("| tojson }}")


def test_a_choice_keeps_its_order_and_drops_what_is_gone():
    cfg = {"home_assistant": {**CFG["home_assistant"], "devices": ["switch.som", "light.gone", "light.sala"],
                              "scenes": []}}
    h = ha.house(cfg, get, Post())
    assert [d["entity"] for d in h["devices"]] == ["switch.som", "light.sala"] and h["scenes"] == []


def test_areas_failing_is_not_fatal():
    h = ha.house(CFG, get, Post(fail=True))
    assert len(h["devices"]) == 3 and all(d["area"] is None for d in h["devices"])


def test_candidates_lights_first():
    assert ha.device_candidates(CFG, get) == [
        ("light.quarto", "Abajur"), ("light.sala", "Luz da sala"), ("light.varanda", "Varanda"),
        ("switch.som", "Tomada do som")]


def test_services():
    post = Post()
    ha.toggle(CFG, "light.sala", post)
    ha.toggle(CFG, "scene.cinema", post)
    ha.set_brightness(CFG, "light.sala", 40, post)
    ha.set_brightness(CFG, "light.sala", 0, post)
    assert post.calls == [
        ("http://ha:8123/api/services/light/toggle", {"entity_id": "light.sala"}),
        ("http://ha:8123/api/services/scene/turn_on", {"entity_id": "scene.cinema"}),
        ("http://ha:8123/api/services/light/turn_on", {"entity_id": "light.sala", "brightness_pct": 40}),
        ("http://ha:8123/api/services/light/turn_off", {"entity_id": "light.sala"}),
    ]


def test_light_capabilities():
    states = [{"entity_id": "light.rgb", "state": "on", "attributes": {
        "friendly_name": "RGB", "supported_color_modes": ["hs", "color_temp"], "color_mode": "hs",
        "hs_color": [30.0, 80.0], "min_color_temp_kelvin": 2200, "max_color_temp_kelvin": 6500, "brightness": 255}}]
    d = ha.house({"home_assistant": {**CFG["home_assistant"], "devices": ["light.rgb"]}},
                 lambda url, token: states, Post())["devices"][0]
    assert d["color"] and d["temperature"] and d["hs"] == [30.0, 80.0] and d["min_kelvin"] == 2200
    sala = ha.house(CFG, get, Post())["devices"][1]
    assert sala["dimmable"] and not sala["color"] and not sala["temperature"] and sala["hs"] is None


def test_grouped_by_room_keeps_the_choice_order_inside_each():
    cfg = {"home_assistant": {**CFG["home_assistant"], "group_by_area": True,
                              "devices": ["switch.som", "light.quarto", "light.sala"]}}
    areas = {"switch.som": "Sala", "light.quarto": "Quarto", "light.sala": "Sala"}
    h = ha.house(cfg, get, Post(areas))
    # the rooms in the order they first come in the choice (Sala first), not alphabetical
    assert [d["entity"] for d in h["devices"]] == ["switch.som", "light.sala", "light.quarto"]


def test_names_of_your_own():
    cfg = {"home_assistant": {**CFG["home_assistant"], "names": {"light.sala": "Teto"}}}
    names = {d["entity"]: d["name"] for d in ha.house(cfg, get, Post())["devices"]}
    assert names["light.sala"] == "Teto" and names["light.quarto"] == "Abajur"


def test_set_light():
    post = Post()
    ha.set_light(CFG, "light.sala", post, color_temp_kelvin=2700)
    ha.set_light(CFG, "light.sala", post, hs_color=[0, 100])
    assert post.calls == [
        ("http://ha:8123/api/services/light/turn_on", {"entity_id": "light.sala", "color_temp_kelvin": 2700}),
        ("http://ha:8123/api/services/light/turn_on", {"entity_id": "light.sala", "hs_color": [0, 100]}),
    ]


# --- another input (HDMI 2) --------------------------------------------------------

TV = {"home_assistant": {**CFG["home_assistant"], "tv_entity": "media_player.tv", "htpc_source": "PC"}}


def tv_state(source, state="on"):
    return lambda url, token: {"state": state, "attributes": {"source": source, "source_list": ["PC", "HDMI 2"]}}


def test_another_input_is_away():
    assert ha.fetch_tv_state(TV, tv_state("PC")) == "on"
    assert ha.fetch_tv_state(TV, tv_state("HDMI 2")) == "away"
    assert ha.fetch_tv_state(TV, tv_state("HDMI 2", "off")) == "off"
    no_home = {"home_assistant": {**TV["home_assistant"], "htpc_source": None}}
    assert ha.fetch_tv_state(no_home, tv_state("HDMI 2")) == "on"   # not known yet: never blocks
    assert ha.tv_sources(TV, tv_state("HDMI 2")) == ("HDMI 2", ["PC", "HDMI 2"])


def test_switch_source_leaves_the_marker_then_asks(tmp_path):
    post = Post()
    marker = tmp_path / "tv-away"
    ha.switch_source(TV, "HDMI 2", post, marker=marker)
    assert marker.exists() and ha.recently_away(marker)
    assert not ha.recently_away(marker, now=lambda: marker.stat().st_mtime + ha.AWAY_QUIET + 1)
    assert post.calls == [("http://ha:8123/api/services/media_player/select_source",
                           {"entity_id": "media_player.tv", "source": "HDMI 2"})]


class Event:
    def __init__(self, value=1):
        self.kind, self.name, self.value, self.device = "button", "a", value, "pad"


def test_away_blocks_and_the_first_press_brings_the_tv_back():
    woke = []
    gate = ha.TvGate(lambda: TV, woke.append, get=tv_state("HDMI 2"), gate=lambda blocked: None,
                     away=lambda: False)
    gate.check()
    assert gate.state == "away" and gate.blocks(Event()) and len(woke) == 1


def test_right_after_the_switch_presses_do_not_bring_it_back():
    woke = []
    gate = ha.TvGate(lambda: TV, woke.append, get=tv_state("HDMI 2"), gate=lambda blocked: None,
                     away=lambda: True)
    gate.check()
    assert gate.blocks(Event()) and woke == []
    sent = []
    activity = ha.HomeAssistant(None, settings=lambda: {}, away=lambda: True)
    activity._send = lambda *a: sent.append(a)
    activity.button(Event())
    assert sent == []
