"""Chime: which of the six notes to play as an orb arrives (pure logic, fake clock, scripted random)."""


class Rig:
    """A Chime with a fake clock and a scripted random source (`picks` cycles; each value is returned as-is)."""

    def __init__(self, env, picks=(1,), **cfg):
        env.load_addon()
        self.t = 0.0
        self.calls = []
        self.picks = list(picks)
        cfg["now"] = lambda: self.t
        cfg["rand"] = self._rand
        self.c = env.ns.Chime.New(env.lua.table_from(cfg))

    def _rand(self, n):
        self.calls.append(n)
        return self.picks[(len(self.calls) - 1) % len(self.picks)]

    def arrive(self, key="b1", at=None):
        if at is not None:
            self.t = at
        return self.c.Arrive(self.c, key)

    def done(self, key):
        self.c.Done(self.c, key)

    def open(self):
        return self.c.Open(self.c)


def test_first_note_is_a_draw_from_all_six(env):
    r = Rig(env, picks=[4])
    assert r.arrive(at=0.0) == 4
    assert r.calls == [6]


def test_next_note_never_equals_the_previous(env):
    # rand(5) picks among the other notes: values below the previous note are kept, the rest shift up by one
    r = Rig(env, picks=[3, 1, 2, 3, 4, 5, 5, 5], perBurst=99)
    notes = [r.arrive(at=0.1 * i) for i in range(8)]
    assert all(1 <= n <= 6 for n in notes)
    assert all(a != b for a, b in zip(notes, notes[1:]))
    assert r.calls == [6] + [5] * 7


def test_exhaustive_stub_draws_never_repeat_a_note(env):
    for first in range(1, 7):
        for second in range(1, 6):
            r = Rig(env, picks=[first, second])
            a, b = r.arrive(at=0.0), r.arrive(at=0.1)
            assert a == first and 1 <= b <= 6 and a != b


def test_real_random_wobbles_without_repeats_and_uses_every_note(env):
    env.load_addon()
    env.lua.execute("math.randomseed(7)")
    t = [0.0]
    c = env.ns.Chime.New(env.lua.table_from({"now": lambda: t[0], "perBurst": 10**6}))
    notes = []
    for i in range(600):
        t[0] = 0.1 * i
        notes.append(c.Arrive(c, "b"))
    assert all(a != b for a, b in zip(notes, notes[1:]))
    assert set(notes) == {1, 2, 3, 4, 5, 6}


def test_bad_random_values_are_clamped(env):
    r = Rig(env, picks=[0, 99, 0.5, -3], perBurst=99)
    notes = [r.arrive(at=0.1 * i) for i in range(4)]
    assert all(isinstance(n, (int, float)) and 1 <= n <= 6 for n in notes)
    assert all(a != b for a, b in zip(notes, notes[1:]))


def test_gap_blocks_notes_that_come_too_soon(env):
    r = Rig(env)
    assert r.arrive(at=0.0) is not None
    assert r.arrive(at=0.05) is None  # under 0.07 s since the last played note
    assert r.arrive(at=0.069) is None
    assert r.arrive(at=0.07) is not None  # exactly the gap is allowed
    # a skipped arrival does not move the clock: the gap counts from the last PLAYED note
    assert r.arrive(at=0.12) is None
    assert r.arrive(at=0.14) is not None
    assert len(r.calls) == 3  # skipped arrivals do not draw


def test_per_burst_limit(env):
    r = Rig(env)
    notes = [r.arrive("b1", at=0.1 * i) for i in range(8)]
    assert all(n is not None for n in notes[:6]) and notes[6:] == [None, None]
    # another burst has its own budget
    assert r.arrive("b2", at=0.9) is not None


def test_custom_settings(env):
    r = Rig(env, gap=0.2, perBurst=2)
    assert r.arrive(at=0.0) is not None
    assert r.arrive(at=0.1) is None
    assert r.arrive(at=0.2) is not None
    assert r.arrive(at=0.4) is None  # perBurst reached
    assert r.arrive("b2", at=0.7) is not None


def test_nil_burst_key_is_silent(env):
    r = Rig(env)
    assert r.c.Arrive(r.c, None) is None


def test_burst_keys_are_opaque(env):
    r = Rig(env)
    assert r.arrive(7, at=0.0) is not None
    assert r.arrive(8.5, at=0.1) is not None
    assert r.arrive("x", at=0.2) is not None


def test_done_forgets_a_burst(env):
    r = Rig(env, perBurst=1)
    assert r.arrive("b1", at=0.0) is not None
    assert r.arrive("b1", at=0.1) is None
    assert r.open() == 1
    r.done("b1")
    assert r.open() == 0
    assert r.arrive("b1", at=0.2) is not None  # a reused key starts a fresh count


def test_done_on_an_unknown_key_is_harmless(env):
    r = Rig(env)
    r.done("never seen")
    assert r.open() == 0
