"""The crossfade style: orbs bloom at the plate, leave it along the exit direction u while fading out, and reappear
as copy B only a short distance (D px) from the bar, after a gap with nothing drawn. Timeline with math.random fixed at
0.5 (delay 0.04, leave start 0.075 after the 0.22 s bloom): A leaves over [0.335, 0.535] s, B flies from 0.655 s."""

import math

import pytest
from test_p2_unknown import LCG, ORIGIN, fire, live_recs, settle
from test_p2_wide import a_orbs, b_orbs
from test_v09 import make, pop_frames, pop_textures, restricted_plate, stream_textures

DELAY, BLOOM, LS, LEAVE, GAP = 0.04, 0.22, 0.075, 0.20, 0.12
LEAVE_START = DELAY + BLOOM + LS
B_START = LEAVE_START + LEAVE + GAP
H = 1080
D = min(160, max(80, 0.15 * H))


def dest_of(g):
    d = tuple(g.ns.Target.GetDestination(g.ns.Target))
    return d[0], d[1]


def unit_to_bar(g):
    dx, dy = dest_of(g)
    vx, vy = dx - ORIGIN[0], dy - ORIGIN[1]
    n = math.hypot(vx, vy)
    return vx / n, vy / n


def a_pos(g):
    (a,) = a_orbs(g)
    return a.points[1][4], a.points[1][5]


def shown_a(g):
    return [t for t in pop_textures(g) if t.shown]


def test_bloom_then_leave_along_u_fading_out(env):
    g = make(env)
    fire(g, "crossfade")
    (o,) = live_recs(g)
    ux, uy = unit_to_bar(g)
    g.stub.tick(DELAY + BLOOM - 0.001)  # bloom just over: A rests on the ring, fully visible
    (a,) = a_orbs(g)
    ring = a_pos(g)
    assert math.hypot(*ring) == pytest.approx(18, abs=0.1) and a.alpha == pytest.approx(1)
    g.stub.tick(0.001 + LS + 0.5 * LEAVE)  # half way through the leave: q = 0.5
    (a,) = a_orbs(g)
    k = 70 * 0.25  # q^2 ease-in
    assert a_pos(g) == pytest.approx((ring[0] + ux * k, ring[1] + uy * k), abs=0.6)
    assert a.alpha == pytest.approx(0.5, abs=0.02)
    assert a.width == pytest.approx(g.db.size * 2.0 * 0.9, rel=0.02)  # size 1 -> 0.8
    g.stub.tick(0.5 * LEAVE + 0.002)
    assert shown_a(g) == []  # alpha 0 by the end of the leave
    assert o.ls == pytest.approx(LS)


def test_copy_b_is_hidden_until_the_leave_plus_gap_is_over(env):
    g = make(env)
    fire(g, "crossfade")
    g.stub.tick(B_START - 0.003)
    assert stream_textures(g) == [] and shown_a(g) == []  # the implied-travel gap: nothing is drawn
    g.stub.tick(0.02)
    assert len(b_orbs(g)) == 1
    assert shown_a(g) == []


def test_copy_b_starts_d_short_of_the_bar_within_the_spread_disc(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "crossfade", n=40)
    dx, dy = dest_of(g)
    ux, uy = unit_to_bar(g)
    recs = live_recs(g)
    along = []
    for o in recs:
        vx, vy = o.x0 - dx, o.y0 - dy
        along.append(-(vx * ux + vy * uy))
        assert math.hypot(vx + ux * D, vy + uy * D) <= 14 + 1e-6  # inside the disc around dest - u * D
        assert (o.ux, o.uy) == pytest.approx((ux, uy))
    assert all(D - 14 - 1e-6 <= v <= D + 14 + 1e-6 for v in along)
    assert max(math.hypot(o.x0 - recs[0].x0, o.y0 - recs[0].y0) for o in recs) > 8  # actually spread
    settle(g)


def test_copy_b_duration_is_045_of_the_flight_time_with_narrow_jitter(env):
    g = make(env)
    fire(g, "crossfade")
    (o,) = live_recs(g)
    assert o.dur == pytest.approx(0.45 * g.db.flightTime)
    assert o.hold == pytest.approx(BLOOM + LS + LEAVE + GAP)
    settle(g)
    env.lua.execute(LCG)
    g2 = make(env, fixed_random=False)
    g2.db.flightTime = 1.0
    fire(g2, "crossfade", n=30)
    assert all(0.94 * 0.45 - 1e-9 <= o.dur <= 1.06 * 0.45 + 1e-9 for o in live_recs(g2))


def test_b_fades_in_over_80_ms_and_there_is_no_ab_crossfade(env):
    g = make(env)
    fire(g, "crossfade")
    (o,) = live_recs(g)
    assert (o.s0, o.s1) == (0, 0)
    g.stub.tick(B_START + 0.04)
    (b,) = b_orbs(g)
    assert b.alpha == pytest.approx(0.5, abs=0.05) and shown_a(g) == []
    g.stub.tick(0.06)
    assert b_orbs(g)[0].alpha == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("setting", ["wide", "off"])
def test_unknown_origin_does_not_apply_to_crossfade(env, setting):
    g = make(env)
    fire(g, "crossfade", setting)
    (o,) = live_recs(g)
    assert (o.sx, o.sy) == (0, 0) and g.orbs.lastUnknown is None
    assert math.hypot(o.ax - ORIGIN[0], o.ay - ORIGIN[1]) == pytest.approx(18)  # A is plate-exact
    settle(g)


def test_without_a_plate_it_is_a_plain_stream_from_p_hat(env):
    g = make(env)
    g.db.unknownOrigin = "off"
    opts = g.env.lua.table_from(dict(n=3, x=300, y=300, kind="kill", style="crossfade"))
    assert g.orbs.Burst(g.orbs, opts) == "stream"
    assert pop_frames(g) == []
    settle(g)


def test_idle_afterwards_and_pools_are_back(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False, trail=True)
    fire(g, "crossfade", n=12)
    settle(g)
    free, created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert g.orbs.Info(g.orbs)[1] == 0 and free == created and alive == 0 and xf == 0
    assert g.orbs.driver.scripts.OnUpdate is None
    assert g.stub.restrictedHits == 0
