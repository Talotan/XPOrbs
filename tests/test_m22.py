"""M2.2: anchored origin (plates we can't measure), target-frame origin, plate measuring shutdown."""

import math
import random

import pytest
from conftest import TESTS, lua_list
from test_plates_stub import Game

OWN = lambda g, a, b: g.env.lua.eval("rawequal")(a, b)  # noqa: E731


def make(env, probe=True, fixed_random=True):
    if fixed_random:
        env.lua.execute("math.random = function() return 0.5 end")
    env.load_chunk(TESTS / "stubs_m2.lua", "stubs_m2.lua")(env.ns)
    g = Game(env, probe=probe)
    env.load_chunk(TESTS / "stubs_m22.lua", "stubs_m22.lua")(env.ns)
    g.stub.makeBar("MainStatusTrackingBarContainer", 400, 20, 800, 10, True)
    g.orbs = env.ns.Orbs
    g.db.trail = False
    g.slash = env.G.SlashCmdList.XPORBS
    return g


def burst(g, **kw):
    g.orbs.Burst(g.orbs, g.env.lua.table_from(kw))


def restricted_plate(g, unit="nameplate1", hostile=False, **opts):
    opts["canAttack"] = hostile
    return g.stub.addRestrictedPlate(unit, g.env.lua.table_from(opts))


def bars(g):
    return lua_list(g.stub.statusBars())


def chat_lines(g):
    return [str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1)]


# ---------------------------------------------------------------- OrbMath


def test_anchored_weights_match_explicit_bezier(env):
    env.load_addon()
    om = env.ns.OrbMath
    rng = random.Random(7)
    for _ in range(200):
        e = rng.random()
        s = (rng.uniform(-6, 6), rng.uniform(-6, 6))
        o = (rng.uniform(-250, 250), rng.uniform(-250, 250))
        d = (rng.uniform(0, 1920), rng.uniform(0, 100))
        lift = rng.uniform(50, 400)
        a, kx, ky = om.AnchoredWeights(e, s[0], s[1], o[0], o[1], d[0], d[1], lift)
        for _ in range(3):
            px, py = rng.uniform(0, 1920), rng.uniform(0, 1080)
            p0 = (px + s[0], py + s[1])
            c1 = (px + o[0], py + o[1])
            c2 = (d[0] + 0.15 * (c1[0] - d[0]), d[1] + 0.15 * (c1[1] - d[1]) + lift)
            bx, by = om.Cubic(e, p0[0], p0[1], c1[0], c1[1], c2[0], c2[1], d[0], d[1])
            assert a * px + kx == pytest.approx(bx, abs=1e-9)
            assert a * py + ky == pytest.approx(by, abs=1e-9)


def test_anchored_weights_endpoints_and_monotonic(env):
    env.load_addon()
    om = env.ns.OrbMath
    assert om.AnchoredWeights(0, 1, 2, 3, 4, 5, 6, 7)[0] == pytest.approx(1)
    assert om.AnchoredWeights(1, 1, 2, 3, 4, 5, 6, 7)[0] == pytest.approx(0)
    vals = [om.AnchoredWeights(i / 20, 1, 2, 3, 4, 5, 6, 7)[0] for i in range(21)]
    assert all(b <= a + 1e-12 for a, b in zip(vals, vals[1:]))


# ---------------------------------------------------------------- anchored bursts


def expected_at(g, p_time, n_total=1):
    """Expected (a, kx, ky) for the single orb of a fixed-random burst after p_time seconds of ticks."""
    om = g.ns.OrbMath
    delay, dur = 0.5 * 0.15, 0.75
    p = (p_time - delay) / dur
    e = om.PopEase(p)
    rad = 6 * math.sqrt(0.5)
    sx, sy = math.cos(math.pi) * rad, math.sin(math.pi) * rad
    ox, oy, _ = om.PopControl(1, 1, 0, 0, lambda: 0.5)
    dx, dy, _ = g.ns.Target.GetDestination(g.ns.Target)
    lift = 0.30 * max(150, 1080 * 0.55 - dy)
    return om.AnchoredWeights(e, sx, sy, ox, oy, dx, dy, lift)


def find(g, kind):
    return [f for f in g.stub.frames.values() if f.kind == kind]


def orb_textures(g):
    return [
        f
        for f in find(g, "Texture")
        if f.calls and "SetTexture" in f.calls and len(f.points) > 0
    ]


def test_burst_with_plate_wires_burst_frame_and_chain(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    burst(g, plate=plate, n=1)
    (R,) = [
        f
        for f in find(g, "Frame")
        if len(f.points) == 2
        and f.points[2][2] is not None
        and OWN(g, f.points[2][2], plate)
    ]
    assert list(R.points[1].values()) == [
        "BOTTOMLEFT",
        g.env.G.UIParent,
        "BOTTOMLEFT",
        0,
        0,
    ] or (
        R.points[1][1] == "BOTTOMLEFT"
        and OWN(g, R.points[1][2], g.env.G.UIParent)
        and R.points[1][3] == "BOTTOMLEFT"
    )
    assert (
        R.points[2][1] == "TOPRIGHT"
        and R.points[2][3] == "CENTER"
        and R.points[2][4] == 0
        and R.points[2][5] == 0
    )
    vbar, hbar = bars(g)
    assert vbar.orientation == "VERTICAL" and hbar.orientation == "HORIZONTAL"
    assert (vbar.minValue, vbar.maxValue) == (
        0,
        1,
    ) and vbar.statusBarPath == "Interface\\Buttons\\WHITE8X8"
    assert OWN(g, vbar.allPoints, R) and OWN(g, vbar.createdParent, R)
    (M,) = [
        f
        for f in find(g, "Frame")
        if len(f.points) == 2
        and f.points[2][2] is not None
        and OWN(g, f.points[2][2], vbar.fill)
    ]
    assert (
        M.points[1][1] == "BOTTOMLEFT"
        and OWN(g, M.points[1][2], R)
        and M.points[1][3] == "BOTTOMLEFT"
    )
    assert M.points[2][1] == "TOPRIGHT" and M.points[2][3] == "TOPRIGHT"
    assert OWN(g, hbar.allPoints, M)
    assert vbar.statusBarColor[4] == 0 and hbar.statusBarColor[4] == 0


def test_chain_values_and_texture_anchor_follow_weights(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    burst(g, plate=plate, n=1)
    g.stub.tick(0.45)  # p = (0.45 - 0.075) / 0.75 = 0.5
    a, kx, ky = expected_at(g, 0.45)
    vbar, hbar = bars(g)
    assert vbar.value == pytest.approx(a) and hbar.value == pytest.approx(a)
    texs = orb_textures(g)
    assert len(texs) == 3  # trail off: underlay, orb, sparkle
    for t in texs:
        pt = t.points[1]
        assert pt[1] == "CENTER" and OWN(g, pt[2], hbar.fill) and pt[3] == "TOPRIGHT"
        assert (pt[4], pt[5]) == (pytest.approx(kx), pytest.approx(ky))
        assert (
            t.restricted
        )  # sanity: the stub propagated the restriction to our regions
    assert g.stub.restrictedHits == 0  # and we never tried to measure any of them


def test_small_weight_anchors_to_uiparent(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    burst(g, plate=plate, n=1)
    g.stub.tick(0.075 + 0.75 * 0.999)
    a, kx, ky = expected_at(g, 0.075 + 0.75 * 0.999)
    assert a < 0.002
    for t in orb_textures(g):
        pt = t.points[1]
        assert OWN(g, pt[2], g.env.G.UIParent) and pt[3] == "BOTTOMLEFT"
        assert (pt[4], pt[5]) == (pytest.approx(kx), pytest.approx(ky))
    assert g.stub.restrictedHits == 0


def test_trail_uses_one_ghost_in_anchored_mode(env):
    g = make(env)
    g.db.trail = True
    plate = restricted_plate(g, cx=700, cy=400)
    burst(g, plate=plate, n=3)
    assert g.orbs.Info(g.orbs)[1] == 12  # 4 textures per orb
    assert g.orbs.AnchorInfo(g.orbs)[0] == 6  # 2 chains per orb
    g.stub.tick(0.5)
    assert g.stub.restrictedHits == 0
    g.stub.tick(3)
    assert g.orbs.Info(g.orbs)[1] == 0 and g.orbs.AnchorInfo(g.orbs)[0] == 0


def test_ten_anchored_bursts_stay_under_ceilings_and_drain(env):
    g = make(env, fixed_random=False)
    g.db.trail = True
    plate = restricted_plate(g, cx=700, cy=400)
    for _ in range(10):
        burst(g, plate=plate, n=40)
    _, in_use, created, ceiling = g.orbs.Info(g.orbs)
    c_in_use, c_created, c_ceiling, r_in_use, r_created = g.orbs.AnchorInfo(g.orbs)
    assert created <= ceiling and g.stub.allTextures() <= ceiling
    assert c_in_use <= c_ceiling and c_created <= c_ceiling
    assert r_created <= 3  # one per burst that actually got orbs
    assert len(g.stub.statusBars()) == 2 * c_created
    peak_bars = len(g.stub.statusBars())
    for _ in range(80):
        g.stub.tick(0.05)
        assert g.stub.allTextures() <= ceiling
    active, in_use, created2, _ = g.orbs.Info(g.orbs)
    assert not active and in_use == 0 and g.orbs.driver.scripts.OnUpdate is None
    c_in_use, c_created2, _, r_in_use, r_created2 = g.orbs.AnchorInfo(g.orbs)
    assert c_in_use == 0 and r_in_use == 0
    burst(g, plate=plate, n=40)  # reuses the pools
    assert len(g.stub.statusBars()) == peak_bars
    assert g.stub.restrictedHits == 0


def test_plate_reused_fades_only_that_plates_orbs(env):
    g = make(env)
    p1 = restricted_plate(g, "nameplate1", cx=700, cy=400)
    p2 = restricted_plate(g, "nameplate2", cx=900, cy=400)
    burst(g, plate=p1, n=3)
    burst(g, plate=p2, n=3)
    g.stub.tick(0.3)
    assert g.orbs.AnchorInfo(g.orbs)[0] == 6 and g.orbs.AnchorInfo(g.orbs)[3] == 2
    g.orbs.PlateReused(g.orbs, p1)
    g.stub.tick(0.05)
    assert g.orbs.AnchorInfo(g.orbs)[0] == 6  # still fading
    mid = [t.alpha for t in orb_textures(g) if t.alpha is not None and t.alpha > 0]
    assert mid
    g.stub.tick(0.12)  # past FADE_OUT = 0.15
    c_in_use, _, _, r_in_use, _ = g.orbs.AnchorInfo(g.orbs)
    assert c_in_use == 3 and r_in_use == 1
    g.stub.tick(3)
    assert g.orbs.AnchorInfo(g.orbs)[0] == 0 and not g.orbs.Info(g.orbs)[0]


def test_nameplate_added_calls_plate_reused(env):
    g = make(env)
    seen = g.env.lua.table()
    g.ns.Orbs = g.env.lua.eval(
        "function(seen) return { PlateReused = function(_, p) seen[#seen + 1] = p end } end"
    )(seen)
    plate = g.plate(guid="G1")
    assert len(seen) == 1 and OWN(g, seen[1], plate)


# ---------------------------------------------------------------- Plates: measuring shutdown


def test_plates_stop_measuring_after_20_double_errors(env):
    g = make(env)
    restricted_plate(g, hostile=True, guid="G1", name="Boar", cx=700, cy=400)
    plates = g.ns.Plates
    assert plates.measurable
    for _ in range(40):
        g.stub.tick(0.05)
    assert plates.measurable is False
    assert g.has_log("GEOM disabled: plates can't be measured (last error: ")
    assert sum("GEOM disabled" in line for line in g.log()) == 1
    err_a = plates.stats.errA
    for _ in range(10):
        g.stub.tick(0.05)
    assert plates.stats.errA == err_a  # no more futile measuring
    assert not plates.SamplerActive()  # guid readable, nothing left to retry
    g.slash("status")
    geom = [ln for ln in chat_lines(g) if ln.startswith("geom:") or "geom: " in ln]
    assert (
        geom
        and "measurable=no" in geom[0]
        and "lastErr=" in geom[0]
        and "measure" in geom[0].lower()
    )


def test_sampler_keeps_running_only_for_unreadable_guids(env):
    g = make(env)
    restricted_plate(g, hostile=True, name="Boar", cx=700, cy=400)
    for _ in range(40):
        g.stub.tick(0.05)
    assert g.ns.Plates.measurable is False
    assert g.ns.Plates.SamplerActive()  # still retrying the GUID
    g.stub.units["nameplate1"].guid = "G9"
    g.stub.tick(0.05)
    g.stub.tick(0.05)
    assert not g.ns.Plates.SamplerActive()


def test_measurable_plates_never_disabled(env):
    g = make(env)
    g.plate(guid="G1", cx=700, cy=400)
    for _ in range(60):
        g.stub.tick(0.05)
    assert g.ns.Plates.measurable is True


# ---------------------------------------------------------------- Kills origins


def kill_with_secret_pos_plate(g, probe_chat=True):
    secret = g.stub.SECRET
    plate = g.plate(guid="G1", name="Boar", cx=secret, cy=secret)
    g.tick(0.05)
    g.ns.fire("UNIT_DIED", "G1")
    g.chat()
    g.tick(0.1)
    return plate


def test_tier1_kill_with_plate_and_no_xy_bursts_anchored(env):
    g = make(env, probe=False)
    g.fake_orbs_on()
    plate = kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert b["x"] is None and b["y"] is None and OWN(g, b["plate"], plate)
    assert b["n"] == 14 and b["kind"] == "kill"
    assert g.has_log(
        "BURST tier=1 kind=kill amount=50 rested=nil hadXY=false origin=anchored probe=false"
    )


def test_tier1_kill_in_probe_mode_logs_only(env):
    g = make(env, probe=True)
    g.fake_orbs_on()
    kill_with_secret_pos_plate(g)
    assert g.bursts() == []
    assert g.has_log("origin=anchored probe=true")


def test_tier4_uses_target_plate_anchored(env):
    g = make(env, probe=False)
    g.fake_orbs_on()
    plate = g.plate(guid="G1", cx=1, cy=1)
    g.stub.plates["target"] = plate
    g.chat()
    g.tick(0.6)
    (b,) = g.bursts()
    assert OWN(g, b["plate"], plate) and b["x"] is None
    assert g.has_log("tier=4 kind=kill") and g.has_log("origin=anchored")


def test_killmatcher_passes_plate_through(env):
    env.load_addon()
    t = [0.0]
    m = env.ns.KillMatcher.New(env.lua.table_from({"now": lambda: t[0]}))
    plate = env.lua.table()
    m.AddDeath(m, env.lua.table_from({"tier": 1, "plate": plate}))
    m.AddKillXP(m, env.lua.table_from({"amount": 10}))
    (b,) = lua_list(m.Poll(m))
    assert OWN(
        Game.__new__(Game) if False else type("G", (), {"env": env})(), b.plate, plate
    )
    assert b.x is None and b.tier == 1


# ---------------------------------------------------------------- target frame origin


def test_target_frame_origin_reads_portrait(env):
    g = make(env)
    assert (
        g.ns.Target.TargetFrameOrigin(g.ns.Target) is None
    )  # no TargetFrame in the stub yet
    portrait = g.stub.setTargetFrame(250, 900)
    assert tuple(g.ns.Target.TargetFrameOrigin(g.ns.Target)) == (250, 900)
    portrait.scale = 0.5
    assert tuple(g.ns.Target.TargetFrameOrigin(g.ns.Target)) == (125, 450)
    portrait.shown = (
        False  # hidden portrait: falls back to the TargetFrame itself, which is shown
    )
    assert tuple(g.ns.Target.TargetFrameOrigin(g.ns.Target)) == (250, 900)
    g.env.G.TargetFrame.shown = False
    assert g.ns.Target.TargetFrameOrigin(g.ns.Target) is None


def test_targetframe_mode_prefers_frame_over_plate(env):
    g = make(env, probe=False)
    g.fake_orbs_on()
    g.db.origin = "targetframe"
    g.stub.setTargetFrame(250, 900)
    kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (250, 900) and b["plate"] is None
    assert g.has_log("origin=targetframe")


def test_targetframe_mode_without_frame_uses_plate(env):
    g = make(env, probe=False)
    g.fake_orbs_on()
    g.db.origin = "targetframe"
    plate = kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert OWN(g, b["plate"], plate) and g.has_log("origin=anchored")


def test_plate_mode_falls_back_to_target_frame_without_plate(env):
    g = make(env, probe=False)
    g.fake_orbs_on()
    g.stub.setTargetFrame(300, 800)
    g.chat()  # no death at all: tier 4
    g.tick(0.6)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (300, 800) and g.has_log("origin=targetframe")


def test_plate_mode_prefers_plate_over_frame(env):
    g = make(env, probe=False)
    g.fake_orbs_on()
    g.stub.setTargetFrame(300, 800)
    plate = kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert OWN(g, b["plate"], plate)


def test_centre_when_nothing_available(env):
    g = make(env, probe=False)
    g.fake_orbs_on()
    g.chat()
    g.tick(0.6)
    (b,) = g.bursts()
    assert b["plate"] is None and b["x"] == 960 and g.has_log("origin=centre")


# ---------------------------------------------------------------- /xporbs test and /xporbs origin


def test_test_command_anchors_to_target_plate(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.slash("test 1")
    assert "origin=target plate" in chat_lines(g)[-1]
    assert len(g.stub.statusBars()) > 0
    g.stub.tick(0.4)
    assert g.stub.restrictedHits == 0


def test_test_command_uses_cursor_without_target_plate(env):
    g = make(env)
    g.stub.cursor.x, g.stub.cursor.y = 200, 300
    g.slash("test 1")
    assert "origin=cursor" in chat_lines(g)[-1]
    assert len(g.stub.statusBars()) == 0


def test_test_command_frame_and_plate_words(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.stub.setTargetFrame(250, 900)
    g.slash("test 5 frame")
    assert "origin=target frame" in chat_lines(g)[-1] and len(g.stub.statusBars()) == 0
    g.stub.tick(3)
    g.slash("test 5 plate")
    assert "origin=target plate" in chat_lines(g)[-1] and len(g.stub.statusBars()) > 0
    g.stub.tick(3)
    g.slash("test 5 rested frame")
    last = chat_lines(g)[-1]
    assert "origin=target frame" in last and "(7 purple)" in last
    g.stub.tick(3)
    g.slash("test 5 frame rested")
    assert "origin=target frame" in chat_lines(g)[-1]


def test_test_command_default_follows_db_origin(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.stub.setTargetFrame(250, 900)
    g.slash("test 1")
    assert "origin=target plate" in chat_lines(g)[-1]
    g.stub.tick(3)
    g.db.origin = "targetframe"
    g.slash("test 1")
    assert "origin=target frame" in chat_lines(g)[-1]


def test_forced_plate_without_plate_does_not_use_frame(env):
    g = make(env)
    g.stub.setTargetFrame(250, 900)
    g.slash("test 1 plate")
    assert "origin=cursor" in chat_lines(g)[-1]


def test_origin_command_and_status(env):
    g = make(env)
    assert g.db.origin == "plate"
    g.slash("origin frame")
    assert g.db.origin == "targetframe" and "frame" in chat_lines(g)[-1]
    g.slash("origin plate")
    assert g.db.origin == "plate" and "plate" in chat_lines(g)[-1]
    g.slash("origin bogus")
    assert g.db.origin == "plate" and "use plate or frame" in chat_lines(g)[-1]
    g.slash("status")
    assert any("orbs: driver=" in ln and "origin=plate" in ln for ln in chat_lines(g))
    assert any("anchor: chains=" in ln for ln in chat_lines(g))
