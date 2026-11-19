"""The "streampop" kill style: screen space only (never a plate frame). Every orb is born at the start point, pops out to
a small ring, then launches (nearest to the bar first) into the normal stream path from its ring point. Added beside
popstream / wide / crossfade / stream, which must keep behaving as before."""

import math

import pytest
from test_m5 import build, ctl, show
from test_migration import load
from test_p2_unknown import LCG, ORIGIN, fire, live_recs, settle
from test_v09 import chat_lines, make, pop_frames, restricted_plate, stream_textures

BORN, BLOOM, LAUNCH_SPAN = 0.03, 0.16, 0.20


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


def test_style_command_persists_prints_and_the_panel_radio_checks(env):
    m5 = build(env)
    m5.slash("style streampop")
    assert m5.db.style == "streampop"
    assert m5.say()[-1].endswith("kill style: streampop")
    show(m5)
    assert ctl(m5, "style_streampop").checked and not ctl(m5, "style_stream").checked
    m5.stub.click(ctl(m5, "style_stream"))
    assert m5.db.style == "stream" and not ctl(m5, "style_streampop").checked
    m5.stub.click(ctl(m5, "style_streampop"))
    assert m5.db.style == "streampop" and ctl(m5, "style_streampop").checked


def test_help_and_the_bogus_style_message_list_it(env):
    m5 = build(env)
    m5.slash("style bogus")
    assert "use popstream, wide, crossfade, stream or streampop" in m5.say()[-1]
    m5.slash("help")
    assert any("popstream|wide|crossfade|stream|streampop" in line for line in m5.say())


def test_test_token_fires_a_streampop_burst_with_no_plate_frame(env):
    g = make(env)
    g.stub.plates["target"] = restricted_plate(g)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "isTarget": True})
    g.stub.setTargetFrame(250, 900, True)
    g.slash("test 5 streampop")
    assert chat_lines(g)[-1].endswith(
        "pop=no stream=estimate style=streampop"
    ) or chat_lines(g)[-1].endswith("style=streampop")
    g.stub.tick(0.1)
    assert pop_frames(g) == [] and g.stub.restrictedHits == 0


def test_initdb_keeps_streampop(env):
    assert load(env, {"version": 5, "style": "streampop"}).style == "streampop"


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
    rad = [math.hypot(o.ax - o.px, o.ay - o.py) for o in recs]
    assert min(rad) >= 14 - 1e-6 and max(rad) <= 26 + 1e-6 and max(rad) - min(rad) > 6
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
    g.stub.tick(0.12)  # t = 0.151: the pop has nearly formed and nobody has launched yet (the first is at 0.16)
    shown = orb_textures(g)
    assert all(
        10 <= math.hypot(pos(t)[0] - ORIGIN[0], pos(t)[1] - ORIGIN[1]) <= 32
        for t in shown
    )
    settle(g)


def test_the_pop_size_eases_from_1_5_to_1_and_fades_in(env):
    g = make(env)
    fire(g, "streampop")
    g.stub.tick(0.5 * BORN + 0.025)  # t = 0.025: alpha 0.5 of the 0.05 s fade-in
    (orb,) = orb_textures(g)
    assert orb.alpha == pytest.approx(0.5, abs=0.02)
    g.stub.tick(BLOOM)
    (orb,) = orb_textures(g)
    assert orb.alpha == pytest.approx(1) and orb.width == pytest.approx(
        g.db.size * 2.0, rel=0.01
    )
    settle(g)


def test_launches_are_nearest_to_the_bar_first_over_0_2_s(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", n=12)
    dx, dy = dest_of(g)
    recs = live_recs(g)
    ordered = sorted(recs, key=lambda o: o.hold)
    dist = [math.hypot(dx - o.ax, dy - o.ay) for o in ordered]
    assert dist == sorted(dist)  # nearest ring point launches first
    holds = [o.hold for o in ordered]
    assert holds[0] == pytest.approx(BLOOM) and holds[-1] - holds[0] == pytest.approx(
        LAUNCH_SPAN
    )
    settle(g)


def test_rested_orbs_launch_later_by_the_rested_delay(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", n=6, nPurple=3)
    recs = live_recs(g)
    assert max(o.hold for o in recs if o.rested) > max(
        o.hold for o in recs if not o.rested
    )
    assert all(o.hold >= BLOOM for o in recs)
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
    )  # the drift ended exactly where the flight starts
    g.stub.tick(0.004)
    (orb,) = orb_textures(g)
    assert math.hypot(pos(orb)[0] - before[0], pos(orb)[1] - before[1]) < 3
    settle(g)


def test_nothing_flies_back_through_the_centre(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", n=40)
    for o in live_recs(g):
        rx, ry = o.ax - o.px, o.ay - o.py  # outward, away from the ring centre
        assert (o.c1x - o.x0) * rx + (o.c1y - o.y0) * ry > 0
    settle(g)


# ---------------------------------------------------------------- unknown origin


def test_unknown_origin_wide_spreads_the_ring_centres_and_off_does_not(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    fire(g, "streampop", "wide", n=30, est="default")
    centres = [(o.px, o.py) for o in live_recs(g)]
    assert (
        max(math.hypot(a[0] - b[0], a[1] - b[1]) for a in centres for b in centres) > 40
    )  # over the ellipse
    for o in live_recs(g):
        assert (
            math.hypot(o.ax - o.px, o.ay - o.py) <= 26 + 1e-6
        )  # each ring is centred on its own point
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
    [("stream", "stream"), ("popstream", "pop+stream"), ("wide", "wide")],
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
        assert all(o.hold == 0 and o.prof is None for o in live_recs(g))
    settle(g)
