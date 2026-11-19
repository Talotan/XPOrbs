"""v0.9: corpse pop + stream, target-frame stream origin, plate measuring shutdown, kills wiring."""

import math

import pytest
from conftest import TESTS, lua_list
from test_plates_stub import Game


def OWN(g, a, b):
    return g.env.lua.eval("rawequal")(a, b)


def make(env, probe=False, fixed_random=True, trail=False):
    if fixed_random:
        env.lua.execute("math.random = function() return 0.5 end")
    env.load_chunk(TESTS / "stubs_m2.lua", "stubs_m2.lua")(env.ns)
    g = Game(env, probe=probe)
    env.load_chunk(TESTS / "stubs_v09.lua", "stubs_v09.lua")(env.ns)
    g.stub.makeBar("MainStatusTrackingBarContainer", 400, 20, 800, 10, True)
    g.orbs = env.ns.Orbs
    g.db.trail = trail
    g.slash = env.G.SlashCmdList.XPORBS
    return g


def burst(g, **kw):
    return g.orbs.Burst(g.orbs, g.env.lua.table_from(kw))


def restricted_plate(g, unit="nameplate1", hostile=False, **opts):
    opts["canAttack"] = hostile
    return g.stub.addRestrictedPlate(unit, g.env.lua.table_from(opts))


def chat_lines(g):
    return [str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1)]


def textures(g):
    return [f for f in g.stub.frames.values() if f.kind == "Texture"]


def pop_frames(g):
    """Every pop frame ever created by Orbs.lua."""
    return lua_list(g.stub.popFrames())


def pop_textures(g):
    return lua_list(g.stub.texturesByOwner(True))


def stream_textures(g, shown=True):
    return [t for t in lua_list(g.stub.texturesByOwner(False)) if (t.shown or not shown) and len(t.points) > 0]


def set_level(g, level, max_level):
    g.env.lua.execute(
        f"UnitLevel = function() return {level} end; GetMaxPlayerLevel = function() return {max_level} end"
    )


# ---------------------------------------------------------------- pop


def test_burst_with_plate_pops_and_streams(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    assert burst(g, plate=plate, n=5, x=300, y=300, kind="kill") == "pop+stream"
    (G,) = pop_frames(g)
    assert len(G.points) == 1
    pt = G.points[1]
    assert (
        pt[1] == "CENTER"
        and OWN(g, pt[2], plate)
        and pt[3] == "CENTER"
        and (pt[4], pt[5]) == (0, -20)  # POP_Y
    )
    assert G.shown
    g.stub.tick(0.1)
    texs = pop_textures(g)
    assert len(texs) == 5 * 3
    for t in texs:
        assert (
            len(t.points) == 1
            and OWN(g, t.points[1][2], G)
            and t.points[1][1] == "CENTER"
        )
    assert g.stub.restrictedHits == 0


def test_pop_count_is_capped_at_12(env):
    g = make(env)
    plate = restricted_plate(g)
    burst(g, plate=plate, n=30, kind="kill")
    g.stub.tick(0.1)
    assert len([t for t in pop_textures(g) if t.shown]) == 12 * 3


def test_small_pop_uses_n_orbs(env):
    g = make(env)
    plate = restricted_plate(g)
    burst(g, plate=plate, n=3, kind="kill")
    g.stub.tick(0.1)
    assert len([t for t in pop_textures(g) if t.shown]) == 9


def test_pop_motion_and_cleanup(env):
    g = make(env)
    plate = restricted_plate(g)
    burst(g, plate=plate, n=1, kind="kill")
    (G,) = pop_frames(g)
    g.stub.tick(0.2)
    orb = [t for t in pop_textures(g) if t.shown]
    assert len(orb) == 3
    assert all(math.hypot(t.points[1][4], t.points[1][5]) > 5 for t in orb)
    assert any(
        t.alpha == pytest.approx(1) for t in orb
    )  # full alpha before the fade window
    g.stub.tick(0.4)  # 0.6 s > POP_TIME (0.55)
    assert not any(t.shown for t in pop_textures(g))
    assert G.shown is False and len(G.points) == 0
    assert g.orbs.PopInfo(g.orbs)[0] == 0
    assert g.stub.restrictedHits == 0


def test_driver_idle_after_pop_and_stream(env):
    g = make(env)
    plate = restricted_plate(g)
    burst(g, plate=plate, n=6, kind="kill")
    assert g.orbs.driver.scripts.OnUpdate is not None
    for _ in range(40):
        g.stub.tick(0.05)
    active, in_use, _, _ = g.orbs.Info(g.orbs)
    assert not active and in_use == 0 and g.orbs.driver.scripts.OnUpdate is None
    assert g.orbs.PopInfo(g.orbs)[0] == 0 and g.stub.shownTextures() == 0


def test_never_measures_pop_frame_or_textures(env):
    g = make(env, fixed_random=False, trail=True)
    plate = restricted_plate(g)
    for _ in range(3):
        burst(g, plate=plate, n=20, kind="kill")
        for _ in range(30):
            g.stub.tick(0.03)
    assert g.stub.restrictedHits == 0
    assert pop_frames(g)


def test_stub_refuses_second_anchor_on_restricted_family(env):
    g = make(env)
    plate = restricted_plate(g)
    f = g.env.lua.eval(
        "function(p) local f = CreateFrame('Frame'); f:SetPoint('CENTER', p, 'CENTER', 0, 0); return f end"
    )(plate)
    with pytest.raises(Exception, match="anchor family"):
        f.SetPoint(f, "BOTTOMLEFT", g.env.G.UIParent, "BOTTOMLEFT", 0, 0)


def test_stream_delay_only_with_pop(env):
    g = make(env)
    plate = restricted_plate(g)
    # fixed random 0.5: base delay = 0.5 * 0.15 = 0.075 s; with a pop it is 0.5 * 0.08 + 0.30 = 0.34 s
    assert burst(g, n=1, x=300, y=300, kind="kill") == "stream"
    g.stub.tick(0.1)
    assert (
        len(stream_textures(g)) == 3
    )  # no pop: the stream orb is already drawn at 0.1 s
    g.stub.tick(3)
    assert burst(g, plate=plate, n=1, x=300, y=300, kind="kill") == "pop+stream"
    g.stub.tick(0.1)
    assert len(stream_textures(g)) == 0  # 0.1 < 0.34
    g.stub.tick(0.25)
    assert len(stream_textures(g)) == 3


def test_pop_frame_cap_skips_ninth_pop_but_streams(env):
    g = make(env)
    plates = [restricted_plate(g, f"nameplate{i}") for i in range(1, 10)]
    modes = [burst(g, plate=p, n=2, kind="kill") for p in plates]
    assert modes[:8] == ["pop+stream"] * 8 and modes[8] == "stream"
    assert tuple(g.orbs.PopInfo(g.orbs))[:2] == (8, 8)
    assert len(pop_frames(g)) == 8
    for _ in range(20):
        g.stub.tick(0.05)
    assert g.orbs.PopInfo(g.orbs)[0] == 0
    assert (
        burst(g, plate=plates[0], n=2, kind="kill") == "pop+stream"
    )  # pooled frames are reused
    assert len(pop_frames(g)) == 8


def test_ninth_pop_stream_still_runs(env):
    g = make(env)
    plates = [restricted_plate(g, f"nameplate{i}") for i in range(1, 10)]
    for p in plates[:8]:
        burst(g, plate=p, n=1, kind="kill")
    g.stub.tick(3)  # let the first eight finish; make the ninth the only one in flight
    for p in plates[:8]:
        burst(g, plate=p, n=1, kind="kill")
    before = g.orbs.Info(g.orbs)[1]
    assert burst(g, plate=plates[8], n=1, x=300, y=300, kind="kill") == "stream"
    assert g.orbs.Info(g.orbs)[1] == before + 3  # its stream orb got textures


def test_plate_reused_fades_only_that_plates_pop(env):
    g = make(env)
    p1 = restricted_plate(g, "nameplate1")
    p2 = restricted_plate(g, "nameplate2")
    burst(g, plate=p1, n=3, kind="kill")
    burst(g, plate=p2, n=3, kind="kill")
    g.stub.tick(0.1)
    assert g.orbs.PopInfo(g.orbs)[0] == 2
    g.orbs.PlateReused(g.orbs, p1)
    g.stub.tick(0.04)
    assert g.orbs.PopInfo(g.orbs)[0] == 2  # still fading
    g.stub.tick(0.07)  # past 0.1 s
    assert g.orbs.PopInfo(g.orbs)[0] == 1
    g.stub.tick(1)
    assert g.orbs.PopInfo(g.orbs)[0] == 0


def test_nameplate_added_calls_plate_reused(env):
    g = make(env)
    seen = g.env.lua.table()
    g.ns.Orbs = g.env.lua.eval(
        "function(seen) return { PlateReused = function(_, p) seen[#seen + 1] = p end } end"
    )(seen)
    plate = g.plate(guid="G1")
    assert len(seen) == 1 and OWN(g, seen[1], plate)


def test_corpse_pop_off_means_no_pop(env):
    g = make(env)
    g.db.style = "stream"
    plate = restricted_plate(g)
    assert burst(g, plate=plate, n=3, kind="kill") == "stream"
    assert pop_frames(g) == []


def test_kind_other_streams_from_centre_without_pop(env):
    g = make(env)
    plate = restricted_plate(g)
    # v1.0.2: no origin given -> the centre; an explicit x/y is honoured (see test_v102)
    assert burst(g, plate=plate, n=2, kind="other") == "stream"
    assert pop_frames(g) == []
    g.stub.tick(0.2)
    pts = [t.points[1] for t in stream_textures(g)]
    assert pts and all(
        abs(p[4] - 960) < 100 for p in pts
    )  # near the centre (x=960), not x=100


def test_secret_plate_is_not_used(env):
    g = make(env)
    assert burst(g, plate=g.stub.SECRET, n=2, kind="kill") == "stream"


def test_burst_requires_positive_n(env):
    g = make(env)
    assert burst(g, n=0) is None


# ---------------------------------------------------------------- /xporbs test and /xporbs pop


def test_test_command_with_target_plate_pops_and_streams_from_estimate(env):
    g = make(env)
    plate = restricted_plate(g)
    g.stub.plates["target"] = plate
    g.stub.setTargetFrame(250, 900)
    g.slash("test 5")
    assert chat_lines(g)[-1].endswith("pop=yes stream=estimate style=popstream/nameplate")
    assert len(pop_frames(g)) == 1
    g.stub.tick(0.4)
    pts = [t.points[1] for t in stream_textures(g)]
    assert pts and all(abs(p[4] - 960) < 300 for p in pts)  # v0.11: the stream starts at P-hat, not the portrait


def test_test_command_without_plate_streams_from_estimate(env):
    g = make(env)
    g.stub.cursor.x, g.stub.cursor.y = 200, 300
    g.slash("test 1")
    assert chat_lines(g)[-1].endswith("pop=no stream=estimate style=stream")
    assert pop_frames(g) == []


def test_test_command_estimate_even_without_a_cursor(env):
    g = make(env)
    g.env.lua.execute("GetCursorPosition = nil")
    g.slash("test 1")
    assert chat_lines(g)[-1].endswith("pop=no stream=estimate style=stream")


def test_test_command_ignores_frame_and_plate_words(env):
    g = make(env)
    g.stub.setTargetFrame(250, 900)
    g.slash("test 5 frame")
    assert "stream=estimate" in chat_lines(g)[-1]
    g.stub.tick(3)
    g.slash("test 5 rested plate")
    last = chat_lines(g)[-1]
    assert "(7 purple)" in last and "stream=estimate" in last


def test_style_and_pop_commands_persist_and_toggle(env):
    g = make(env)
    assert g.db.style == "popstream" and g.db.corpsePop is None
    g.slash("style crossfade")
    assert g.db.style == "crossfade" and "Crossfade" in chat_lines(g)[-1]
    g.slash("style bogus")
    assert g.db.style == "crossfade" and "use popstream [nameplate|direct], crossfade or stream" in chat_lines(g)[-1]
    g.slash("style")
    assert "kill style: Crossfade" in chat_lines(g)[-1]
    g.slash("pop off")
    assert g.db.style == "stream"
    plate = restricted_plate(g)
    g.stub.plates["target"] = plate
    g.slash("test 1")
    assert "pop=no" in chat_lines(g)[-1] and "style=stream" in chat_lines(g)[-1]
    g.slash("pop on")
    assert g.db.style == "popstream"
    g.slash("pop bogus")
    assert g.db.style == "popstream" and "use on or off" in chat_lines(g)[-1]


def test_status_shows_pop_and_no_anchor_line(env):
    g = make(env)
    g.slash("status")
    lines = chat_lines(g)
    assert any(
        "orbs: driver=" in ln and "style=popstream" in ln and "pops=0" in ln
        for ln in lines
    )
    # the old origin "anchor:" line stays gone; only the zoom anchor line (p2) may use the word
    assert not any("anchor:" in ln and "anchor: zoom=" not in ln for ln in lines)
    assert not any("origin=" in ln for ln in lines)


def test_old_commands_are_gone(env):
    g = make(env)
    g.slash("origin plate")
    g.slash("lab")
    lines = chat_lines(g)
    assert any("unknown command 'origin'" in ln for ln in lines)
    assert any("unknown command 'lab'" in ln for ln in lines)
    g.slash("help")
    helptext = "\n".join(chat_lines(g)).split("commands:")[-1]
    assert "lab" not in helptext and "origin" not in helptext
    assert "/xporbs pop on|off" in helptext


# ---------------------------------------------------------------- Kills end to end


def kill_with_secret_pos_plate(g):
    secret = g.stub.SECRET
    plate = g.plate(guid="G1", name="Boar", cx=secret, cy=secret)
    g.tick(0.05)
    g.ns.fire("UNIT_DIED", "G1")
    g.chat()
    g.tick(0.1)
    return plate


def test_tier1_kill_with_plate_hidden_target_frame_uses_estimate(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900, False)  # hidden: the mob was deselected on death
    plate = kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    # no mouseover sample: P-hat is the default point (W/2, 0.58 H); the cursor (stub default 960, 540) has weight 0
    assert (b["x"], b["y"]) == (pytest.approx(960), pytest.approx(1080 * 0.58))
    assert (b["ex"], b["ey"]) == (b["x"], b["y"]) and OWN(g, b["plate"], plate)
    assert b["n"] == 14 and b["kind"] == "kill" and b["nPurple"] == 0
    assert g.has_log("origin=estimate plate=yes est=default w=0.00")


def test_tier1_kill_with_plate_visible_target_frame_still_uses_estimate(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900, True)
    plate = kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (pytest.approx(960), pytest.approx(1080 * 0.58)) and OWN(g, b["plate"], plate)
    assert g.has_log("origin=estimate plate=yes est=default w=0.00")


def test_kill_real_orbs_pop_and_stream_end_to_end(env):
    g = make(env)
    g.stub.setTargetFrame(250, 900)
    g.db.cap = 40
    kill_with_secret_pos_plate(g)
    assert len(pop_frames(g)) == 1
    for _ in range(60):
        g.tick(0.05)
    assert g.stub.restrictedHits == 0
    assert not g.orbs.Info(g.orbs)[0]


def test_kill_without_target_frame_uses_estimate(env):
    g = make(env)
    g.fake_orbs_on()
    kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert b["x"] == 960 and b["y"] == pytest.approx(626.4) and g.has_log("origin=estimate plate=yes")


def test_kill_without_any_plate_no_pop(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900)
    g.chat()  # tier 4, no plate at all
    g.tick(0.6)
    (b,) = g.bursts()
    assert (
        b["plate"] is None
        and (b["x"], b["y"]) == (pytest.approx(960), pytest.approx(626.4))
        and g.has_log("origin=estimate plate=no")
    )


def test_tier4_uses_target_plate(env):
    g = make(env)
    g.fake_orbs_on()
    plate = g.plate(guid="G1", cx=1, cy=1)
    g.stub.plates["target"] = plate
    g.stub.units["target"] = g.env.lua.table_from({"dead": True})  # v1.0.2: only a dead target's plate is used
    g.chat()
    g.tick(0.6)
    (b,) = g.bursts()
    assert OWN(g, b["plate"], plate) and g.has_log("plate=yes")


def test_corpse_pop_off_passes_no_plate(env):
    g = make(env)
    g.fake_orbs_on()
    g.db.style = "stream"
    kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert b["plate"] is None and g.has_log("plate=no")


def test_disabled_suppresses_bursts(env):
    g = make(env)
    g.fake_orbs_on()
    g.db.enabled = False
    kill_with_secret_pos_plate(g)
    assert g.bursts() == [] and g.has_log("BURST tier=1 kind=kill")


def test_max_level_no_longer_suppresses_bursts(env):
    # v1.0.2: the emit-time gate is gone. The game pays no XP at the cap, so it only ever ate the burst of the gain
    # that reached max level (PLAYER_LEVEL_UP has already run by then). The showAtMax setting itself stays (1.1.0).
    g = make(env)
    g.fake_orbs_on()
    set_level(g, 70, 70)
    assert g.db.showAtMax is False
    kill_with_secret_pos_plate(g)
    assert len(g.bursts()) == 1
    g.stub.plates["nameplate1"] = None
    g.stub.addPlate(
        "nameplate2",
        g.env.lua.table_from({"guid": "G2", "name": "Boar", "cx": 1, "cy": 1}),
    )
    g.tick(0.05)
    g.ns.fire("UNIT_DIED", "G2")
    g.chat()
    g.tick(0.1)
    assert len(g.bursts()) == 2
    assert g.db.showAtMax is False


def test_quest_burst_from_screen_centre_without_plate(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setXP(100, 1000)
    g.tick(0.6)
    (b,) = g.bursts()
    assert b["kind"] == "other" and b["plate"] is None
    assert (b["x"], b["y"]) == (960, pytest.approx(1080 * 0.65))  # v1.0.2: 65% of the height (was 55%)
    assert g.has_log("kind=other") and g.has_log("origin=centre plate=no")


def test_quest_bursts_gated_by_option(env):
    g = make(env)
    g.fake_orbs_on()
    g.db.questBursts = False
    g.stub.setXP(100, 1000)
    g.tick(0.6)
    assert g.bursts() == [] and g.has_log("kind=other")


def test_killmatcher_passes_plate_through(env):
    env.load_addon()
    t = [0.0]
    m = env.ns.KillMatcher.New(env.lua.table_from({"now": lambda: t[0]}))
    plate = env.lua.table()
    m.AddDeath(m, env.lua.table_from({"tier": 1, "plate": plate}))
    m.AddKillXP(m, env.lua.table_from({"amount": 10}))
    (b,) = lua_list(m.Poll(m))
    assert env.lua.eval("rawequal")(b.plate, plate) and b.x is None and b.tier == 1


# ---------------------------------------------------------------- target frame origin


def origin_of(g):
    return g.ns.Target.TargetFrameOrigin(g.ns.Target)


def new_frame(g, cx, cy, scale=1):
    fn = g.env.lua.eval(
        "function(cx, cy, s) local f = CreateFrame('Frame'); f.cx, f.cy, f.scale = cx, cy, s; return f end"
    )
    return fn(cx, cy, scale)


def test_target_frame_origin_reads_portrait_even_hidden(env):
    g = make(env)
    assert origin_of(g) is None
    portrait = g.stub.setTargetFrame(250, 900)
    assert tuple(origin_of(g)) == (250, 900)
    portrait.scale = 0.5
    assert tuple(origin_of(g)) == (125, 450)
    portrait.shown = False
    g.env.G.TargetFrame.shown = False
    assert tuple(origin_of(g)) == (125, 450)


def test_target_frame_origin_candidate_order(env):
    g = make(env)
    g.env.G.TargetFrame = new_frame(g, 100, 200)
    assert tuple(origin_of(g)) == (100, 200)
    g.env.G.TargetFramePortrait = new_frame(g, 300, 400, 0.5)
    assert tuple(origin_of(g)) == (150, 200)
    portrait = g.stub.setTargetFrame(250, 900)
    assert tuple(origin_of(g)) == (250, 900)
    g.stub.failMeasure(portrait)
    assert tuple(origin_of(g)) == (150, 200)


def test_target_frame_origin_cache_and_secret_values(env):
    g = make(env)
    portrait = g.stub.setTargetFrame(250, 900)
    assert tuple(origin_of(g)) == (250, 900)
    g.stub.failMeasure(portrait)
    g.stub.failMeasure(g.env.G.TargetFrame)
    assert tuple(origin_of(g)) == (250, 900)
    g.stub.clearTargetFrame()
    assert tuple(origin_of(g)) == (250, 900)
    portrait.cx = g.stub.SECRET
    assert tuple(origin_of(g)) == (250, 900)


def test_target_plate_helper(env):
    g = make(env)
    assert g.ns.Target.TargetPlate(g.ns.Target) is None
    plate = restricted_plate(g)
    g.stub.plates["target"] = plate
    assert OWN(g, g.ns.Target.TargetPlate(g.ns.Target), plate)


# ---------------------------------------------------------------- crossfade style


XF_HOLD, STAGGER_POP = 0.22, 0.08  # the crossfade timeline now lives in test_p2_crossfade.py


def test_crossfade_cleanup_and_idle_and_no_measuring(env):
    g = make(env, fixed_random=False, trail=True)
    plate = restricted_plate(g)
    burst(g, plate=plate, n=15, kind="kill", style="crossfade")
    (G,) = pop_frames(g)
    for _ in range(100):  # the whole crossfade (bloom, leave, gap, 0.45 x flight) is over well within 3 s
        g.stub.tick(0.03)
    assert g.stub.restrictedHits == 0
    assert G.shown is False and len(G.points) == 0
    assert not any(t.shown for t in pop_textures(g))
    active, in_use, _, _ = g.orbs.Info(g.orbs)
    assert not active and in_use == 0 and g.orbs.driver.scripts.OnUpdate is None
    assert g.orbs.PopInfo(g.orbs)[0] == 0
    # the frame is pooled and reused
    burst(g, plate=plate, n=2, kind="kill", style="crossfade")
    assert len(pop_frames(g)) == 1


def test_crossfade_plate_reused_fades_copy_a_only(env):
    g = make(env)
    p1 = restricted_plate(g, "nameplate1")
    burst(g, plate=p1, n=1, kind="kill", style="crossfade")
    g.stub.tick(0.5 * STAGGER_POP + 0.1)  # mid-bloom: copy A fully visible
    a_orb = [t for t in pop_textures(g) if t.calls["SetDrawLayer"][2] == 0][0]
    assert a_orb.alpha > 0.9
    g.orbs.PlateReused(g.orbs, p1)
    g.stub.tick(0.12)  # > 0.1 s fade
    assert not any(t.shown for t in pop_textures(g))
    g.stub.tick(0.5)  # copy B carries on to the bar
    assert len(stream_textures(g)) > 0 or not g.orbs.Info(g.orbs)[0]
    g.stub.tick(2)
    assert not g.orbs.Info(g.orbs)[0]


def test_crossfade_falls_back_to_stream_without_plate_or_frame(env):
    g = make(env)
    assert burst(g, n=3, x=300, y=300, kind="kill", style="crossfade") == "stream"
    assert pop_frames(g) == []
    g.stub.tick(0.2)
    # plain stream from (300, 300), not from the estimated mob position at the centre
    assert stream_textures(g) and all(t.points[1][4] < 700 for t in stream_textures(g))
    g.stub.tick(3)
    plates = [restricted_plate(g, f"nameplate{i}") for i in range(1, 10)]
    modes = [burst(g, plate=p, n=2, kind="kill", style="crossfade") for p in plates]
    assert modes[:8] == ["crossfade"] * 8 and modes[8] == "stream"


def test_crossfade_kind_other_and_secret_plate_stream(env):
    g = make(env)
    plate = restricted_plate(g)
    assert burst(g, plate=plate, n=2, kind="other", style="crossfade") == "stream"
    assert burst(g, plate=g.stub.SECRET, n=2, kind="kill", style="crossfade") == "stream"
    assert pop_frames(g) == []


def test_crossfade_style_from_db_and_kills_pass_plate(env):
    g = make(env)
    g.db.style = "crossfade"
    g.stub.setTargetFrame(250, 900)
    kill_with_secret_pos_plate(g)
    assert len(pop_frames(g)) == 1
    assert g.has_log("plate=yes")
    assert g.has_log("origin=estimate plate=yes")  # v0.11: crossfade flies from P-hat, so the log says so
    for _ in range(60):
        g.tick(0.05)
    assert g.stub.restrictedHits == 0 and not g.orbs.Info(g.orbs)[0]


def test_test_command_style_word_forces_style(env):
    g = make(env)
    plate = restricted_plate(g)
    g.stub.plates["target"] = plate
    g.stub.setTargetFrame(250, 900)
    g.slash("test 5 crossfade")
    assert chat_lines(g)[-1].endswith("pop=no stream=estimated style=crossfade")
    g.stub.tick(3)
    g.slash("test 5 stream rested")
    assert "style=stream" in chat_lines(g)[-1] and "(7 purple)" in chat_lines(g)[-1]
    g.stub.tick(3)
    g.db.style = "crossfade"
    g.slash("test 5")
    assert chat_lines(g)[-1].endswith("style=crossfade")
    g.stub.tick(3)
    g.slash("test 5 popstream")
    assert chat_lines(g)[-1].endswith("pop=yes stream=estimate style=popstream/nameplate")


def test_stream_kills_pass_no_plate(env):
    g = make(env)
    g.fake_orbs_on()
    g.db.style = "stream"
    kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert b["plate"] is None
