"""Secret kill-XP chat lines (instances): a marker pairs the oldest death with an unclaimed XP delta."""

import pytest
from test_killmatcher import Rig
from test_plates_stub import Game


@pytest.fixture
def rig(env):
    r = Rig(env)
    r.secret = lambda: r.m.AddSecretChat(r.m)
    return r


def assert_secret_kill(b, guid, tier=1, amount=50):
    assert (b.kind, b.guid, b.tier, b.amount, b.secret) == ("kill", guid, tier, amount, True)
    assert b.rested is None


def test_marker_death_delta_makes_one_kill(rig):
    rig.death("d1", tier=2)
    rig.secret()
    rig.delta(50)
    (b,) = rig.poll()
    assert_secret_kill(b, "d1", tier=2)
    s = rig.stats()
    assert s.secret == 1 and s.tier2 == 1 and s.other == 0 and s.dropped == 0
    assert rig.m.Pending(rig.m) == 0
    rig.at(5)
    assert rig.poll() == []


def test_delta_before_marker(rig):
    rig.death("d1")
    rig.delta(50)
    rig.at(0.1)
    rig.secret()
    (b,) = rig.poll()
    assert_secret_kill(b, "d1")


def test_death_after_delta_within_windows(rig):
    rig.secret()
    rig.delta(50)
    rig.at(0.2)
    assert rig.poll() == []
    rig.death("late")
    (b,) = rig.poll()
    assert_secret_kill(b, "late")
    assert rig.stats().other == 0


def test_no_marker_stays_other_and_dropped(rig):
    rig.death("d1")
    rig.delta(50)
    assert rig.poll() == []
    rig.at(0.5)
    (b,) = rig.poll()
    assert b.kind == "other" and b.amount == 50
    rig.at(1.6)
    rig.poll()
    s = rig.stats()
    assert s.other == 1 and s.dropped == 1 and s.secret == 0


def test_expired_marker_does_not_pair(rig):
    rig.secret()
    rig.at(1.1)
    rig.death("d1")
    rig.delta(50)
    assert rig.poll() == []
    assert rig.m.Pending(rig.m) == 2  # marker gone, death and delta remain
    rig.at(1.6)
    (b,) = rig.poll()
    assert b.kind == "other"
    assert rig.stats().secret == 0


def test_two_kills_pair_fifo(rig):
    rig.death("a")
    rig.at(0.05)
    rig.death("b")
    rig.secret()
    rig.secret()
    rig.delta(30)
    rig.delta(40)
    first, second = rig.poll()
    assert_secret_kill(first, "a", amount=30)
    assert_secret_kill(second, "b", amount=40)
    assert rig.stats().secret == 2


def test_readable_kill_claims_its_delta_despite_a_marker(rig):
    rig.death("d1")
    rig.chat(50)
    rig.secret()
    rig.delta(50)
    (b,) = rig.poll()
    assert b.guid == "d1" and b.secret is None and b.kind == "kill"
    assert rig.stats().secret == 0
    assert rig.m.Pending(rig.m) == 1  # the marker waits for its own kill
    rig.at(1.2)
    rig.poll()
    assert rig.m.Pending(rig.m) == 0


def test_pending_counts_markers(rig):
    assert rig.m.Pending(rig.m) == 0
    rig.secret()
    assert rig.m.Pending(rig.m) == 1
    rig.at(1.0)
    rig.poll()
    assert rig.m.Pending(rig.m) == 0


def test_end_to_end_secret_chat_is_a_kill_not_other(env):
    g = Game(env)
    g.plate(guid="G1", name="Boar", cx=300, cy=200)
    g.tick(0.05)
    env.ns.fire("UNIT_DIED", "G1")
    g.chat(g.stub.SECRET)
    g.stub.setXP(50)
    g.tick(0.1)
    assert g.has_log("BURST tier=1 kind=kill amount=50")
    assert not g.has_log("kind=other")
    assert g.has_log("SECRETPAIR tier=1 amount=50")
    assert g.has_log("secret=1")
    g.tick(2.0, 3)
    assert g.stats()["other"] == 0 and g.stats()["dropped"] == 0
