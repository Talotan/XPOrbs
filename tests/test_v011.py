"""v0.11: no-mouseover kills start at the mob (cursor weight 0, popstream always from P-hat), crossfade hold + pace,
golden-angle pop ring, whiter arrival flash, truthful BURST/log lines."""

import math

import pytest
from test_v09 import (
    burst,
    chat_lines,
    kill_with_secret_pos_plate,
    make,
    pop_frames,
    pop_textures,
    restricted_plate,
    stream_textures,
)
from test_v010 import DEF_X, DEF_Y, estimate, new_est

# ---------------------------------------------------------------- MobEstimate / origin rule


def test_default_estimate_without_sample_ignores_the_cursor(env):
    est = new_est(env, [0.0])
    for cur in (None, (1911, 885), (0, 0)):
        assert estimate(est, "A", cur) == (
            pytest.approx(DEF_X),
            pytest.approx(DEF_Y),
            "default",
            0,
        )
    assert est.cfg.cursorWeight == 0


def test_cursor_code_path_still_works_with_a_configured_weight(env):
    est = new_est(env, [0.0], cursorWeight=0.35)
    x, y, src, wm = estimate(est, "A", (600, 300))
    assert src == "cursor" and wm == 0
    assert (x, y) == (
        pytest.approx(0.35 * 600 + 0.65 * DEF_X),
        pytest.approx(0.35 * 300 + 0.65 * DEF_Y),
    )
    assert (
        estimate(est, "A")[2] == "default"
    )  # a weight but no cursor is still the default


def test_confident_constant_is_gone(env):
    env.load_addon()
    assert env.ns.MobEstimate.CONFIDENT is None


def test_popstream_uses_estimate_even_with_target_frame_visible(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900, True)  # visible portrait; no mouseover sample
    kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (pytest.approx(DEF_X), pytest.approx(DEF_Y))
    assert g.has_log("origin=estimate plate=yes est=default w=0.00")


def test_popstream_real_stream_starts_at_the_estimate_not_the_portrait(env):
    g = make(env)
    g.stub.setTargetFrame(250, 900, True)
    g.db.cap = 40
    kill_with_secret_pos_plate(g)
    g.stub.tick(0.5)  # the pop is still up; the stream (delay 0.30 + stagger) has begun
    pts = [t.points[1] for t in stream_textures(g)]
    assert pts and all(abs(p[4] - DEF_X) < 200 and abs(p[5] - DEF_Y) < 200 for p in pts)


def test_popstream_falls_back_to_portrait_only_without_an_estimate(env):
    g = make(env)
    g.stub.setTargetFrame(250, 900, True)
    tg = g.env.ns.Target
    assert tuple(tg.StreamOrigin(tg, 10, 20)) == (10, 20, "estimate")
    assert tuple(tg.StreamOrigin(tg, None, None)) == (250, 900, "targetframe")


def test_stream_style_still_uses_the_portrait(env):
    g = make(env)
    g.fake_orbs_on()
    g.db.style = "stream"
    g.stub.setTargetFrame(250, 900, True)
    kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (250, 900) and g.has_log("origin=targetframe plate=no")


def test_test_command_popstream_starts_at_the_estimate_not_the_portrait(env):
    g = make(env)
    plate = restricted_plate(g)
    g.stub.plates["target"] = plate
    g.stub.setTargetFrame(250, 900, True)
    g.slash("test 5 popstream")
    assert chat_lines(g)[-1].endswith("pop=yes stream=estimate style=popstream")


def test_crossfade_kill_logs_origin_estimate_and_orbs_fly_from_it(env):
    g = make(env)
    g.fake_orbs_on()
    g.db.style = "crossfade"
    g.stub.setTargetFrame(250, 900, True)
    kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert g.has_log("origin=estimate plate=yes") and not g.has_log(
        "origin=targetframe"
    )
    assert (b["x"], b["y"]) == (b["ex"], b["ey"])  # Orbs gets one consistent P-hat


# ---------------------------------------------------------------- crossfade hold

HOLD, DELAY = 0.22, 0.04  # XF_HOLD, 0.5 * STAGGER_POP (fixed random 0.5)
GLOW = 2.0


def xf_burst(g, n=1):
    plate = restricted_plate(g, cx=700, cy=400)
    assert (
        burst(
            g,
            plate=plate,
            n=n,
            x=300,
            y=300,
            ex=700,
            ey=500,
            kind="kill",
            style="crossfade",
        )
        == "crossfade"
    )
    return plate


def a_orb(g):
    return [t for t in pop_textures(g) if t.calls["SetDrawLayer"][2] == 0][0]


def test_crossfade_hold_shows_only_copy_a_blooming_at_the_plate(env):
    g = make(env)
    xf_burst(g)
    g.stub.tick(DELAY + 0.03)  # 30 ms into the hold: fade-in 0.5
    assert stream_textures(g) == []  # copy B is hidden during the hold
    h = 0.03 / HOLD
    e = 1 - (1 - h) ** 3
    orb = a_orb(g)
    assert orb.alpha == pytest.approx(0.5)  # XF_FADE_IN 0.06
    assert math.hypot(orb.points[1][4], orb.points[1][5]) == pytest.approx(18 * e)
    assert orb.width == pytest.approx(g.db.size * GLOW * (1 + 0.5 * (1 - e)))
    (G,) = pop_frames(g)
    assert G.shown and all(len(t.points) == 1 for t in pop_textures(g))


def test_crossfade_hold_ends_at_bloom_radius_and_normal_size(env):
    g = make(env)
    xf_burst(g)
    g.stub.tick(DELAY + HOLD - 0.001)
    assert stream_textures(g) == []
    orb = a_orb(g)
    assert orb.alpha == pytest.approx(1)
    assert math.hypot(orb.points[1][4], orb.points[1][5]) == pytest.approx(18, abs=0.01)
    assert orb.width == pytest.approx(g.db.size * GLOW, rel=1e-3)


def test_crossfade_alpha_is_zero_at_birth_then_fades_in(env):
    g = make(env)
    xf_burst(g)
    g.stub.tick(DELAY)  # t = 0: nothing visible yet
    assert not any(t.shown for t in pop_textures(g))
    g.stub.tick(0.06)  # fade-in complete
    assert a_orb(g).alpha == pytest.approx(1)


def test_crossfade_flight_uses_xf_flight_and_equal_power(env):
    g = make(env)
    xf_burst(g)
    dur = g.db.flightTime * 1.2  # XF_FLIGHT * (0.85 + 0.5 * 0.3)
    g.stub.tick(DELAY + HOLD + 0.21 * dur)  # midpoint of the crossfade window
    assert a_orb(g).alpha == pytest.approx(math.sqrt(0.5))
    bo = [t for t in stream_textures(g) if t.calls["SetDrawLayer"][2] == 0][0]
    assert bo.alpha == pytest.approx(math.sqrt(0.5))
    g.stub.tick(0.79 * dur - 0.01)  # still flying just before the end
    assert g.orbs.Info(g.orbs)[1] > 0
    g.stub.tick(0.02)
    assert g.orbs.Info(g.orbs)[1] == 0


def arrival_time(g, step=0.005, limit=4.0):
    t = 0.0
    while t < limit:
        g.stub.tick(step)
        t += step
        if g.orbs.Info(g.orbs)[1] == 0:
            return t
    pytest.fail("orbs never arrived")


def test_crossfade_first_arrival_matches_popstream(env):
    g1 = make(env)
    plate = restricted_plate(g1, cx=700, cy=400)
    assert (
        burst(
            g1,
            plate=plate,
            n=3,
            x=700,
            y=500,
            ex=700,
            ey=500,
            kind="kill",
            style="popstream",
        )
        == "pop+stream"
    )
    pop = arrival_time(g1)
    g2 = make(env)
    xf_burst(g2, n=3)
    xf = arrival_time(g2)
    assert abs(xf - pop) < 0.15, (xf, pop)
    assert xf == pytest.approx(DELAY + HOLD + g2.db.flightTime * 1.2, abs=0.01)


def test_pop_ease_default_unchanged_and_weighted(env):
    env.load_addon()
    ease = env.ns.OrbMath.PopEase
    for p in (0, 0.1, 0.5, 1):
        assert ease(p) == pytest.approx(0.5 * (1 - (1 - p) ** 3) + 0.5 * p**2.2)
        assert ease(p, 0.5) == pytest.approx(ease(p))
        assert ease(p, 0.25) == pytest.approx(0.25 * (1 - (1 - p) ** 3) + 0.75 * p**2.2)
    assert ease(0.001, 0.25) / 0.001 == pytest.approx(
        0.75, abs=0.01
    )  # launch slope 0.75 (was 1.5)
    assert ease(0.001) / 0.001 == pytest.approx(1.5, abs=0.01)
    assert ease(0, 0.25) == 0 and ease(1, 0.25) == pytest.approx(1)


# ---------------------------------------------------------------- golden-angle pop ring


def test_ring_angle_interleaves_the_first_half_around_the_whole_ring(env):
    env.load_addon()
    om = env.ns.OrbMath
    for m in (4, 8, 12):
        angs = [om.RingAngle(i, m, lambda: 0.5) for i in range(1, m // 2 + 1)]
        assert any(math.sin(a) > 0.2 for a in angs) and any(
            math.sin(a) < -0.2 for a in angs
        ), m
        if m >= 8:
            assert any(math.cos(a) > 0.2 for a in angs) and any(
                math.cos(a) < -0.2 for a in angs
            ), m
    assert om.RingAngle(1, 4, lambda: 0.0) == 0
    assert om.RingAngle(2, 4, lambda: 0.0) == pytest.approx(0.618034 * 2 * math.pi)


def test_rested_pop_orbs_cover_both_halves_of_the_ring(env):
    g = make(env)
    plate = restricted_plate(g)
    burst(g, plate=plate, n=12, nPurple=6, kind="kill")
    g.stub.tick(0.2)
    rested = g.db.restedColor
    ys = []
    for t in pop_textures(g):
        if t.calls["SetDrawLayer"][2] == 0 and t.shown:
            vc = t.calls["SetVertexColor"]
            if all(vc[i] == pytest.approx(rested[i]) for i in (1, 2, 3)):
                ys.append(t.points[1][5])
    assert len(ys) == 6
    assert any(y > 10 for y in ys) and any(y < -10 for y in ys)


def test_stream_angles_are_unchanged(env):
    env.load_addon()
    pc = env.ns.OrbMath.PopControl
    for i in range(
        1, 7
    ):  # the first half of 12 keep the upper half: the two-line stream stays
        ang = ((i - 1) + 0.4) / 12 * 2 * math.pi
        c1x, c1y, r = pc(i, 12, 0, 0, lambda: 0.5)
        assert c1x == pytest.approx(math.cos(ang) * r * 2.2) and c1y > 0


# ---------------------------------------------------------------- flash tint


def test_arrival_flash_is_tinted_towards_white(env):
    g = make(env)
    burst(g, n=1, x=300, y=300, kind="kill")
    flash = None
    for _ in range(300):
        g.stub.tick(0.01)
        fl = [
            f
            for f in g.stub.frames.values()
            if f.kind == "Texture" and f.shown and f.width == g.db.size * 12
        ]
        if fl:
            flash = fl[0]
            break
    assert flash is not None
    c = g.db.color
    vc = flash.calls["SetVertexColor"]
    for i in (1, 2, 3):
        assert vc[i] == pytest.approx(c[i] + (1 - c[i]) * 0.45)


# ---------------------------------------------------------------- logs


def test_burst_log_says_plate_not_pop(env):
    g = make(env)
    g.fake_orbs_on()
    kill_with_secret_pos_plate(g)
    assert g.has_log(" plate=yes ") and not g.has_log(" pop=")
