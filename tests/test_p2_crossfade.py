"""The crossfade style: orbs bloom at the plate, leave it along the exit direction u while fading out, and reappear
as copy B only a short distance (D px) from the bar, after a gap with nothing drawn. Timeline with math.random fixed at
0.5 (delay 0.02, leave start 0.075 after the 0.24 s pop): A leaves over [0.335, 0.595] s, B flies from 0.695 s."""

import math

import pytest
from test_p2_styles import a_orbs, b_orbs
from test_p2_unknown import LCG, ORIGIN, fire, live_recs, pos, settle
from test_v09 import make, pop_frames, pop_textures, restricted_plate, stream_textures

DELAY, BLOOM, LS, LEAVE, GAP = 0.02, 0.24, 0.075, 0.26, 0.10
LEAVE_START = DELAY + BLOOM + LS
B_START = LEAVE_START + LEAVE + GAP
H = 1080
D = min(320, max(80, 0.30 * H))  # 320 on a long trip; 0.60 * L caps it for a mob near the bar


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
    assert a.alpha == pytest.approx(1)
    assert math.hypot(o.ringX - ORIGIN[0], o.ringY - ORIGIN[1]) == pytest.approx(math.hypot(*ring), abs=1e-3)
    assert 24 - 8 <= math.hypot(*ring) <= 36 + 8  # radius 24..36 plus up to 8 px of upward drift
    g.stub.tick(0.001 + LS + 0.5 * LEAVE)  # half way through the leave: q = 0.5
    (a,) = a_orbs(g)
    k = 180 * 0.25  # q^2 ease-in
    assert a_pos(g) == pytest.approx((ring[0] + ux * k, ring[1] + uy * k), abs=0.6)
    assert a.alpha == pytest.approx(0.75, abs=0.02)  # 1 - q^2
    assert a.width == pytest.approx(g.db.size * 2.0 * 0.9, rel=0.02)  # size 1 -> 0.8
    g.stub.tick(0.5 * LEAVE + 0.002)
    assert shown_a(g) == []  # alpha 0 by the end of the leave
    assert o.leaveStart == pytest.approx(LS)


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


def test_copy_b_duration_is_040_of_the_flight_time_with_narrow_jitter(env):
    g = make(env)
    fire(g, "crossfade")
    (o,) = live_recs(g)
    assert o.dur == pytest.approx(0.40 * g.db.flightTime)
    assert o.hold == pytest.approx(BLOOM + LS + LEAVE + GAP)
    settle(g)
    env.lua.execute(LCG)
    g2 = make(env, fixed_random=False)
    g2.db.flightTime = 1.0
    fire(g2, "crossfade", n=30)
    assert all(0.94 * 0.40 - 1e-9 <= o.dur <= 1.06 * 0.40 + 1e-9 for o in live_recs(g2))


def test_b_fades_in_over_80_ms_and_there_is_no_ab_crossfade(env):
    g = make(env)
    fire(g, "crossfade")
    (o,) = live_recs(g)
    assert o.s0 is None and o.s1 is None  # the A -> B window went with the wide burst (schema 6)
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
    assert g.orbs.lastUnknown is None
    assert 16 <= math.hypot(o.ringX - ORIGIN[0], o.ringY - ORIGIN[1]) <= 36 + 8  # A is plate-exact (ring + drift)
    settle(g)


def test_without_a_plate_copy_a_blooms_at_p_hat_on_a_screen_anchored_group(env):
    """Test burst / unlocated kill: the group hangs off UIParent at P-hat instead of off a nameplate."""
    g = make(env)
    g.db.unknownOrigin = "off"
    opts = g.env.lua.table_from(dict(n=3, x=300, y=300, ex=700, ey=500, kind="kill", style="crossfade"))
    assert g.orbs.Burst(g.orbs, opts) == "crossfade"
    (frame,) = pop_frames(g)
    assert len(frame.points) == 1 and frame.points[1][1] == "CENTER" and frame.points[1][3] == "BOTTOMLEFT"
    assert (frame.points[1][4], frame.points[1][5]) == (700, 500) and frame.shown
    assert g.orbs.PoolInfo(g.orbs)[3] == 1
    g.stub.tick(0.1)
    shown = [t for t in pop_textures(g) if t.shown]
    assert len(shown) == 3 * 3  # copy A: three textures per orb
    xs = [t.points[1][4] for t in shown]
    assert all(abs(x) < 80 for x in xs)  # offsets relative to the frame, i.e. around P-hat
    assert all(t.points[1][2] is frame or g.env.lua.eval("rawequal")(t.points[1][2], frame) for t in shown)
    g.stub.tick(0.2 + 0.5)  # B appears after the leave and the gap
    assert b_orbs(g)
    settle(g)
    free, created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert alive == 0 and xf == 0 and free == created  # the group went back to the pool
    assert g.stub.restrictedHits == 0


def test_idle_afterwards_and_pools_are_back(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False, trail=True)
    fire(g, "crossfade", n=12)
    settle(g)
    free, created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert g.orbs.Info(g.orbs)[1] == 0 and free == created and alive == 0 and xf == 0
    assert g.orbs.driver.scripts.OnUpdate is None
    assert g.stub.restrictedHits == 0


def test_b_first_control_point_lies_ahead_along_u_within_the_jitter_band(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "crossfade", n=40)
    dx, dy = dest_of(g)
    ux, uy = unit_to_bar(g)
    seen = []
    for o in live_recs(g):
        d0 = math.hypot(dx - o.x0, dy - o.y0)
        vx, vy = o.control1X - o.x0, o.control1Y - o.y0
        along, side = vx * ux + vy * uy, -vx * uy + vy * ux
        assert along == pytest.approx(0.4 * d0, abs=1e-6)  # no lift, no wandering: 0.4 * dist straight ahead
        assert abs(side) <= 0.1 * d0 + 1e-6
        seen.append(side)
    assert max(seen) > 0 > min(seen)  # jittered to both sides
    settle(g)


def test_leaving_alpha_follows_one_minus_q_squared(env):
    g = make(env)
    fire(g, "crossfade")
    g.stub.tick(DELAY + BLOOM + LS + 0.001)
    g.stub.tick(0.25 * LEAVE - 0.001)
    assert a_orbs(g)[0].alpha == pytest.approx(1 - 0.25**2, abs=0.01)
    g.stub.tick(0.5 * LEAVE)
    assert a_orbs(g)[0].alpha == pytest.approx(1 - 0.75**2, abs=0.01)
    settle(g)


def test_d_respects_060_of_the_distance_for_a_mob_near_the_bar(env):
    g = make(env)
    dx, dy = dest_of(g)
    fire(g, "crossfade", ex=dx, ey=dy - 200, x=dx, y=dy - 200)  # L = 200: D = min(324, 120) = 120
    (o,) = live_recs(g)
    assert abs(math.hypot(o.x0 - dx, o.y0 - dy) - 120) <= 14 + 1e-6
    settle(g)
    fire(g, "crossfade", ex=dx, ey=dy - 100, x=dx, y=dy - 100)  # L = 100: leave 60, D = max(50, 100 - 60) = 50
    (o,) = live_recs(g)
    assert abs(math.hypot(o.x0 - dx, o.y0 - dy) - 50) <= 14 + 1e-6
    settle(g)


@pytest.mark.parametrize("length", [1000, 300, 150, 100])
def test_b_is_always_ahead_of_where_a_vanishes_and_a_never_passes_the_bar(env, length):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    dx, dy = dest_of(g)
    fire(g, "crossfade", n=30, ex=dx, ey=dy - length, x=dx, y=dy - length)
    ld = max(60, min(180, 0.40 * length))
    d_nominal = max(50, min(D, length - ld))
    for o in live_recs(g):
        assert o.leaveDist == pytest.approx(ld)
        # nominal numbers along u from P-hat (ring offset and B's spread aside): A vanishes at ld, B at L - D
        b_centre = (o.y0 - (dy - length)) * (o.uy)
        assert abs(b_centre - (length - d_nominal)) <= 14 + 1e-6
        assert ld <= length - d_nominal or length - d_nominal == length - 50  # only the D floor of 50 may invert it
        assert ld - (length - d_nominal) <= 10 + 1e-6  # ... and then by at most 10 px (L = 100)
        assert ld < length  # A never flies past the bar
    settle(g)


def test_far_mob_keeps_the_full_leave_and_the_old_d(env):
    g = make(env)
    dx, dy = dest_of(g)
    fire(g, "crossfade", ex=dx, ey=dy - 1000, x=dx, y=dy - 1000)
    (o,) = live_recs(g)
    assert o.leaveDist == 180
    assert abs(math.hypot(o.x0 - dx, o.y0 - dy) - D) <= 14 + 1e-6
    settle(g)


def test_b_trail_ghosts_sit_behind_it_along_minus_u_during_the_fade_in(env):
    g = make(env, trail=True)
    fire(g, "crossfade")
    ux, uy = unit_to_bar(g)
    g.stub.tick(B_START + 0.02)  # p = 0.05 of the flight, inside the 0.08 s fade-in (p < 0.2)
    orb, g1, g2, g3 = b_orbs(g)
    bx, by = pos(orb)
    gap = g.ns.OrbShapes.k.ghostGapK * orb.width  # drawn diameter x ghostGapK, from the body's own width
    assert pos(g1) == pytest.approx((bx - ux * gap, by - uy * gap), abs=1e-6)
    assert pos(g2) == pytest.approx((bx - ux * 2 * gap, by - uy * 2 * gap), abs=1e-6)
    assert pos(g3) == pytest.approx((bx - ux * 3 * gap, by - uy * 3 * gap), abs=1e-6)
    g.stub.tick(0.3)  # fade-in over: the ghosts follow the path lag again (just behind on the path, not 1 / 2 gaps along -u)
    orb, g1, g2, g3 = b_orbs(g)
    assert math.hypot(*(a - b for a, b in zip(pos(orb), pos(g1)))) < 12
    settle(g)


@pytest.mark.parametrize("style", ["popstream", "wide"])
def test_other_styles_keep_their_own_profile(env, style):
    g = make(env)
    fire(g, style)
    (o,) = live_recs(g)
    assert o.profile is None or not o.profile.leave
    settle(g)


def test_pop_ring_radius_birth_window_and_leave_distance(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "crossfade", n=40)
    ux, uy = unit_to_bar(g)
    recs = live_recs(g)
    rad = [math.hypot(o.ringX - ORIGIN[0], o.ringY - ORIGIN[1]) for o in recs]
    assert min(rad) >= 24 - 8 - 1e-6 and max(rad) <= 36 + 8 + 1e-6 and max(rad) - min(rad) > 8  # 24..36, drift <= 8
    assert all(0 <= o.delay <= 0.04 + 1e-9 for o in recs)  # born within 0.04 s
    assert all(o.hold == pytest.approx(BLOOM + o.leaveStart + LEAVE + GAP) for o in recs)
    # leave distance 180 px: at q = 0.5 an orb is 180 * 0.25 px along u from its ring point
    o = max(recs, key=lambda r: r.leaveStart)
    t = o.delay + BLOOM + o.leaveStart + 0.5 * LEAVE
    g.stub.tick(t)
    shown = [t_ for t_ in a_orbs(g)]
    assert shown  # still leaving at q = 0.5
    px = [pos_ for pos_ in (a_pos_of(x) for x in shown)]
    assert any(
        abs((p[0] - (o.ringX - ORIGIN[0])) * ux + (p[1] - (o.ringY - ORIGIN[1])) * uy - 180 * 0.25) < 1.0 for p in px
    )  # 180 * q^2 at q = 0.5
    settle(g)


def a_pos_of(tex):
    return tex.points[1][4], tex.points[1][5]
