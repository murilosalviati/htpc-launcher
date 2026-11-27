import subprocess
from types import SimpleNamespace

import pytest

from htpc.backends.linux import system as linux_system


def make(session_call, run):
    s = linux_system.LinuxSystem.__new__(linux_system.LinuxSystem)
    s._session = SimpleNamespace(call=session_call)
    linux_system.subprocess.run = run
    return s


@pytest.fixture(autouse=True)
def keep_run():
    run = subprocess.run
    yield
    linux_system.subprocess.run = run


def test_restart_goes_through_gnome_first():
    calls, ran = [], []
    s = make(lambda addr, method, timeout: calls.append(method), lambda *a, **k: ran.append(a))
    s.reboot()
    s.power_off()
    assert calls == ["RequestReboot", "RequestShutdown"] and ran == []


def test_without_gnome_systemctl_and_its_refusal_is_reported():
    def no_gnome(addr, method, timeout):
        raise RuntimeError("org.freedesktop.DBus.Error.ServiceUnknown")

    refused = SimpleNamespace(returncode=1, stdout="", stderr="Operation inhibited by \"gnome-session\"")
    s = make(no_gnome, lambda cmd, **k: refused)
    with pytest.raises(RuntimeError, match="inhibited"):
        s.reboot()
    ok = SimpleNamespace(returncode=0, stdout="", stderr="")
    s = make(no_gnome, lambda cmd, **k: ok)
    s.power_off()   # no error
