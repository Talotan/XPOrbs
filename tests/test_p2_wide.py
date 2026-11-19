"""The "wide" kill style (once "mob"): one burst of plate-space orbs at the mob that launch (staggered) and cross-fade
into the screen-space stream. Added alongside popstream / crossfade / stream, which must keep behaving as before."""

import math

import pytest
from test_m5 import build, ctl, show
from test_migration import load
from test_p2_zoom import anchor_of
from test_v09 import burst, chat_lines, make, pop_frames, pop_textures, restricted_plate, stream_textures

BORN, HOLD, STAGGER = 0.04, 0.195, 0.08  # MOB_BORN, hold of a lone orb at random 0.5 (0.18 + 0.015), STAGGER_POP


def wide_burst(g, n=6, **kw):
    plate = kw.pop("plate", None) or restricted_plate(g, cx=700, cy=400)
    opts = dict(plate=plate, n=n, x=300, y=300, ex=700, ey=500, kind="kill", style="wide")
    opts.update(kw)
    assert burst(g, **opts) == "wide"
    return plate


def a_orbs(g):
    return [t for t in pop_textures(g) if t.calls["SetDrawLayer"][2] == 0 and t.shown]


def b_orbs(g):
    return [t for t in stream_textures(g) if t.calls["SetDrawLayer"][2] == 0]


# ---------------------------------------------------------------- setting and commands


def test_style_command_persists_prints_and_the_panel_radio_checks(env):
    m5 = build(env)
    m5.slash("style wide")
    assert m5.db.style == "wide"
    assert m5.say()[-1].endswith("kill style: wide")
    show(m5)
    assert ctl(m5, "style_wide").checked and not ctl(m5, "style_popstream").checked
    m5.slash("style stream")
    m5.stub.click(ctl(m5, "style_wide"))
    assert m5.db.style == "wide" and ctl(m5, "style_wide").checked and not ctl(m5, "style_stream").checked


def test_test_command_fires_a_wide_burst(env):
    g = make(env)
    g.stub.plates["target"] = restricted_plate(g)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "isTarget": True})
    g.stub.setTargetFrame(250, 900, True)
    g.slash("test 5 wide")
    assert chat_lines(g)[-1].endswith("pop=no stream=estimated style=wide")
    g.stub.tick(0.1)
    assert len(pop_frames(g)) == 1 and pop_frames(g)[0].shown


def test_initdb_keeps_wide_maps_mob_and_resets_junk(env):
    assert load(env, {"version": 5, "style": "wide"}).style == "wide"
    assert load(env, {"version": 5, "style": "mob"}).style == "wide"  # the old name


def test_mob_is_still_accepted_as_an_alias(env):
    m5 = build(env)
    m5.slash("style mob")
    assert m5.db.style == "wide" and m5.say()[-1].endswith("kill style: wide")
    m5.slash("style bogus")
    assert "use popstream, wide, crossfade or stream" in m5.say()[-1]
    g = make(env)
    g.stub.plates["target"] = restricted_plate(g)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "isTarget": True})
    g.stub.setTargetFrame(250, 900, True)
    g.slash("test 5 mob")
    assert chat_lines(g)[-1].endswith("style=wide")


def test_initdb_resets_junk_style(env):
    assert load(env, {"version": 5, "style": "mobb"}).style == "popstream"


# ---------------------------------------------------------------- the burst


def test_wide_burst_uses_one_plate_frame_anchored_at_bottom(env):
    g = make(env)
    wide_burst(g, n=5)
    (f,) = pop_frames(g)
    assert anchor_of(f) == ("CENTER", "BOTTOM", 0, 0)
    g.stub.tick(BORN + 0.1)
    assert len(a_orbs(g)) == 5  # every orb has a plate copy
    assert g.stub.restrictedHits == 0


def test_wide_burst_follows_the_zoom_anchor(env):
    g = make(env)
    g.slash("zoomanchor on")
    g.stub.zoom = 15
    wide_burst(g, n=3)
    (f,) = pop_frames(g)
    assert anchor_of(f) == ("CENTER", "BOTTOM", 0, pytest.approx(-(10 + 500 / 15)))


def test_orbs_born_together_then_launch_staggered_and_swap_to_copy_b(env):
    g = make(env, fixed_random=False)
    wide_burst(g, n=8)
    g.stub.tick(BORN + 0.02)
    assert len(a_orbs(g)) == 8  # all born within 0.04 s
    assert b_orbs(g) == []  # the hold: copy A only
    t, t_first, t_all = BORN + 0.02, None, None
    while t < BORN + HOLD + STAGGER + 1.2 and t_all is None:
        g.stub.tick(0.005)
        t += 0.005
        seen = len(b_orbs(g))
        if seen and t_first is None:
            t_first = t
        if seen == 8:
            t_all = t
    assert t_all is not None
    assert t_first >= HOLD - 0.01  # nobody launches before the bloom is over
    assert t_all - t_first > 0.03  # the launch is staggered


def test_after_the_crossfade_only_copy_b_is_visible(env):
    g = make(env)  # fixed random 0.5: hold 0.195, dur = flightTime * 1.1 * 1.0
    wide_burst(g, n=1)
    dur = g.db.flightTime * 1.1
    g.stub.tick(0.02 + HOLD + 0.12 * dur)  # mid crossfade (p = 0.12 of [0.04, 0.20])
    assert a_orbs(g)[0].alpha == pytest.approx(math.sqrt(0.5), abs=0.02)
    assert b_orbs(g)[0].alpha == pytest.approx(math.sqrt(0.5), abs=0.02)
    g.stub.tick(0.1 * dur)  # p = 0.22
    assert a_orbs(g) == [] and len(b_orbs(g)) == 1


def test_bloom_reaches_a_ring_point_between_30_and_55_px_then_drifts(env):
    g = make(env)
    wide_burst(g, n=1)
    g.stub.tick(0.02 + 0.18)  # the bloom just ended
    (a,) = a_orbs(g)
    x0, y0 = a.points[1][4], a.points[1][5]
    assert 30 <= math.hypot(x0, y0) <= 55 + 12  # POP_R_MAX plus the upward drift
    g.stub.tick(0.01)
    x1, y1 = a.points[1][4], a.points[1][5]
    assert (x1, y1) != (x0, y0)  # no freeze on the ring: it keeps drifting
    assert math.hypot(x1 - x0, y1 - y0) == pytest.approx(0.01 * 15, abs=0.01 * 8 + 1e-6)


def test_crossfade_keeps_its_own_timings(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    assert burst(g, plate=plate, n=1, x=300, y=300, ex=700, ey=500, kind="kill", style="crossfade") == "crossfade"
    g.stub.tick(0.04 + 0.22 - 0.001)  # delay 0.5 * STAGGER_POP, XF_HOLD
    (a,) = a_orbs(g)
    assert math.hypot(a.points[1][4], a.points[1][5]) == pytest.approx(18, abs=0.01)  # XF_BLOOM_R


@pytest.mark.parametrize("kw", [{"plate": None}, {"kind": "other"}])
def test_no_plate_or_other_kind_is_a_plain_stream(env, kw):
    g = make(env)
    opts = dict(n=3, x=300, y=300, kind="kill", style="wide")
    plate = restricted_plate(g)
    opts["plate"] = plate
    opts.update(kw)
    if opts["plate"] is None:
        del opts["plate"]
    assert burst(g, **opts) == "stream"
    assert pop_frames(g) == [] or not any(f.shown for f in pop_frames(g))


def test_everything_is_idle_after_the_burst(env):
    g = make(env, fixed_random=False)
    wide_burst(g, n=10)
    g.tick(0.05, 80)
    assert g.orbs.Info(g.orbs)[1] == 0
    free, created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert free == created and alive == 0 and xf == 0
    assert g.stub.updaters() == 0
    assert g.stub.restrictedHits == 0


def test_plate_reused_fades_the_wide_frame(env):
    g = make(env)
    plate = wide_burst(g, n=3)
    g.stub.tick(0.1)
    assert len(a_orbs(g)) == 3
    g.orbs.PlateReused(g.orbs, plate)
    g.stub.tick(0.11)  # past POP_FADE_OUT
    assert a_orbs(g) == []


def test_driver_allocates_nothing_per_frame_for_a_wide_burst(env):
    g = make(env, fixed_random=False, trail=True)
    g.db.flightTime = 1.5
    wide_burst(g, n=20, x=400, y=300)
    g.tick(0.016, 3)
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




# ---------------------------------------------------------------- launch order, continuity, jitter, direction


def recs(g):
    from test_p2_unknown import live_recs

    return live_recs(g)


def seeded(env):
    """Install the deterministic math.random BEFORE make(): the addon captures math.random when it loads."""
    from test_p2_unknown import LCG

    env.lua.execute(LCG)


def test_launch_order_is_nearest_to_the_bar_first_within_the_new_hold_range(env):
    seeded(env)
    g = make(env, fixed_random=False)
    wide_burst(g, n=12)
    os_ = recs(g)
    assert len(os_) == 12
    free = [o for o in os_ if not o.rested]
    # o.dist0 is measured from the launch point (ring + a few px of drift), so the order matches it closely
    d = [o.dist0 for o in free]
    h = [o.hold for o in free]
    n = len(free)
    rd = [sorted(d).index(v) for v in d]
    rh = [sorted(h).index(v) for v in h]
    rho = 1 - 6 * sum((x - y) ** 2 for x, y in zip(rd, rh)) / (n * (n * n - 1))
    assert rho > 0.8
    assert 0.18 <= min(o.hold for o in os_) and max(o.hold for o in os_ if not o.rested) <= 0.40 + 0.03 + 1e-9
    assert min(o.hold for o in os_) < 0.22 and max(o.hold for o in os_ if not o.rested) > 0.38
    for o in os_:  # every orb has per-orb drift numbers: 15 px/s up plus 8 px/s outwards
        assert abs(o.dvx) <= 8 and 7 <= o.dvy <= 23


def test_flight_jitter_for_wide_orbs_is_narrow_and_others_keep_theirs(env):
    seeded(env)
    g = make(env, fixed_random=False)
    wide_burst(g, n=30)
    base = g.db.flightTime * 1.1
    durs = [o.dur for o in recs(g)]
    assert min(durs) >= base * 0.94 - 1e-9 and max(durs) <= base * 1.06 + 1e-9
    assert max(durs) - min(durs) > 0.05 * base


def test_c1_leaves_along_the_ring_angle(env):
    seeded(env)
    g = make(env, fixed_random=False)
    wide_burst(g, n=10, x=300, y=300)
    for o in recs(g):
        ring = (o.x0 - o.dvx * (o.hold - 0.18) - o.px, o.y0 - o.dvy * (o.hold - 0.18) - o.py)
        cx, cy = o.c1x - o.x0, o.c1y - o.y0
        # outwards: c1's horizontal leg points the same way as the ring point from the centre (lift only adds up)
        assert cx * ring[0] > 0 or abs(ring[0]) < 1e-6
        assert math.hypot(cx, cy) > 40


def test_no_position_jump_between_the_end_of_the_hold_and_the_flight(env):
    g = make(env)
    wide_burst(g, n=1)
    (o,) = recs(g)
    assert (o.dvx, o.dvy) != (0, 0)
    g.stub.tick(0.02 + o.hold - 0.001)
    (a,) = a_orbs(g)
    before = (a.points[1][4], a.points[1][5])
    g.stub.tick(0.002)
    (a,) = a_orbs(g)
    after = (a.points[1][4], a.points[1][5])
    assert math.hypot(after[0] - before[0], after[1] - before[1]) < 1.0


def test_crossfade_orbs_have_no_drift_and_narrow_jitter(env):
    seeded(env)
    g = make(env, fixed_random=False)
    plate = restricted_plate(g, cx=700, cy=400)
    assert burst(g, plate=plate, n=10, x=300, y=300, ex=700, ey=500, kind="kill", style="crossfade") == "crossfade"
    for o in recs(g):
        # bloom 0.22 + leave start 0..0.15 + leave 0.18 + gap 0.10; B flies flightTime * 0.40 * (0.94..1.06)
        assert (o.dvx, o.dvy) == (0, 0) and 0.50 <= o.hold <= 0.65 and o.hold == pytest.approx(0.50 + o.ls)
        assert 0.94 * 0.40 * g.db.flightTime - 1e-9 <= o.dur <= 1.06 * 0.40 * g.db.flightTime + 1e-9
