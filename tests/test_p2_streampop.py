"""Popstream (Direct), render style "streampop" (db.style "popstream" + popMode "direct" since schema 6; "streampop" stays
an alias): screen space only (never a plate frame). Every orb is born at the start point, pops out to a ring, then
launches the moment its own bloom ends (nearest to the bar first) into the normal stream path from its ring point.
The other styles must keep behaving as before."""

import math

import pytest
from test_m5 import build, ctl, show
from test_migration import load
from test_p2_unknown import LCG, ORIGIN, RX, RY, fire, live_recs, settle
from test_v09 import chat_lines, make, pop_frames, restricted_plate, stream_textures

BORN, BLOOM_MIN, BLOOM_SPAN, RESTED_PAUSE, EASE_OUT, BSIZE = 0.03, 0.20, 0.06, 0.06, 0.5, 1.55
RING_MIN, RING_MAX, WIDTH_CAP = 25, 46, 64
MAX_HOLD = 0.30  # every non-rested orb has left within 0.30 s of the kill, birth delay included


def dest_of(g):
    d = tuple(g.ns.Target.GetDestination(g.ns.Target))
    return d[0], d[1]


def orb_textures(g):
    return [
        t
        for t in stream_textures(g)
        if t.calls["SetDrawLayer"] and t.calls["SetDrawLayer"][2] == 0
    ]


def pos(t):
    return t.points[1][4], t.points[1][5]


# ---------------------------------------------------------------- selection


@pytest.mark.parametrize("cmd", ["style streampop", "style popstream direct", "style direct"])
def test_style_command_persists_prints_and_the_panel_radio_checks(env, cmd):
    m5 = build(env)
    m5.slash(cmd)
    assert (m5.db.style, m5.db.popMode) == ("popstream", "direct")
    assert m5.say()[-1].endswith("kill style: Popstream (Direct)")
    show(m5)
    assert ctl(m5, "style_popstream").checked and ctl(m5, "popMode_direct").checked
    assert not ctl(m5, "popMode_nameplate").checked and not ctl(m5, "style_stream").checked
    m5.stub.click(ctl(m5, "style_stream"))
    assert m5.db.style == "stream" and m5.db.popMode == "direct" and not ctl(m5, "style_popstream").checked
    m5.stub.click(ctl(m5, "style_popstream"))
    assert (m5.db.style, m5.db.popMode) == ("popstream", "direct") and ctl(m5, "popMode_direct").checked


def test_help_and_the_bogus_style_message_list_it(env):
    m5 = build(env)
    m5.slash("style bogus")
    assert "use popstream [nameplate|direct], crossfade or stream" in m5.say()[-1]
    m5.slash("help")
    assert any("popstream [nameplate|direct] | crossfade | stream" in line for line in m5.say())
    assert any("Popstream (Direct): a pop at the estimated mob position" in line for line in m5.say())


def test_test_token_fires_a_streampop_burst_with_no_plate_frame(env):
    g = make(env)
    g.stub.plates["target"] = restricted_plate(g)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "isTarget": True})
    g.stub.setTargetFrame(250, 900, True)
    g.slash("test 5 streampop")
    assert chat_lines(g)[-1].endswith("pop=no stream=estimate style=popstream/direct")
    g.stub.tick(0.1)
    assert pop_frames(g) == [] and g.stub.restrictedHits == 0
    g.stub.tick(3)
    g.slash("test 5 direct")
    assert chat_lines(g)[-1].endswith("pop=no stream=estimate style=popstream/direct")
    g.stub.tick(0.1)
    assert pop_frames(g) == [] and g.stub.restrictedHits == 0


def test_initdb_maps_streampop_to_popstream_direct(env):
    db = load(env, {"version": 5, "style": "streampop"})
    assert (db.style, db.popMode, db.version) == ("popstream", "direct", 6)


def test_a_passed_plate_is_ignored_entirely(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    opts = dict(
        plate=plate,
        n=6,
        x=ORIGIN[0],
        y=ORIGIN[1],
        ex=ORIGIN[0],
        ey=ORIGIN[1],
        kind="kill",
        style="streampop",
    )
    assert g.orbs.Burst(g.orbs, g.env.lua.table_from(opts)) == "streampop"
    g.stub.tick(0.1)
    assert pop_frames(g) == [] and g.stub.restrictedHits == 0
    settle(g)
    assert g.stub.restrictedHits == 0


# ---------------------------------------------------------------- the pop


def test_births_within_30_ms_at_the_start_point_and_ring_radius(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", n=40)
    recs = live_recs(g)
    assert len(recs) == 40
    assert all(0 <= o.delay <= BORN + 1e-9 for o in recs)
    assert all(
        (o.px, o.py) == pytest.approx(ORIGIN) for o in recs
    )  # one centre without the unknown spread
    rad = [math.hypot(o.ringX - o.px, o.ringY - o.py) for o in recs]
    assert min(rad) >= RING_MIN - 1e-6 and max(rad) <= RING_MAX + 1e-6 and max(rad) - min(rad) > 10
    g.stub.tick(
        0.001
    )  # only the earliest-born orbs are alive, and they have not left the start point yet
    shown = orb_textures(g)
    assert len(shown) >= 1
    assert all(
        math.hypot(pos(t)[0] - ORIGIN[0], pos(t)[1] - ORIGIN[1]) < 3 for t in shown
    )
    g.stub.tick(BORN)  # everyone has been born
    assert len(orb_textures(g)) == 40
    g.stub.tick(0.1)  # t = 0.13: the pop is forming and nobody has launched yet (the first leaves at 0.20 + delay)
    shown = orb_textures(g)
    assert all(
        8 <= math.hypot(pos(t)[0] - ORIGIN[0], pos(t)[1] - ORIGIN[1]) <= RING_MAX + 1
        for t in shown
    )
    settle(g)


def test_the_pop_size_eases_from_the_boost_to_1_and_fades_in(env):
    g = make(env)
    fire(g, "streampop")
    g.stub.tick(0.5 * BORN + 0.025)  # t = 0.025: alpha 0.5 of the 0.05 s fade-in
    (orb,) = orb_textures(g)
    assert orb.alpha == pytest.approx(0.5, abs=0.02)
    (rec,) = live_recs(g)
    g.stub.tick(rec.delay + rec.bloom - 0.001 - 0.025 - 0.5 * BORN)  # just before the bloom (and so the launch) ends
    (orb,) = orb_textures(g)
    assert orb.alpha == pytest.approx(1) and orb.width == pytest.approx(g.db.size * 2.0, rel=0.02)
    settle(g)


def test_each_orb_launches_when_its_own_bloom_ends_nearest_to_the_bar_first(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", n=12)
    dx, dy = dest_of(g)
    recs = live_recs(g)
    ordered = sorted(recs, key=lambda o: o.hold)
    dist = [math.hypot(dx - o.ringX, dy - o.ringY) for o in ordered]
    assert dist == sorted(dist)  # nearest ring point has the shortest bloom, so it launches first
    assert all(o.hold == pytest.approx(o.bloom) for o in recs)  # no hold after the bloom
    holds = [o.hold for o in ordered]
    assert holds[0] == pytest.approx(BLOOM_MIN) and holds[-1] - holds[0] == pytest.approx(BLOOM_SPAN)
    assert len(set(round(h, 6) for h in holds)) == 12  # staggered, not one volley
    settle(g)


def test_no_orb_lingers_before_its_launch(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", n=30, nPurple=10)
    recs = live_recs(g)
    assert all(o.delay + o.hold <= MAX_HOLD + (RESTED_PAUSE if o.rested else 0) + 1e-9 for o in recs)
    assert all(o.delay + o.hold <= MAX_HOLD for o in recs if not o.rested)
    assert all(o.hold >= BLOOM_MIN - 1e-9 for o in recs)
    assert any(o.rested for o in recs)
    settle(g)


def test_the_launch_starts_exactly_at_the_bloom_end_point_and_still_moving(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", n=12, nPurple=4)
    for o in live_recs(g):
        assert (o.x0, o.y0) == pytest.approx((o.ringX, o.ringY), abs=1e-6)  # the bloom ended on the ring point
        # the partial ease-out leaves (1 - EASE_OUT) of the linear speed at the end: it is not parked
        speed_end = (1 - EASE_OUT) * math.hypot(o.ringX - o.px, o.ringY - o.py) / o.bloom
        assert speed_end > 30  # px/s
        rx, ry = o.ringX - o.px, o.ringY - o.py
        assert (o.control1X - o.x0) * rx + (o.control1Y - o.y0) * ry > 0  # the flight carries on outward
    settle(g)


def test_rested_orbs_bloom_longer_by_the_rested_delay(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", n=6, nPurple=3)
    recs = live_recs(g)
    assert max(o.hold for o in recs if o.rested) > max(o.hold for o in recs if not o.rested)
    for o in recs:
        base = o.bloom - (RESTED_PAUSE if o.rested else 0)
        assert BLOOM_MIN - 1e-9 <= base <= BLOOM_MIN + BLOOM_SPAN + 1e-9
    settle(g)


def test_no_jump_at_the_launch(env):
    g = make(env)
    fire(g, "streampop")
    (o,) = live_recs(g)
    t_launch = o.delay + o.hold
    g.stub.tick(t_launch - 0.002)
    (orb,) = orb_textures(g)
    before = pos(orb)
    assert before == pytest.approx(
        (o.x0, o.y0), abs=0.6
    )  # the bloom ended exactly where the flight starts
    g.stub.tick(0.004)
    (orb,) = orb_textures(g)
    assert math.hypot(pos(orb)[0] - before[0], pos(orb)[1] - before[1]) < 3
    settle(g)


def test_nothing_flies_back_through_the_centre(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", n=40)
    for o in live_recs(g):
        rx, ry = o.ringX - o.px, o.ringY - o.py  # outward, away from the ring centre
        assert (o.control1X - o.x0) * rx + (o.control1Y - o.y0) * ry > 0
    settle(g)


# ---------------------------------------------------------------- unknown origin


def test_unknown_origin_wide_keeps_the_pop_fixed_and_widens_the_ring_horizontally(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", "wide", n=30, est="default")
    recs = live_recs(g)
    # the pop stays at the estimate (no jumping about the ellipse); only the ring's x radius is stretched by 1.6
    assert all((o.px, o.py) == pytest.approx(ORIGIN) for o in recs)
    for o in recs:
        width = o.ringX - o.px
        radius = math.hypot(width / 1.6, o.ringY - o.py)
        assert RING_MIN - 1e-6 <= radius <= RING_MAX + 1e-6 or abs(width) == pytest.approx(WIDTH_CAP)  # capped
        assert abs(width) <= max(WIDTH_CAP, RING_MAX) + 1e-6
    assert max(abs(o.ringX - o.px) for o in recs) > RING_MAX * 0.9  # wider than the plain ring
    assert g.orbs.lastUnknown == "wide"
    settle(g)
    fire(g, "streampop", "off", n=30, est="default")
    assert all((o.px, o.py) == pytest.approx(ORIGIN) for o in live_recs(g))
    assert g.orbs.lastUnknown is None
    settle(g)


def test_a_known_position_never_spreads(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", "wide", n=10, est="mouseover")
    assert all((o.px, o.py) == pytest.approx(ORIGIN) for o in live_recs(g))
    settle(g)


# ---------------------------------------------------------------- housekeeping


def test_idle_afterwards_and_pools_are_back(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False, trail=True)
    fire(g, "streampop", "wide", n=15, est="default")
    settle(g)
    free, created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert g.orbs.Info(g.orbs)[1] == 0 and free == created and alive == 0 and xf == 0
    assert g.orbs.driver.scripts.OnUpdate is None
    assert g.stub.restrictedHits == 0


def test_driver_allocates_nothing_per_frame(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False, trail=True)
    g.db.flightTime = 1.5
    fire(g, "streampop", "wide", n=20)
    g.db.flightTime = 1.5
    g.tick(0.016, 3)  # still inside the pop hold for most orbs
    assert g.orbs.Info(g.orbs)[1] > 15
    grown = g.env.lua.eval(
        """function(driver, frames, dt)
            local fm = getmetatable(UIParent).__index
            local noop = function() end
            for _, n in ipairs({ "SetPoint", "ClearAllPoints", "SetSize", "SetRotation", "SetVertexColor", "SetTexture",
                "SetBlendMode", "SetDrawLayer" }) do
                fm[n] = noop
            end
            local fn = driver.scripts.OnUpdate
            fn(driver, dt)
            collectgarbage("collect")
            collectgarbage("stop")
            local c0 = collectgarbage("count")
            for _ = 1, frames do
                fn(driver, dt)
            end
            local c1 = collectgarbage("count")
            collectgarbage("restart")
            return c1 - c0
        end"""
    )(g.orbs.driver, 300, 0.002)
    assert g.orbs.Info(g.orbs)[1] > 0
    assert grown < 4.0, grown


@pytest.mark.parametrize(
    "style, result",
    [("stream", "stream"), ("popstream", "pop+stream"), ("wide", "pop+stream"), ("crossfade", "crossfade")],
)
def test_other_styles_are_unchanged(env, style, result):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    opts = dict(
        plate=plate,
        n=3,
        x=ORIGIN[0],
        y=ORIGIN[1],
        ex=ORIGIN[0],
        ey=ORIGIN[1],
        kind="kill",
        style=style,
    )
    assert g.orbs.Burst(g.orbs, g.env.lua.table_from(opts)) == result
    if style == "stream":
        assert all(o.hold == 0 and o.profile is None for o in live_recs(g))
    settle(g)
