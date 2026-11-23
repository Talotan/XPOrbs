"""Flight paths (db.flightPath): Smooth, Chaos and Helix. Pure OrbMath maths, then the renderer, settings, slash
commands and the options radios."""

import math
import random
from types import SimpleNamespace

import pytest
from conftest import TESTS, make_runtime
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
    assert tuple(om.PathShape("helix")) == (0.10, 2.5, 1.2125, 0.075, 0.5)


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
    # 1 ms after the start the offset is still tiny (a helix starts from its own line, not the disc: up to ~6 px apart)
    assert math.dist(first, smooth_first) < (3 + 6 if path == "helix" else 3)
    assert math.dist(last, smooth_last) < 3  # ... and 1 ms before the landing too


@pytest.mark.parametrize("path", ["chaos", "helix"])
def test_ghosts_trace_the_same_path_a_step_earlier(env, path):
    g = make(env, trail=True)
    g.db.flightTime = 1.0
    g.db.flightPath = path
    burst(g, n=1, x=300, y=200, kind="kill", style="stream")
    # fixed random: dur = 1 s (a helix 1.25 s), so a tick of 0.015 s (0.015 * 1.25) is one GHOST_STEP of progress
    step = 0.015 * (1.25 if path == "helix" else 1)
    bodies, ghost1s, ghost2s = [], [], []
    for _ in range(50):
        g.tick(step)
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


@pytest.mark.parametrize("hold", [0.1, 0.5])  # copy A blooming / copy B flying
def test_screen_anchored_crossfade_allocates_nothing_per_frame(env, hold):
    g = make(env, fixed_random=False, trail=True)
    g.db.flightTime = 1.5
    assert burst(g, n=10, ex=700, ey=500, kind="kill", style="crossfade", est="default") == "crossfade"
    g.tick(0.05, int(hold / 0.05))
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
    )(g.orbs.driver, 20, 0.002)
    assert g.orbs.Info(g.orbs)[1] > 0
    assert grown < 4.0, grown


def burst_upvalue_counts(g):
    """(upvalues of Burst, upvalues of the per-orb builder closure it creates), via a call hook (test-only)."""
    run = g.env.lua.eval(
        """function(burstFn, fire)
        local inner = 0
        local function count(f)
            local i = 0
            while debug.getupvalue(f, i + 1) do i = i + 1 end
            return i
        end
        debug.sethook(function()
            local info = debug.getinfo(2, "Sf")
            if info.what == "Lua" and info.short_src:find("Orbs") and info.func ~= burstFn
                and info.linedefined > 1000 and count(info.func) > inner then
                inner = count(info.func)
            end
        end, "c")
        fire()
        debug.sethook()
        return count(burstFn), inner
        end"""
    )
    return run(g.orbs.Burst, lambda: burst(g, n=3, x=300, y=300, kind="kill", style="stream"))


def test_burst_builder_closure_stays_under_the_lua_upvalue_limit(env):
    g = make(env)
    outer, inner = burst_upvalue_counts(g)
    assert outer <= 60 and 0 < inner <= 60, (outer, inner)  # Lua 5.1 allows 60 per function


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
    assert "flight style: Smooth" in chat_lines(g)[-1]
    g.slash("path chaos")
    assert g.db.flightPath == "chaos" and "flight style: Chaos" in chat_lines(g)[-1]
    g.slash("path helix")
    assert g.db.flightPath == "helix"
    g.slash("path bogus")
    assert (
        g.db.flightPath == "helix" and "use smooth, chaos or helix" in chat_lines(g)[-1]
    )
    g.slash("path")
    assert "flight style: Helix" in chat_lines(g)[-1]
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


# ---------------------------------------------------------------- bow direction and screen clamp

W, H = 1920, 1080  # the stub's UIParent


def old_pop_control(i, n, x0, y0, rand, spread=1, lift=0.35):
    """PopControl as it was before the bow (the regression lock)."""
    angle = ((i - 1) + rand() * 0.8) / n * 2 * math.pi
    radius = (45 + rand() * 55) * spread
    return x0 + math.cos(angle) * radius * 2.2, y0 + (0.8 * math.sin(angle) + lift) * radius * 2.2, radius


def old_home_control(c1x, c1y, dx, dy, dist0):
    return dx + (c1x - dx) * 0.15, dy + 0.30 * dist0


def test_default_bow_leaves_pop_and_home_control_bit_identical(om):
    for seed in range(40):
        rng = random.Random(seed)
        x0, y0, n, i = rng.uniform(0, W), rng.uniform(0, H), rng.randint(1, 20), 1
        i = rng.randint(1, n)
        spread, lift = rng.choice([(None, None), (0.45, 0.10), (1.5, 0.35)])
        old = old_pop_control(i, n, x0, y0, random.Random(seed + 99).random, spread or 1, lift or 0.35)
        for bow in ((), (0, 1)):
            new = tuple(om.PopControl(i, n, x0, y0, random.Random(seed + 99).random, spread, lift, *bow))
            assert new == old
        c1x, c1y, dx = rng.uniform(0, W), rng.uniform(0, H), rng.uniform(0, W)
        dy, dist0 = rng.uniform(0, 80), rng.uniform(50, 2000)
        want = old_home_control(c1x, c1y, dx, dy, dist0)
        assert tuple(om.HomeControl(c1x, c1y, dx, dy, dist0)) == want
        assert tuple(om.HomeControl(c1x, c1y, dx, dy, dist0, 0, 1)) == want


def test_bow_vector_is_up_for_level_and_downward_flights(om):
    for dest_y in (500, 300, 0):  # the mob at (900, 500): level, then downward
        assert tuple(om.BowVector(900, 500, 1500, dest_y, W, H)) == (0, 1)
        assert tuple(om.BowVector(900, 500, 100, dest_y, W, H, -1)) == (0, 1)
    assert tuple(om.BowVector(900, 500, 900, 500, W, H)) == (0, 1)  # no flight at all


def test_bow_vector_turns_sideways_as_the_flight_climbs(om):
    # straight up: the bow is horizontal, on the requested side
    bx, by = om.BowVector(900, 100, 900, 1000, W, H, 1)
    assert (bx, by) == pytest.approx((1, 0), abs=1e-9)
    bx, by = om.BowVector(900, 100, 900, 1000, W, H, -1)
    assert (bx, by) == pytest.approx((-1, 0), abs=1e-9)
    for rise in (0.05, 0.1, 0.25, 0.5, 0.8):
        for side in (1, -1):
            bx, by = om.BowVector(500, 500, 500 + 1000, 500 + 1000 * rise / math.sqrt(1 - rise * rise), W, H, side)
            assert math.hypot(bx, by) == pytest.approx(1)
            assert bx * side > 0  # the bow always leans to the requested side
    # a weak climb bows mostly up, a steep one mostly sideways
    assert om.BowVector(500, 500, 1500, 560, W, H, 1)[1] > om.BowVector(500, 500, 1000, 1500, W, H, 1)[1]


def test_bow_side_is_the_perpendicular_with_more_room(om):
    # a climb to a top-right bar: the right-hand perpendicular points down-right (lots of room), the left one up-left
    assert om.BowSide(960, 540, 1650, 930, W, H) == 1
    # to a top-centre bar from the middle: both are level; the tie goes to the right
    assert om.BowSide(960, 300, 960, 1060, W, H) == 1
    # up the right-hand side of the screen: the room is to the left
    assert om.BowSide(1700, 300, 1700, 1060, W, H) == -1
    # a flight with no length
    assert om.BowSide(500, 500, 500, 500, W, H) == 1
    # no side given: BowVector picks the same one
    args = (1700, 300, 1700, 1060, W, H)
    assert tuple(om.BowVector(*args)) == tuple(om.BowVector(*args, -1))
    assert om.BowVector(*args)[0] < 0


def test_clamp_to_screen(om):
    assert tuple(om.ClampToScreen(500, 400, W, H, 40)) == (500, 400)
    assert tuple(om.ClampToScreen(-100, 2000, W, H, 40)) == (40, H - 40)
    assert tuple(om.ClampToScreen(W + 10, -5, W, H, 40)) == (W - 40, 40)
    # a destination inside the band widens it on that axis only: a bar flush with the bottom edge keeps y = 20
    assert tuple(om.ClampToScreen(900, 25, W, H, 40, 900, 20)) == (900, 25)
    assert tuple(om.ClampToScreen(900, 5, W, H, 40, 900, 20)) == (900, 20)
    assert tuple(om.ClampToScreen(900, H + 50, W, H, 40, 900, H - 2)) == (900, H - 2)
    assert tuple(om.ClampToScreen(5, 5, 60, 60, 40)) == (30, 30)  # a screen smaller than the margins: the middle
    assert tuple(om.ClampToScreen(5, 5, None, None, 40)) == (5, 5)


# ---- bursts on screen

BARS = {"top-right": (0.85 * W, 0.97 * H), "top-centre": (0.5 * W, 0.99 * H), "top-edge": (0.3 * W, H - 2)}
MOBS = [(0.5 * W, 0.5 * H), (0.35 * W, 0.55 * H), (0.7 * W, 0.45 * H), (0.1 * W, 0.12 * H), (0.9 * W, 0.2 * H),
        (0.2 * W, 0.93 * H)]


def pin_destination(g, x, y):
    g.env.lua.eval("function(T, x, y) T.GetDestination = function() return x, y, true end end")(g.ns.Target, x, y)


@pytest.mark.parametrize("bar", list(BARS))
@pytest.mark.parametrize("style", ["stream", "popstream", "streampop", "crossfade"])
def test_every_flight_stays_on_screen_for_bars_along_the_top(env, bar, style):
    env.lua.execute(LCG_SOURCE)
    g = make(env, fixed_random=False)
    g.db.flightTime = 1.0
    pin_destination(g, *BARS[bar])
    for path in KINDS:
        for mob in MOBS:
            opts = dict(n=8, x=mob[0], y=mob[1], ex=mob[0], ey=mob[1], kind="kill", style=style, path=path)
            if style == "popstream":
                opts["plate"] = restricted_plate(g, cx=mob[0], cy=mob[1])
            assert burst(g, **opts)
            for _ in range(130):
                g.tick(0.025)
                for t in stream_textures(g):
                    x, y = t.points[1][4], t.points[1][5]
                    assert -4 <= x <= W + 4 and -4 <= y <= H + 4, (bar, style, path, mob, x, y)
            assert g.orbs.Info(g.orbs)[1] == 0  # all landed


def test_bottom_bar_flights_are_exactly_the_old_ones_for_smooth(env):
    env.lua.execute(LCG_SOURCE)
    g = make(env, fixed_random=False)
    dx, dy = tuple(g.ns.Target.GetDestination(g.ns.Target))[:2]
    assert dy < 60  # the default test bar is along the bottom
    burst(g, n=6, x=0.5 * W, y=0.5 * H, kind="kill", style="stream", path="smooth")
    recs = live_recs_of(g)
    om = g.ns.OrbMath
    for o in recs:
        assert (o.bowX, o.bowY) == (0, 1)
        assert o.pathAmp == 0 and o.clampMargin == pytest.approx(0.04 * H)
        c2 = tuple(om.HomeControl(o.control1X, o.control1Y, dx, dy, o.flightDist, o.bowX, o.bowY))
        assert c2 == old_home_control(o.control1X, o.control1Y, dx, dy, o.flightDist)
        assert c2[1] > 0.04 * H  # not moved by the clamp
        assert tuple(om.ClampToScreen(*c2, W, H, o.clampMargin, dx, dy)) == c2
    # c1 is the old PopControl value for the orb's own start (the centre of the screen: no clamp involved)
    n = len(recs)
    assert n == 6
    g.tick(0.05)


def live_recs_of(g):
    return list(
        g.env.lua.eval(
            """function(fn)
                local function up(f, name)
                    local i = 1
                    while true do
                        local n, v = debug.getupvalue(f, i)
                        if not n then return nil end
                        if n == name then return v end
                        i = i + 1
                    end
                end
                local drive = up(fn, "drive")
                local live, n = up(drive, "live"), up(drive, "nLive")
                local out = {}
                for i = 1, n do out[i] = live[i] end
                return out
            end"""
        )(g.orbs.driver.scripts.OnUpdate).values()
    )


LCG_SOURCE = """local s = 12345
math.random = function(a, b)
    s = (s * 16807) % 2147483647
    local r = s / 2147483647
    if a == nil then return r elseif b == nil then return math.floor(r * a) + 1 end
    return a + math.floor(r * (b - a + 1))
end"""


# ---------------------------------------------------------------- helix start and speed


@pytest.mark.parametrize("style", ["stream", "popstream"])
@pytest.mark.parametrize("setting, half", [("off", 8), ("wide", 18)])
@pytest.mark.parametrize("bar", [None, (0.85 * W, 0.97 * H)])
def test_helix_starts_on_a_short_line_across_the_flight(env, style, setting, half, bar):
    env.lua.execute(LCG_SOURCE)
    g = make(env, fixed_random=False)
    if bar:
        pin_destination(g, *bar)
    dx, dy = tuple(g.ns.Target.GetDestination(g.ns.Target))[:2]
    g.db.unknownOrigin = setting
    opts = dict(n=30, x=900, y=500, ex=900, ey=500, est="default", kind="kill", style=style, path="helix")
    if style == "popstream":
        opts["plate"] = restricted_plate(g, cx=700, cy=400)
    burst(g, **opts)
    recs = live_recs_of(g)
    assert len(recs) == 30
    length = math.hypot(dx - 900, dy - 500)
    ax, ay = (dx - 900) / length, (dy - 500) / length
    across = [-(o.x0 - 900) * ay + (o.y0 - 500) * ax for o in recs]
    along = [(o.x0 - 900) * ax + (o.y0 - 500) * ay for o in recs]
    assert all(abs(v) <= half + 1e-6 for v in across) and all(abs(v) <= 2 + 1e-6 for v in along)
    assert max(abs(v) for v in across) > half * 0.6  # it really uses the width


def arrival_angle(g, o, om):
    """Degrees from straight up of the heading over the last 4 % of the base curve (smooth path)."""
    dx, dy = tuple(g.ns.Target.GetDestination(g.ns.Target))[:2]
    c2 = tuple(om.HomeControl(o.control1X, o.control1Y, dx, dy, o.flightDist, o.bowX, o.bowY))
    c2 = tuple(om.ClampToScreen(*c2, o.screenW, o.screenH, o.clampMargin, dx, dy))
    ease = om.PopEase
    a = tuple(om.Cubic(ease(0.96, 0.5), o.x0, o.y0, o.control1X, o.control1Y, *c2, dx, dy))
    b = tuple(om.Cubic(ease(1.0, 0.5), o.x0, o.y0, o.control1X, o.control1Y, *c2, dx, dy))
    return math.degrees(math.atan2(abs(b[0] - a[0]), b[1] - a[1]))


@pytest.mark.parametrize("bar", [(0.85 * W, 0.97 * H), (0.3 * W, H - 2)], ids=["top-right", "top-edge"])
def test_orbs_rise_into_a_top_bar_instead_of_sliding_in_along_the_edge(env, bar):
    env.lua.execute(LCG_SOURCE)
    g = make(env, fixed_random=False)
    pin_destination(g, *bar)
    burst(g, n=10, x=0.5 * W, y=0.5 * H, ex=0.5 * W, ey=0.5 * H, kind="kill", style="stream", path="smooth")
    recs = live_recs_of(g)
    angles = [arrival_angle(g, o, g.ns.OrbMath) for o in recs]
    assert len(angles) == 10 and max(angles) < 30, angles


def test_helix_pop_ring_is_widened_horizontally(env):
    env.lua.execute(LCG_SOURCE)
    g = make(env, fixed_random=False)
    for setting, widen in (("off", 1.4), ("wide", 1.6)):
        g.db.unknownOrigin = setting
        burst(g, n=20, x=900, y=500, ex=900, ey=500, est="default", kind="kill", style="streampop", path="helix")
        for o in live_recs_of(g):
            ring = math.hypot((o.ringX - o.px) / widen, o.ringY - o.py)
            assert 18 * 0.5 - 1e-6 <= ring <= 30 * 0.5 + 1e-6
        g.tick(0.05, 80)


def test_helix_flies_twenty_percent_slower(om):
    low, span = tuple(om.PathShape("helix"))[2:4]
    assert (low, span) == pytest.approx((0.97 * 1.25, 0.06 * 1.25))
