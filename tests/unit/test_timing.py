from htpc.timing import Throttle


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_first_call_is_ready_then_waits_the_interval():
    clock = Clock()
    t = Throttle(2.0, clock)
    assert t.ready()
    assert not t.ready()
    clock.now += 1.9
    assert not t.ready()
    clock.now += 0.1
    assert t.ready()


def test_touch_counts_as_done_now():
    clock = Clock()
    t = Throttle(5.0, clock)
    t.touch()
    assert not t.ready()
    clock.now += 5
    assert t.ready()


def test_reset_makes_it_ready_again():
    t = Throttle(60.0, Clock())
    assert t.ready()
    t.reset()
    assert t.ready()
