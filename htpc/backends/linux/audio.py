# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""The audio output through pactl, which talks to PipeWire (Ubuntu's default,
through pipewire-pulse) and to PulseAudio alike."""

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
