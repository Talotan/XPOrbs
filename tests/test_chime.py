"""Chime: which of the six notes to play as an orb arrives (pure logic, fake clock)."""


class Rig:
    def __init__(self, env, **cfg):
        env.load_addon()
        self.t = 0.0
        cfg["now"] = lambda: self.t
        self.c = env.ns.Chime.New(env.lua.table_from(cfg))

    def arrive(self, key="b1", at=None):
        if at is not None:
            self.t = at
        return self.c.Arrive(self.c, key)

    def done(self, key):
        self.c.Done(self.c, key)

    def open(self):
        return self.c.Open(self.c)


def test_notes_climb_one_step_per_played_note(env):
    r = Rig(env, perBurst=10)
    assert [r.arrive(at=0.1 * i) for i in range(6)] == [1, 2, 3, 4, 5, 6]


def test_top_note_repeats_instead_of_wrapping(env):
    r = Rig(env, perBurst=10)
    assert [r.arrive(at=0.1 * i) for i in range(9)] == [1, 2, 3, 4, 5, 6, 6, 6, 6]


def test_gap_blocks_notes_that_come_too_soon(env):
    r = Rig(env)
    assert r.arrive(at=0.0) == 1
    assert r.arrive(at=0.05) is None  # under 0.07 s since the last played note
    assert r.arrive(at=0.069) is None
    assert r.arrive(at=0.07) == 2  # exactly the gap is allowed
    # a skipped arrival does not move the clock: the gap counts from the last PLAYED note
    assert r.arrive(at=0.12) is None
    assert r.arrive(at=0.14) == 3


def test_per_burst_limit(env):
    r = Rig(env)
    notes = [r.arrive("b1", at=0.1 * i) for i in range(8)]
    assert notes == [1, 2, 3, 4, 5, 6, None, None]
    # another burst has its own budget (the arpeggio continues: no quiet moment yet)
    assert r.arrive("b2", at=0.9) == 6


def test_arpeggio_restarts_after_a_quiet_moment(env):
    r = Rig(env)
    assert [r.arrive(at=0.1 * i) for i in range(3)] == [1, 2, 3]
    assert r.arrive("b2", at=0.2 + 0.49) == 4  # under the 0.5 s reset
    assert r.arrive("b2", at=0.69 + 0.5) == 1  # reset seconds with no note: back to the bottom


def test_custom_settings(env):
    r = Rig(env, gap=0.2, perBurst=2, reset=1.0)
    assert r.arrive(at=0.0) == 1
    assert r.arrive(at=0.1) is None
    assert r.arrive(at=0.2) == 2
    assert r.arrive(at=0.4) is None  # perBurst reached
    assert r.arrive("b2", at=0.7) == 3
    assert r.arrive("b2", at=2.0) == 1


def test_nil_burst_key_is_silent(env):
    r = Rig(env)
    assert r.c.Arrive(r.c, None) is None


def test_burst_keys_are_opaque(env):
    r = Rig(env)
    assert r.arrive(7, at=0.0) == 1
    assert r.arrive(8.5, at=0.1) == 2
    assert r.arrive("x", at=0.2) == 3


def test_done_forgets_a_burst(env):
    r = Rig(env, perBurst=1)
    assert r.arrive("b1", at=0.0) == 1
    assert r.arrive("b1", at=0.1) is None
    assert r.open() == 1
    r.done("b1")
    assert r.open() == 0
    assert r.arrive("b1", at=0.2) == 2  # a reused key starts a fresh count


def test_done_on_an_unknown_key_is_harmless(env):
    r = Rig(env)
    r.done("never seen")
    assert r.open() == 0
