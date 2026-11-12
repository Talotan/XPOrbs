"""v0.8: robust target-frame origin, kills live (M4 gating), anchor diagnostics, /xporbs lab."""

import pytest
from conftest import TESTS, lua_list
from test_m22 import (
    OWN,
    bars,
    burst,
    chat_lines,
    kill_with_secret_pos_plate,
    restricted_plate,
)
from test_m22 import make as make22


def make(env, **kw):
    g = make22(env, **kw)
    env.load_chunk(TESTS / "stubs_v08.lua", "stubs_v08.lua")(env.ns)
    return g


def set_level(g, level, max_level):
    g.env.lua.execute(
        f"UnitLevel = function() return {level} end; GetMaxPlayerLevel = function() return {max_level} end"
    )


def origin_of(g):
    return g.ns.Target.TargetFrameOrigin(g.ns.Target)


def new_frame(g, cx, cy, scale=1):
    fn = g.env.lua.eval(
        "function(cx, cy, s) local f = CreateFrame('Frame'); f.cx, f.cy, f.scale = cx, cy, s; return f end"
    )
    return fn(cx, cy, scale)


# ---------------------------------------------------------------- TargetFrameOrigin


def test_target_frame_origin_works_when_everything_is_hidden(env):
    g = make(env)
    portrait = g.stub.setTargetFrame(250, 900, False)
    g.env.G.TargetFrame.shown = False
    assert portrait.shown is False
    assert tuple(origin_of(g)) == (250, 900)


def test_target_frame_origin_candidate_order_and_scale(env):
    g = make(env)
    g.env.G.TargetFrame = new_frame(g, 100, 200)
    assert tuple(origin_of(g)) == (100, 200)  # TargetFrame itself is the last candidate
    g.env.G.TargetFramePortrait = new_frame(g, 300, 400, 0.5)
    assert tuple(origin_of(g)) == (150, 200)  # TargetFramePortrait beats TargetFrame
    portrait = g.stub.setTargetFrame(250, 900)  # replaces TargetFrame; container portrait beats the other two
    assert tuple(origin_of(g)) == (250, 900)
    g.stub.failMeasure(portrait)
    assert tuple(origin_of(g)) == (150, 200)  # an unreadable candidate falls through to the next


def test_target_frame_origin_returns_cache_when_measuring_fails(env):
    g = make(env)
    assert origin_of(g) is None  # nothing yet, nothing cached
    portrait = g.stub.setTargetFrame(250, 900)
    assert tuple(origin_of(g)) == (250, 900)
    g.stub.failMeasure(portrait)
    g.stub.failMeasure(g.env.G.TargetFrame)
    assert tuple(origin_of(g)) == (250, 900)  # cached
    g.stub.clearTargetFrame()
    assert tuple(origin_of(g)) == (250, 900)


def test_target_frame_origin_secret_values_use_cache(env):
    g = make(env)
    portrait = g.stub.setTargetFrame(250, 900)
    assert tuple(origin_of(g)) == (250, 900)
    portrait.cx = g.stub.SECRET
    g.env.G.TargetFrame.cx = g.stub.SECRET
    assert tuple(origin_of(g)) == (250, 900)


# ---------------------------------------------------------------- kills live


def test_kill_with_probe_off_bursts_from_target_frame(env):
    g = make(env, probe=False, origin="targetframe")
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900, False)  # hidden: the mob was deselected on death
    kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (250, 900) and b["plate"] is None
    assert b["n"] == 14 and b["kind"] == "kill" and b["nPurple"] == 0
    assert g.has_log("origin=targetframe probe=false")


def test_disabled_suppresses_bursts(env):
    g = make(env, probe=False, origin="targetframe")
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900)
    g.db.enabled = False
    kill_with_secret_pos_plate(g)
    assert g.bursts() == []
    assert g.has_log("BURST tier=1 kind=kill")  # still logged


def kill_second_mob(g):
    g.stub.plates["nameplate1"] = None
    g.stub.addPlate(
        "nameplate2",
        g.env.lua.table_from({"guid": "G2", "name": "Boar", "cx": 1, "cy": 1}),
    )
    g.tick(0.05)
    g.ns.fire("UNIT_DIED", "G2")
    g.chat()
    g.tick(0.1)


def test_max_level_suppresses_unless_show_at_max(env):
    g = make(env, probe=False, origin="targetframe")
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900)
    set_level(g, 70, 70)
    kill_with_secret_pos_plate(g)
    assert g.bursts() == []
    g.db.showAtMax = True
    kill_second_mob(g)
    assert len(g.bursts()) == 1


def test_below_max_level_allows_bursts(env):
    g = make(env, probe=False, origin="targetframe")
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900)
    set_level(g, 60, 70)
    kill_with_secret_pos_plate(g)
    assert len(g.bursts()) == 1


def test_only_one_level_api_available_skips_the_check(env):
    g = make(env, probe=False, origin="targetframe")
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900)
    g.env.lua.execute(
        "UnitLevel = function() return 70 end"
    )  # GetMaxPlayerLevel stays nil
    kill_with_secret_pos_plate(g)
    assert len(g.bursts()) == 1


def quest_xp(g, xp=100):
    g.stub.setXP(xp, 1000)
    g.tick(0.6)


def test_quest_burst_from_screen_centre(env):
    g = make(env, probe=False, origin="targetframe")
    g.fake_orbs_on()
    quest_xp(g)
    (b,) = g.bursts()
    assert b["kind"] == "other" and b["plate"] is None
    assert (b["x"], b["y"]) == (960, pytest.approx(1080 * 0.55))
    assert b["n"] >= 1
    assert g.has_log("kind=other") and g.has_log("origin=centre")


def test_quest_bursts_gated_by_option(env):
    g = make(env, probe=False, origin="targetframe")
    g.fake_orbs_on()
    g.db.questBursts = False
    quest_xp(g)
    assert g.bursts() == []
    assert g.has_log("kind=other")


def test_quest_burst_respects_enabled_and_max_level(env):
    g = make(env, probe=False, origin="targetframe")
    g.fake_orbs_on()
    g.db.enabled = False
    quest_xp(g)
    assert g.bursts() == []
    g.db.enabled = True
    set_level(g, 70, 70)
    quest_xp(g, 300)
    assert g.bursts() == []
    g.db.showAtMax = True
    quest_xp(g, 500)
    assert len(g.bursts()) == 1


# ---------------------------------------------------------------- anchor diagnostics


def log_lines(g, needle):
    return [ln for ln in g.log() if needle in ln]


def test_anchor_error_in_R_is_captured_logged_and_shown(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.stub.failSecondAnchorTo = plate
    g.slash("test 1 plate")
    last = chat_lines(g)[-1]
    assert "origin=centre (anchor failed: " in last and "restricted region" in last
    assert len(bars(g)) == 0  # fell back to the numeric centre path
    g.stub.tick(3)
    g.slash("test 1 plate")  # same message again: logged once only
    assert len(log_lines(g, "ANCHOR_ERR where=R err=")) == 1
    assert (
        "Cannot anchor" in str(g.orbs.lastAnchorErr)
        and len(g.orbs.lastAnchorErr) <= 120
    )
    g.slash("status")
    assert any(
        "anchor: chains=" in ln and "lastAnchorErr=" in ln and "Cannot anchor" in ln
        for ln in chat_lines(g)
    )


def test_chain_error_is_captured(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.stub.failAnchorToKind = g.env.lua.table_from({"StatusBarTexture": True})
    g.slash("test 1 plate")
    assert "origin=centre (anchor failed: " in chat_lines(g)[-1]
    assert len(log_lines(g, "ANCHOR_ERR where=chain err=")) == 1
    assert g.orbs.AnchorInfo(g.orbs)[3] == 0  # the burst frame was released


def test_draw_error_is_captured(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    burst(g, plate=plate, n=1)
    vbar = bars(g)[0]
    vbar.SetValue = g.env.lua.eval("function() error('draw boom') end")
    g.stub.tick(0.45)
    assert (
        len(log_lines(g, "ANCHOR_ERR where=draw err=")) == 1
        and "draw boom" in g.orbs.lastAnchorErr
    )


def test_successful_plate_test_reports_anchored_and_no_error(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.slash("test 1 plate")
    assert "origin=target plate (anchored)" in chat_lines(g)[-1]
    g.slash("status")
    assert any("lastAnchorErr=none" in ln for ln in chat_lines(g))


def test_default_test_command_uses_target_frame_origin(env):
    g = make(env, origin="targetframe")
    plate = restricted_plate(g, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.stub.setTargetFrame(250, 900, False)
    g.slash("test 1")
    assert "origin=target frame" in chat_lines(g)[-1]


# ---------------------------------------------------------------- /xporbs lab

NAMES = [
    "single-anchor",
    "two-anchor",
    "two-anchor-plate-first",
    "scale-anim",
    "translate-anim",
]
FINAL = "lab: watch for 4 s — red=mob, green=mob, yellow=halfway to corner, blue=slides mob↔bar, purple=bobs below mob"


def lab_lines(g):
    return [ln for ln in chat_lines(g) if "lab" in ln]


def frames_with_points(g):
    # Plates keeps size-1 proxy frames anchored to plates; those are not the lab's
    return [f for f in g.stub.frames.values() if len(f.points) > 0 and f.width != 1]


def start_lab(g):
    plate = restricted_plate(g, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.slash("lab")
    return plate


def run_out(g, seconds=5):
    for _ in range(int(seconds / 0.1)):
        g.stub.tick(0.1)


def test_lab_without_target_prints_reason_and_does_nothing(env):
    g = make(env)
    g.slash("lab")
    (line,) = lab_lines(g)
    assert "no nameplate" in line
    assert g.stub.shownTextures() == 0 and g.stub.allTextures() == 0
    assert g.ns.Lab.running is False and g.stub.updaters() == 0


def test_lab_all_techniques_ok_then_cleans_up(env):
    g = make(env)
    g.db.debug = True
    plate = start_lab(g)
    lines = lab_lines(g)
    for i, name in enumerate(NAMES, 1):
        assert any(ln.endswith(f"lab T{i} {name}: ok") for ln in lines), lines
        assert g.has_log(f"lab T{i} {name}: ok")
    assert lines[-1].endswith(FINAL)
    assert g.ns.Lab.running and g.stub.updaters() == 1
    assert g.stub.shownTextures() == 7  # red, 2 x (green + yellow), blue, purple
    assert g.stub.playingGroups() == 2
    on_plate = [
        f
        for f in g.stub.frames.values()
        if f.kind == "Texture" and len(f.points) == 1 and OWN(g, f.points[1][2], plate)
    ]
    assert (
        len(on_plate) == 2
    )  # T1's red marker and T4's blue marker anchor straight to the plate
    # T4: scale animation on a frame at the bar destination
    dx, dy, _ = g.ns.Target.GetDestination(g.ns.Target)
    (sc,) = lua_list(g.stub.animsOfKind("Scale"))
    s, F = sc["anim"], sc["owner"]
    assert (s.scaleFrom[1], s.scaleTo[1], s.duration, s.origin[1]) == (
        1,
        0.05,
        1.0,
        "CENTER",
    )
    assert (
        F.points[1][1] == "CENTER"
        and F.points[1][4] == pytest.approx(dx)
        and F.points[1][5] == pytest.approx(dy)
    )
    # T5: translation
    (tr,) = lua_list(g.stub.animsOfKind("Translation"))
    assert (tr["anim"].offset[1], tr["anim"].offset[2]) == (0, -200)
    assert OWN(g, tr["owner"].points[1][2], plate)
    assert all(grp.looping == "BOUNCE" for grp in lua_list(g.stub.animGroups))
    assert sorted(b.value for b in bars(g)) == [0.5] * 4  # T2 and T3 chains
    assert g.stub.restrictedHits == 0
    run_out(g)
    assert g.stub.shownTextures() == 0 and g.stub.playingGroups() == 0
    assert frames_with_points(g) == []
    assert g.ns.Lab.running is False and g.stub.updaters() == 0
    assert g.stub.restrictedHits == 0


def test_lab_keeps_markers_for_four_seconds(env):
    g = make(env)
    start_lab(g)
    run_out(g, 3.5)
    assert g.stub.shownTextures() == 7 and g.ns.Lab.running
    run_out(g, 1)
    assert g.stub.shownTextures() == 0


def test_lab_reuses_frames_on_second_run(env):
    g = make(env)
    start_lab(g)
    n_frames, n_groups = len(g.stub.frames), len(g.stub.animGroups)
    run_out(g)
    assert g.stub.shownTextures() == 0
    g.slash("lab")
    assert len(g.stub.frames) == n_frames and len(g.stub.animGroups) == n_groups
    assert g.stub.shownTextures() == 7 and g.stub.playingGroups() == 2
    g.slash("lab")  # re-running while active restarts cleanly
    assert g.stub.shownTextures() == 7 and g.stub.updaters() == 1
    assert len(g.stub.frames) == n_frames


def test_lab_t2_reports_which_setpoint_fails_and_others_continue(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.stub.failSecondAnchorTo = plate
    g.slash("lab")
    lines = lab_lines(g)
    t2 = [ln for ln in lines if "lab T2 " in ln][0]
    assert (
        "ERR SetPoint failed (TOPRIGHT->plate:" in t2
        and "BOTTOMLEFT->UIParent" not in t2
    )
    assert any(ln.endswith("lab T3 two-anchor-plate-first: ok") for ln in lines)
    assert any(ln.endswith("lab T1 single-anchor: ok") for ln in lines)
    run_out(g)
    assert g.stub.shownTextures() == 0 and frames_with_points(g) == []


def test_lab_scale_api_old_names(env):
    g = make(env)
    g.stub.scaleApi = "old"
    start_lab(g)
    assert any(ln.endswith("lab T4 scale-anim: ok") for ln in lab_lines(g))
    (sc,) = lua_list(g.stub.animsOfKind("Scale"))
    assert (sc["anim"].scaleFrom[1], sc["anim"].scaleTo[1]) == (1, 0.05)


def test_lab_scale_api_missing_is_reported_and_others_continue(env):
    g = make(env)
    g.stub.scaleApi = "none"
    start_lab(g)
    lines = lab_lines(g)
    t4 = [ln for ln in lines if "lab T4 " in ln][0]
    assert "ERR Scale animation has no SetScaleFrom" in t4
    assert any(ln.endswith("lab T5 translate-anim: ok") for ln in lines)
    run_out(g)
    assert (
        g.stub.shownTextures() == 0
        and g.stub.playingGroups() == 0
        and frames_with_points(g) == []
    )
