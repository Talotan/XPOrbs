"""Engaged: the short-lived set of GUIDs the player was fighting (pure logic, fake clock)."""


class Rig:
    def __init__(self, env, **cfg):
        env.load_addon()
        self.env = env
        self.t = 0.0
        cfg["now"] = lambda: self.t
        self.e = env.ns.Engaged.New(env.lua.table_from(cfg))

    def mark(self, guid):
        self.e.Mark(self.e, guid)

    def engaged(self, guid):
        return self.e.IsEngaged(self.e, guid)

    def count(self):
        return self.e.Count(self.e)


def test_marked_guid_is_engaged(env):
    r = Rig(env)
    assert not r.engaged("G1")
    r.mark("G1")
    assert r.engaged("G1") and not r.engaged("G2")


def test_non_strings_are_ignored(env):
    r = Rig(env)
    for junk in (None, 5, True, {}, 1.5):
        r.mark(junk)
        assert not r.engaged(junk)
    assert r.count() == 0


def test_default_window_is_ten_seconds(env):
    r = Rig(env)
    r.mark("G1")
    r.t = 10.0
    assert r.engaged("G1")
    r.t = 10.01
    assert not r.engaged("G1")
    assert r.count() == 0  # the expired entry is gone


def test_remarking_refreshes_the_window(env):
    r = Rig(env, window=5)
    r.mark("G1")
    r.t = 4.0
    r.mark("G1")
    r.t = 8.0
    assert r.engaged("G1")
    r.t = 9.5
    assert not r.engaged("G1")


def test_custom_window(env):
    r = Rig(env, window=2)
    r.mark("G1")
    r.t = 1.9
    assert r.engaged("G1")
    r.t = 2.1
    assert not r.engaged("G1")


def test_pruned_by_age_when_marking(env):
    r = Rig(env, window=3)
    r.mark("A")
    r.mark("B")
    r.t = 4.0
    r.mark("C")  # A and B are stale and are dropped by this call
    assert r.count() == 1 and r.engaged("C")


def test_cap_evicts_the_oldest(env):
    r = Rig(env, window=100, cap=3)
    for i, g in enumerate(("A", "B", "C", "D")):
        r.t = float(i)
        r.mark(g)
    assert r.count() == 3
    assert not r.engaged("A") and r.engaged("B") and r.engaged("C") and r.engaged("D")


def test_default_cap_is_forty(env):
    r = Rig(env, window=1000)
    for i in range(60):
        r.t = float(i)
        r.mark(f"G{i}")
    assert r.count() == 40
    assert not r.engaged("G19") and r.engaged("G20") and r.engaged("G59")


def test_remarking_an_existing_guid_does_not_evict(env):
    r = Rig(env, window=100, cap=2)
    r.mark("A")
    r.t = 1.0
    r.mark("B")
    r.t = 2.0
    r.mark("A")  # already present: still two entries, nobody is evicted
    assert r.count() == 2 and r.engaged("A") and r.engaged("B")
