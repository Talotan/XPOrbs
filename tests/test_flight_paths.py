"""Flight paths (db.flightPath): Smooth, Chaos and Helix. Pure OrbMath maths, then the renderer, settings, slash
commands and the options radios."""

import math
import random
from types import SimpleNamespace

import pytest
from conftest import TESTS, make_runtime
from test_m5 import build, ctl, show
from test_v09 import burst, chat_lines, make, restricted_plate, stream_textures
from test_v102 import load_db

KINDS = ("smooth", "chaos", "helix")


def fresh_env():
    """A second, independent runtime (one test compares several runs, and an addon loads once per runtime)."""
    from conftest import ROOT, addon_files

    lua, ns, load_chunk = make_runtime()
    load_chunk(TESTS / "wowstub.lua", "wowstub.lua")(ns)
    e = SimpleNamespace(lua=lua, ns=ns, load_chunk=load_chunk, G=lua.globals())

    def load_addon():
        for rel in addon_files():
            load_chunk(ROOT / rel, rel)("XPOrbs", ns)

    e.load_addon = load_addon
    return e


@pytest.fixture
def om(env):
    env.load_addon()
    return env.ns.OrbMath


def params(om, kind, index=1, distance=600.0, seed=1):
    rng = random.Random(seed)
    return tuple(om.PathParams(kind, index, distance, rng.random))


def offset(om, kind, t, p):
    return tuple(om.PathOffset(kind, t, *p))


# ---------------------------------------------------------------- pure maths


def test_path_kind_falls_back_to_smooth(om):
    assert [om.PathKind(k) for k in KINDS] == list(KINDS)
    assert [om.PathKind(k) for k in ("bogus", "", None, 3, "Chaos")] == ["smooth"] * 5


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("distance", [30.0, 200.0, 600.0, 1500.0])
def test_offsets_vanish_at_both_ends(om, kind, distance):
    for seed in range(20):
        p = params(om, kind, seed, distance, seed)
        for t in (0, 1):
            perp, warp, size, alpha = offset(om, kind, t, p)
            assert perp == pytest.approx(0, abs=1e-9) and warp == pytest.approx(
                0, abs=1e-9
            )
            assert size == pytest.approx(1) and alpha == pytest.approx(1)


def test_smooth_is_all_zeros_and_ones_and_draws_no_random(om):
    calls = []
    assert (
        tuple(om.PathParams("smooth", 3, 600, lambda: calls.append(1) or 0.5))
        == (0,) * 7
    )
    assert calls == []
    for t in (0, 0.2, 0.5, 0.99, 1):
        assert offset(om, "smooth", t, (0,) * 7) == (0, 0, 1, 1)
        assert offset(om, "bogus", t, (50, 2, 3, 2, 1, 1, 1)) == (0, 0, 1, 1)


def test_chaos_progress_warp_is_monotonic_even_for_extreme_parameters(om):
    rng = random.Random(7)
    for _ in range(300):
        p = (
            50,
            rng.uniform(1, 3),
            rng.uniform(2, 5),
            rng.choice([0.1, 1.5, 3, 12, 60]),
            0,
            0,
            rng.uniform(0, 6.3),
        )
        last = -1.0
        for i in range(201):
            t = i / 200
            warp = offset(om, "chaos", t, p)[1]
            assert abs(warp) <= 0.08 + 1e-12
            assert t + warp > last - 1e-12
            last = t + warp


def test_chaos_parameter_ranges_and_amplitude_clamps(om):
    for distance in (10, 160, 400, 700, 5000):
        base = min(max(0.12 * distance, 20), 60)
        amps, signs = set(), set()
        for seed in range(200):
            amp, f1, f2, f3, p1, p2, p3 = params(om, "chaos", 1, distance, seed)
            assert 1.1 <= f1 <= 2.0 and 2.6 <= f2 <= 4.0 and 0.9 <= f3 <= 1.5
            assert all(0 <= ph < 2 * math.pi for ph in (p1, p2, p3))
            assert 0.75 * base - 1e-9 <= abs(amp) <= 1.25 * base + 1e-9
            signs.add(amp > 0)
            amps.add(round(amp, 6))
        assert len(amps) > 50 and signs == {
            True,
            False,
        }  # random per orb, either way first
    assert (
        abs(params(om, "chaos", 1, 10, 4)[0]) <= 1.25 * 20
        and abs(params(om, "chaos", 1, 5000, 4)[0]) <= 1.25 * 60
    )
    # the sideways wobble stays inside the amplitude
    p = params(om, "chaos", 1, 500, 3)
    assert (
        max(abs(offset(om, "chaos", i / 500, p)[0]) for i in range(501))
        <= abs(p[0]) + 1e-9
    )


def test_helix_parameters(om):
    for distance in (50, 300, 700, 2000):
        amp, turns, f2, f3, _phase, p2, p3 = params(om, "helix", 2, distance)
        assert amp == pytest.approx(min(max(0.12 * distance, 26), 50))
        assert turns == pytest.approx(min(max(distance / 190, 1.5), 3.0))
        assert (f2, f3, p2, p3) == (0, 0, 0, 0)
    assert (
        params(om, "helix", 1, 10)[1] == 1.5 and params(om, "helix", 1, 99999)[1] == 3.0
    )
    assert (
        params(om, "helix", 1, 10)[0] == 26 and params(om, "helix", 1, 99999)[0] == 50
    )
    for seed in range(50):  # a double helix: strands half a turn apart
        for index in (1, 2, 3, 4, 5, 6):
            phase = params(om, "helix", index, 600, seed)[4]
            assert abs(phase - (index % 2) * math.pi) <= 0.10 + 1e-9


def test_helix_handedness_flips_the_turns(om):
    left = om.PathParams("helix", 1, 600, random.Random(1).random, 1)
    right = om.PathParams("helix", 1, 600, random.Random(1).random, -1)
    assert right[1] == -left[1] and right[0] == left[0] and right[4] == left[4]


def test_path_shape(om):
    assert tuple(om.PathShape("smooth")) == (1, 1, None, None, 1)
    assert tuple(om.PathShape("bogus")) == (1, 1, None, None, 1)
    assert tuple(om.PathShape("chaos")) == (0.6, 1, None, None, 1)
    assert tuple(om.PathShape("helix")) == (0.10, 2, 0.97, 0.06, 0.5)


def test_helix_depth_size_and_alpha_ranges(om):
    sizes = []
    for seed in range(40):
        p = params(om, "helix", seed, 700, seed)
        for i in range(201):
            perp, warp, size, alpha = offset(om, "helix", i / 200, p)
            assert warp == 0
            assert 0.6 - 1e-9 <= size <= 1.4 + 1e-9 and 0.5 - 1e-9 <= alpha <= 1 + 1e-9
            assert abs(perp) <= p[0] + 1e-9
            sizes.append(size)
    assert min(sizes) < 0.75 and max(sizes) > 1.25  # it does swing


def test_helix_envelope_opens_quickly_and_closes_on_landing(om):
    p = (30, 2, 0, 0, math.pi / 2, 0, 0)
    assert abs(offset(om, "helix", 0.02, p)[0]) < 0.2 * 30
    assert offset(om, "helix", 0.5, p)[0] == pytest.approx(
        30 * math.sin(2 * 2 * math.pi * 0.5 + math.pi / 2), abs=1e-6
    )
    assert abs(offset(om, "helix", 0.98, p)[0]) < 0.2 * 30


# ---------------------------------------------------------------- renderer


def trace(env, path=None, style="stream", ticks=12, dt=0.07, switch=None, **extra):
    """(x, y, width, alpha) of every live texture after each tick of a 3-orb burst with trails."""
    g = make(fresh_env(), trail=True)
    g.db.flightTime = 1.0
    if path:
        g.db.flightPath = path
    burst(g, n=3, x=300, y=200, kind="kill", style=style, **extra)
    if switch:
        g.db.flightPath = switch
    out = []
    for _ in range(ticks):
        g.tick(dt)
        out.append(
            [
                (
                    round(t.points[1][4], 4),
                    round(t.points[1][5], 4),
                    round(t.width, 4),
                    round(t.alpha, 4),
                )
                for t in stream_textures(g)
            ]
        )
    return g, out


# Recorded on the code before flight paths existed (git HEAD 5859978): ticks 4 and 9 of trace() on Direct Stream.
GOLDEN_SMOOTH = [
    [(359.5754, 243.8802, 35, 0.45), (359.5754, 243.8802, 28, 1), (359.5754, 243.8802, 26.6, 0.6),
     (356.6285, 244.9512, 23.8, 0.55), (353.4804, 245.5834, 19.6, 0.3),
     (240.7766, 214.5773, 35, 0.45), (240.7766, 214.5773, 28, 1), (240.7766, 214.5773, 26.6, 0.6),
     (240.762, 216.2474, 23.8, 0.55), (241.1661, 217.6412, 19.6, 0.3),
     (333.6046, 151.1264, 35, 0.45), (333.6046, 151.1264, 28, 1), (333.6046, 151.1264, 26.6, 0.6),
     (331.2988, 154.0935, 23.8, 0.55), (328.9272, 157.1365, 19.6, 0.3)],
    [(393.8561, 159.0603, 35, 0.45), (393.8561, 159.0603, 28, 1), (393.8561, 159.0603, 26.6, 0.6),
     (393.2091, 163.7371, 23.8, 0.55), (392.5168, 168.3777, 19.6, 0.3),
     (299.4706, 138.9241, 35, 0.45), (299.4706, 138.9241, 28, 1), (299.4706, 138.9241, 26.6, 0.6),
     (295.9111, 142.7892, 23.8, 0.55), (292.3887, 146.6319, 19.6, 0.3),
     (373.2224, 95.322, 35, 0.45), (373.2224, 95.322, 28, 1), (373.2224, 95.322, 26.6, 0.6),
     (371.9387, 97.4295, 23.8, 0.55), (370.6277, 99.5447, 19.6, 0.3)],
]  # fmt: skip


@pytest.mark.parametrize("path", [None, "smooth"])
def test_smooth_is_exactly_the_old_flight(env, path):
    _, rows = trace(env, path)
    assert [rows[3], rows[8]] == GOLDEN_SMOOTH


@pytest.mark.parametrize("path", ["chaos", "helix"])
def test_other_paths_differ_from_smooth_mid_flight(env, path):
    _, smooth = trace(env, "smooth")
    _, other = trace(env, path)
    moved = [
        abs(a[0] - b[0]) + abs(a[1] - b[1])
        for row_a, row_b in zip(smooth[1:11], other[1:11])
        for a, b in zip(row_a, row_b)
    ]
    assert max(moved) > 5


def end_points(env, path, style):
    """Where the first and the last drawn frame of one orb's body sit (tiny ticks, so both ends are sampled)."""
    g = make(fresh_env(), trail=False)
    g.db.flightTime = 1.0
    g.db.flightPath = path
    kw = {}
    if style in ("popstream", "crossfade"):
        kw["plate"] = restricted_plate(g, cx=700, cy=400)
    burst(g, n=1, x=300, y=200, kind="kill", style=style, **kw)
    first = last = None
    for _ in range(4000):
        g.tick(0.001)
        texs = stream_textures(g)  # one orb: underlay, body, sparkle
        bodies = texs[1:2] if len(texs) == 3 else []
        if bodies:
            pos = (bodies[0].points[1][4], bodies[0].points[1][5])
            first = first or pos
            last = pos
        elif last is not None:
            break
    return first, last


@pytest.mark.parametrize("path", ["chaos", "helix"])
@pytest.mark.parametrize("style", ["stream", "streampop", "popstream", "crossfade"])
def test_orbs_start_at_the_origin_and_land_on_the_destination(env, path, style):
    # the same random numbers drive both runs, so only the path differs and the ends must coincide
    smooth_first, smooth_last = end_points(env, "smooth", style)
    first, last = end_points(env, path, style)
    assert first and last and smooth_first and smooth_last
    assert (
        math.dist(first, smooth_first) < 3
    )  # 1 ms after the start the offset is still tiny
    assert math.dist(last, smooth_last) < 3  # ... and 1 ms before the landing too


@pytest.mark.parametrize("path", ["chaos", "helix"])
def test_ghosts_trace_the_same_path_a_step_earlier(env, path):
    g = make(env, trail=True)
    g.db.flightTime = 1.0
    g.db.flightPath = path
    burst(g, n=1, x=300, y=200, kind="kill", style="stream")
    # fixed random: dur = 1 s, so a tick of 0.015 s is exactly one GHOST_STEP of progress
    bodies, ghost1s, ghost2s = [], [], []
    for _ in range(50):
        g.tick(0.015)
        texs = stream_textures(g)
        if len(texs) == 5:
            bodies.append((texs[1].points[1][4], texs[1].points[1][5]))
            ghost1s.append((texs[3].points[1][4], texs[3].points[1][5]))
            ghost2s.append((texs[4].points[1][4], texs[4].points[1][5]))
    assert len(bodies) > 20
    for k in range(2, len(bodies)):
        assert math.dist(ghost1s[k], bodies[k - 1]) < 1e-6
        assert math.dist(ghost2s[k], bodies[k - 2]) < 1e-6


def test_helix_orbs_swing_in_size_and_chaos_orbs_do_not(env):
    _, helix = trace(env, "helix", ticks=14, dt=0.05)
    widths = {row[1][2] for row in helix[1:12] if len(row) >= 2}
    assert max(widths) - min(widths) > 2
    assert all(28 * 0.6 - 1e-6 <= w <= 28 * 1.4 + 1e-6 for w in widths)
    _, chaos = trace(env, "chaos", ticks=14, dt=0.05)
    assert {row[1][2] for row in chaos[1:6]} == {28}


def test_the_path_is_fixed_at_spawn(env):
    _, kept = trace(env, "chaos")
    _, switched = trace(env, "chaos", switch="helix")
    assert switched == kept
    _, kept = trace(env, "smooth")
    _, switched = trace(env, "smooth", switch="chaos")
    assert switched == kept


def test_a_burst_can_override_the_path(env):
    g = make(env, trail=True)
    g.db.flightTime = 1.0
    burst(g, n=3, x=300, y=200, kind="kill", style="stream", path="helix")
    g.tick(0.07, 6)
    got = [
        (round(t.points[1][4], 4), round(t.points[1][5], 4)) for t in stream_textures(g)
    ]
    _, helix = trace(env, "helix", ticks=6)
    assert got == [(a[0], a[1]) for a in helix[5]]


@pytest.mark.parametrize("path", KINDS)
def test_driver_allocates_nothing_per_frame(env, path):
    g = make(env, fixed_random=False, trail=True)
    g.db.flightTime = 1.5
    g.db.flightPath = path
    burst(g, n=20, x=400, y=300, kind="kill", style="stream")
    burst(g, n=20, x=600, y=300, kind="kill", style="streampop")
    g.tick(0.016, 3)
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


def test_burst_upvalue_count_has_not_grown(env):
    g = make(env)
    count = env.lua.eval(
        """function(f) local i = 0
        while debug.getupvalue(f, i + 1) do i = i + 1 end
        return i end"""
    )(g.orbs.Burst)
    assert (
        count <= 55
    )  # Lua 5.1 allows 60 per function; this was 55 before flight paths


# ---------------------------------------------------------------- settings and commands


def test_default_is_smooth(env):
    assert load_db(env, {}).flightPath == "smooth"
    for good in KINDS:
        assert load_db(env, {"version": 7, "flightPath": good}).flightPath == good


@pytest.mark.parametrize("bad", ["bogus", "Chaos", 5, True, ""])
def test_junk_flight_path_resets_to_the_default(env, bad):
    assert load_db(env, {"version": 7, "flightPath": bad}).flightPath == "smooth"


def test_path_command(env):
    g = make(env)
    g.slash("path")
    assert "flight path: Smooth" in chat_lines(g)[-1]
    g.slash("path chaos")
    assert g.db.flightPath == "chaos" and "flight path: Chaos" in chat_lines(g)[-1]
    g.slash("path helix")
    assert g.db.flightPath == "helix"
    g.slash("path bogus")
    assert (
        g.db.flightPath == "helix" and "use smooth, chaos or helix" in chat_lines(g)[-1]
    )
    g.slash("path")
    assert "flight path: Helix" in chat_lines(g)[-1]
    g.slash("help")
    assert any("/xporbs path smooth|chaos|helix" in line for line in chat_lines(g))


def test_test_tokens_override_the_path_for_that_burst(env):
    g = make(env, trail=True)
    g.db.flightTime = 1.0
    g.db.style = "stream"

    def run(command):
        g.slash(command)
        g.tick(0.07, 6)
        pos = sorted(
            (round(t.points[1][4], 3), round(t.points[1][5], 3))
            for t in stream_textures(g)
        )
        g.tick(0.5, 10)
        return pos

    plain = run("test 5")
    helix = run("test 5 helix")
    assert helix != plain
    assert g.db.flightPath == "smooth"  # only that burst
    assert run("test 5 smooth") == plain
    chaos = run("test chaos 5")
    assert chaos != plain and chaos != helix
    g.slash("test 5 chaos")
    assert "path=chaos" in chat_lines(g)[-1]
    g.slash("test 5")
    assert "path=" not in chat_lines(g)[-1]


# ---------------------------------------------------------------- options


@pytest.fixture
def m(env):
    return build(env)


def test_flight_path_radios(m):
    show(m)
    assert m.opt.rows["flightPath"] is not None
    for kind in KINDS:
        assert ctl(m, f"flightPath_{kind}").template == "UIRadioButtonTemplate"
    assert (
        ctl(m, "flightPath_smooth").checked and not ctl(m, "flightPath_chaos").checked
    )
    m.stub.click(ctl(m, "flightPath_helix"))
    assert m.db.flightPath == "helix"
    assert (
        ctl(m, "flightPath_helix").checked and not ctl(m, "flightPath_smooth").checked
    )
    m.stub.click(
        ctl(m, "flightPath_helix")
    )  # clicking the selected one keeps it selected
    assert ctl(m, "flightPath_helix").checked
    m.stub.click(ctl(m, "flightPath_chaos"))
    assert m.db.flightPath == "chaos" and ctl(m, "flightPath_chaos").checked
    assert m.opt.descs.flightPath.text.startswith("How orbs fly to the bar")


def test_flight_path_reset(m):
    show(m)
    assert not bool(m.opt.resets["flightPath"].shown)
    m.stub.click(ctl(m, "flightPath_chaos"))
    assert bool(m.opt.resets["flightPath"].shown)
    m.stub.click(m.opt.resets["flightPath"])
    assert m.db.flightPath == "smooth" and ctl(m, "flightPath_smooth").checked


def test_flight_path_row_sits_after_the_style_group_and_above_the_xp_bar_rows(m):
    show(m)
    flight = m.opt.rows["flightPath"].points[1][5]
    assert (
        m.opt.rows["style_stream"].points[1][5] > flight
    )  # y grows downwards: more negative is lower
    assert m.opt.rows["targetFrame"].points[1][5] < flight
