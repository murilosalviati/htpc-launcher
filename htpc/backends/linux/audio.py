# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""The audio output: through pactl when installed (it talks to PipeWire and to
PulseAudio alike), otherwise through PipeWire's own pw-dump and wpctl (Ubuntu
ships those, but not always pactl)."""

import json
import logging
import shutil
import subprocess

from ..base import Audio, AudioOutput

log = logging.getLogger("htpc")


class PulseAudio(Audio):
    def __init__(self, run=None):
        self.run = run or self._run

    @staticmethod
    def _run(command):
        if not shutil.which(command[0]):
            raise RuntimeError(f"{command[0]} is not installed")
        return subprocess.run(command, capture_output=True, text=True, timeout=5, check=True).stdout

    def outputs(self):
        sinks = json.loads(self.run(["pactl", "-f", "json", "list", "sinks"]) or "[]")
        default = self.run(["pactl", "get-default-sink"]).strip()
        out = []
        for sink in sinks:
            props = sink.get("properties") or {}
            name = sink.get("description") or props.get("device.description") or sink.get("name", "")
            out.append(AudioOutput(id=sink.get("name", ""), name=name, current=sink.get("name") == default,
                                   bluetooth=props.get("device.bus") == "bluetooth"
                                   or str(sink.get("name", "")).startswith("bluez_")))
        out.sort(key=lambda o: (not o.current, o.name.lower()))
        return out

    def set_output(self, output_id):
        self.run(["pactl", "set-default-sink", output_id])
        # Streams that are already playing follow (PipeWire moves most of them by
        # itself; PulseAudio does not).
        for line in self.run(["pactl", "list", "short", "sink-inputs"]).splitlines():
            stream = line.split("\t")[0].strip()
            if stream.isdigit():
                try:
                    self.run(["pactl", "move-sink-input", stream, output_id])
                except Exception as e:  # noqa: BLE001 - a stream that just ended
                    log.debug("move %s: %s", stream, e)
        log.info("audio output: %s", output_id)


class PipeWireAudio(Audio):
    """Without pactl: PipeWire's own tools, pw-dump (to list) and wpctl (to choose).
    WirePlumber then moves what is playing to the new default by itself."""

    def __init__(self, run=None):
        self.run = run or PulseAudio._run

    def _dump(self):
        return json.loads(self.run(["pw-dump"]) or "[]")

    def outputs(self):
        objects = self._dump()
        default = None
        for obj in objects:
            if obj.get("type") == "PipeWire:Interface:Metadata" and \
                    (obj.get("props") or {}).get("metadata.name") == "default":
                for entry in obj.get("metadata") or []:
                    if entry.get("key") == "default.audio.sink":
                        value = entry.get("value")
                        if isinstance(value, str):
                            try:
                                value = json.loads(value)
                            except ValueError:
                                value = {"name": value}
                        default = (value or {}).get("name")
        out = []
        for obj in objects:
            props = (obj.get("info") or {}).get("props") or {}
            if obj.get("type") != "PipeWire:Interface:Node" or props.get("media.class") != "Audio/Sink":
                continue
            name = props.get("node.name", "")
            out.append(AudioOutput(id=str(obj.get("id")), name=props.get("node.description") or name,
                                   current=name == default,
                                   bluetooth=props.get("device.api") == "bluez5" or name.startswith("bluez_")))
        out.sort(key=lambda o: (not o.current, o.name.lower()))
        return out

    def set_output(self, output_id):
        self.run(["wpctl", "set-default", str(output_id)])
        log.info("audio output: %s", output_id)


def best_audio():
    """pactl when it's there (PipeWire or PulseAudio), else PipeWire's own tools."""
    if shutil.which("pactl"):
        return PulseAudio()
    if shutil.which("pw-dump") and shutil.which("wpctl"):
        return PipeWireAudio()
    return PulseAudio()   # says what is missing when used
