import json
import os
import time

from htpc import config


def write(path, cfg):
    path.write_text(json.dumps(cfg))


def settle(path):
    old = time.time() - 10
    os.utime(path, (old, old))


def test_a_just_written_file_is_read_every_time(tmp_path):
    path = tmp_path / "apps.json"
    write(path, {"apps": [{"id": "a"}]})
    assert config.load_quietly(path) is not config.load_quietly(path)


def test_a_settled_file_is_read_once(tmp_path):
    path = tmp_path / "apps.json"
    write(path, {"apps": [{"id": "a"}]})
    settle(path)
    assert config.load_quietly(path) is config.load_quietly(path)


def test_a_changed_file_is_read_again(tmp_path):
    path = tmp_path / "apps.json"
    write(path, {"apps": [{"id": "a"}]})
    settle(path)
    config.load_quietly(path)
    write(path, {"apps": [{"id": "b"}]})
    assert config.load_quietly(path)["apps"][0]["id"] == "b"


def test_a_broken_file_falls_back_to_the_last_good_copy_without_writing(tmp_path):
    path = tmp_path / "apps.json"
    config.save({"apps": [{"id": "good"}]}, path)
    path.write_text("{ not json")
    assert config.load_quietly(path)["apps"][0]["id"] == "good"
    assert path.read_text() == "{ not json"


def test_nothing_readable_gives_an_empty_config(tmp_path):
    assert config.load_quietly(tmp_path / "missing.json") == {}
