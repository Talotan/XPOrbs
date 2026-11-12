"""KillMatcher: death / chat / delta pairing state machine, driven by a fake clock."""

import pytest
from conftest import lua_list


class Rig:
    def __init__(self, env):
        env.load_addon()
        self.env = env
        self.t = 0.0
        self.m = env.ns.KillMatcher.New(env.lua.table_from({"now": lambda: self.t}))

    def tbl(self, **kw):
        return self.env.lua.table_from({k: v for k, v in kw.items() if v is not None})

    def death(self, x=10, y=20, tier=1, name=None):
        self.m.AddDeath(self.m, self.tbl(x=x, y=y, tier=tier, name=name))

    def chat(self, amount, mob=None, rested=None):
        self.m.AddKillXP(self.m, self.tbl(amount=amount, mob=mob, rested=rested))

    def delta(self, amount):
        self.m.AddDelta(self.m, amount)

    def at(self, t):
        self.t = t

    def poll(self):
        return lua_list(self.m.Poll(self.m))

    def stats(self):
        return self.m.Stats(self.m)


@pytest.fixture
def rig(env):
    return Rig(env)


def test_death_then_chat_tier1_at_death_position(rig):
    rig.death(x=100, y=200, tier=1)
    rig.at(0.1)
    rig.chat(90, rested=40)
    (b,) = rig.poll()
    assert (b.x, b.y, b.amount, b.rested, b.tier, b.kind) == (
        100,
        200,
        90,
        40,
        1,
        "kill",
    )
    assert rig.stats().tier1 == 1


def test_tier2_death_keeps_its_tier(rig):
    rig.death(tier=2)
    rig.chat(50)
    (b,) = rig.poll()
    assert b.tier == 2 and rig.stats().tier2 == 1


def test_chat_then_death_within_wait_pairs(rig):
    rig.chat(90)
    assert rig.poll() == []
    rig.at(0.3)
    rig.death(x=5, y=6)
    (b,) = rig.poll()
    assert (b.x, b.y, b.tier) == (5, 6, 1)


def test_chat_without_death_goes_tier4_after_wait(rig):
    rig.chat(90)
    rig.at(0.49)
    assert rig.poll() == []
    rig.at(0.5)
    (b,) = rig.poll()
    assert (
        b.x is None
        and b.y is None
        and b.tier == 4
        and b.kind == "kill"
        and b.amount == 90
    )
    assert rig.stats().tier4 == 1


def test_two_deaths_two_chats_paired_by_name(rig):
    rig.death(x=1, y=1, name="Kobold")
    rig.death(x=2, y=2, name="Defias Pillager")
    rig.chat(10, mob="Defias Pillager")  # arrives out of death order
    rig.chat(20, mob="Kobold")
    bursts = {b.amount: (b.x, b.y) for b in rig.poll()}
    assert bursts == {10: (2, 2), 20: (1, 1)}


def test_unreadable_names_fall_back_to_fifo(rig):
    rig.death(x=1, y=1)
    rig.at(0.1)
    rig.death(x=2, y=2)
    rig.chat(10)
    rig.chat(20)
    bursts = rig.poll()
    assert [(b.amount, b.x) for b in bursts] == [(10, 1), (20, 2)]


def test_name_mismatch_still_pairs_oldest(rig):
    rig.death(x=1, y=1, name="Wolf")
    rig.chat(10, mob="Kobold")
    (b,) = rig.poll()
    assert b.x == 1


def test_delta_with_matching_chat_is_one_burst(rig):
    rig.death()
    rig.chat(90)
    rig.delta(90)
    assert len(rig.poll()) == 1
    rig.at(2.0)
    assert rig.poll() == []
    assert rig.stats().other == 0


def test_delta_before_chat_is_claimed_not_other(rig):
    rig.delta(90)
    rig.at(0.2)
    rig.chat(90)
    rig.death()
    (b,) = rig.poll()
    assert b.kind == "kill"
    rig.at(1.0)
    assert rig.poll() == []


def test_delta_after_emitted_kill_is_claimed(rig):
    rig.death()
    rig.chat(90)
    assert len(rig.poll()) == 1
    rig.at(0.2)
    rig.delta(90)
    rig.at(0.3)
    assert rig.poll() == []
    rig.at(1.0)
    assert rig.poll() == []
    assert rig.stats().other == 0


def test_equal_amount_deltas_claimed_fifo_one_each(rig):
    rig.death()
    rig.death()
    rig.chat(90)
    rig.chat(90)
    rig.delta(90)
    rig.delta(90)
    assert len(rig.poll()) == 2
    rig.at(1.0)
    assert rig.poll() == []


def test_lone_delta_is_other_after_wait(rig):
    rig.delta(250)
    rig.at(0.39)
    assert rig.poll() == []
    rig.at(0.4)
    (b,) = rig.poll()
    assert b.kind == "other" and b.amount == 250 and b.x is None and b.rested is None
    assert rig.stats().other == 1


def test_unmatched_delta_amount_does_not_steal_kill(rig):
    rig.death()
    rig.chat(90)
    rig.delta(77)  # a different gain, e.g. quest
    rig.at(0.4)
    bursts = rig.poll()
    assert sorted(b.kind for b in bursts) == ["kill", "other"]


def test_death_without_xp_dropped_after_ttl(rig):
    rig.death()
    rig.at(1.49)
    assert rig.poll() == []
    assert rig.stats().dropped == 0
    rig.at(1.5)
    assert rig.poll() == []
    assert rig.stats().dropped == 1


def test_expired_death_not_used_by_late_chat(rig):
    rig.death(x=9, y=9)
    rig.at(2.0)
    rig.poll()
    rig.chat(10)
    rig.at(2.5)
    (b,) = rig.poll()
    assert b.tier == 4 and b.x is None


def test_rested_carried_through_burst(rig):
    rig.chat(90, rested=45)
    rig.at(0.5)
    (b,) = rig.poll()
    assert b.rested == 45
    rig.chat(30)
    rig.at(1.0)
    (b,) = rig.poll()
    assert b.rested is None


def test_pending_goes_idle(rig):
    assert rig.m.Pending(rig.m) == 0
    rig.death()
    rig.chat(5)
    assert rig.m.Pending(rig.m) > 0
    rig.poll()
    rig.at(5.0)
    rig.poll()
    assert rig.m.Pending(rig.m) == 0
