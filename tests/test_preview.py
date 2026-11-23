"""Test target window (Preview.lua) and the chime play button (Options.lua + Orbs:PlayChimeSample)."""

import pytest
from conftest import lua_list
from test_m5 import build, ctl, show

# Model frames get recording methods; mode "raising" makes every call error, "no-model-frame" makes the frame types
# unknown (CreateFrame raises), None records quietly.
MODEL_STUB = """
function(mode)
    local base = CreateFrame
    CreateFrame = function(kind, ...)
        if mode == "no-model-frame" and (kind == "PlayerModel" or kind == "CinematicModel" or kind == "DressUpModel") then
            error("unknown frame type")
        end
        local f = base(kind, ...)
        if kind == "PlayerModel" then
            f.log, f.anims = {}, {}
            for _, name in ipairs({ "SetCreature", "SetDisplayInfo", "SetAnimation", "SetPortraitZoom",
                    "SetCamDistanceScale", "SetFacing", "SetPosition", "FreezeAnimation" }) do
                f[name] = function(self, ...)
                    self.log[#self.log + 1] = name
                    if mode == "raising" then
                        error(name .. " exploded")
                    end
                    if name == "SetAnimation" then
                        self.anims[#self.anims + 1] = (...)
                    elseif name == "FreezeAnimation" then
                        self.anims[#self.anims + 1] = "freeze"
                    elseif name == "SetCreature" then
                        self.creature = (...)
                    end
                end
            end
            f.cx, f.cy = 1500, 600
        end
        return f
    end
end
"""

# records the params of every Orbs:Burst call in ns.captured, then runs the real one
CAPTURE = """
function(ns)
    local orig = ns.Orbs.Burst
    ns.captured = nil
    ns.Orbs.Burst = function(self, params)
        ns.captured = params
        return orig(self, params)
    end
end
"""


def make(env, mode=None):
    m = build(env, pre=lambda e: e.lua.eval(MODEL_STUB)(mode))
    env.lua.eval(CAPTURE)(m.ns)
    m.lua = env.lua
    m.same = env.lua.eval("rawequal")
    return m


def anims(model):
    """The SetAnimation ids the model received (FreezeAnimation calls are recorded as "freeze" and left out)."""
    return [a for a in lua_list(model.anims) if a != "freeze"]


def hide(m):
    m.opt.panel.scripts.OnHide(m.opt.panel)


def test_window_follows_the_options_panel(env):
    m = make(env)
    pv = m.ns.Preview
    assert pv.window is None  # built on first show
    show(m)
    assert pv.window.shown
    hide(m)
    assert not pv.window.shown
    show(m)
    assert pv.window.shown
    assert pv.window.width == 200 and pv.window.height == 260
    assert (
        pv.window.calls["SetFrameStrata"][1] == "MEDIUM"
    )  # below the HIGH orbs overlay


def test_docks_to_the_settings_panel(env):
    m = make(env)
    panel = m.lua.eval("{}")
    m.G.SettingsPanel = panel
    show(m)
    pt = m.ns.Preview.window.points[1]
    assert (pt[1], pt[3], pt[4]) == ("TOPLEFT", "TOPRIGHT", 4) and m.same(pt[2], panel)


def test_test_burst_comes_from_the_stand_in(env):
    m = make(env)
    show(m)
    m.slash("test 5")
    p = m.ns.captured
    assert m.same(p["plate"], m.ns.Preview.popAnchor)
    assert p["est"] == "mouseover" and p["estW"] == 1
    assert (p["ex"], p["ey"]) == (1500, 600)


@pytest.mark.parametrize("style", ["popstream", "crossfade", "stream", "streampop"])
def test_every_style_gets_the_located_case(env, style):
    m = make(env)
    show(m)
    m.slash("test 5 " + style)
    p = m.ns.captured
    assert (
        p["est"] != "default" and m.same(p["plate"], m.ns.Preview.popAnchor) and p["ex"] == 1500
    )


def test_popstream_pops_on_the_pop_anchor(env):
    m = make(env)
    show(m)
    m.db.style, m.db.popMode = "popstream", "nameplate"
    m.slash("test 5")
    plate = m.ns.Preview.popAnchor
    anchored = [
        f
        for f in m.stub.frames.values()
        if any(len(pt) > 2 and m.same(pt[2], plate) for pt in lua_list(f.points))
    ]
    assert anchored  # a pop frame hangs off the invisible pop anchor


def test_closed_options_keep_todays_behaviour(env):
    m = make(env)
    show(m)
    hide(m)
    m.slash("test 5")
    p = m.ns.captured
    assert p["plate"] is None and p["est"] == "default"


def test_death_and_revive_timer_clears_itself(env):
    m = make(env)
    show(m)
    pv = m.ns.Preview
    win, model = pv.window, pv.model
    assert win.scripts.OnUpdate is None
    m.slash("test 5")
    assert win.scripts.OnUpdate is not None
    assert anims(model)[-1] == 1  # Death
    m.stub.tick(1.5)
    assert anims(model)[-1] == 6  # held on Dead
    m.stub.tick(2.0)
    assert anims(model)[-1] == 0  # back to Stand
    assert lua_list(model.anims)[-1] == "freeze"  # ...and held calm again after the revive
    assert win.scripts.OnUpdate is None


def test_hiding_mid_death_stops_the_timer(env):
    m = make(env)
    show(m)
    m.slash("test 5")
    hide(m)
    assert m.ns.Preview.window.scripts.OnUpdate is None
    assert anims(m.ns.Preview.model)[-1] == 0


def test_model_load_tries_the_creature_then_the_display_id(env):
    m = make(env)
    show(m)
    assert lua_list(m.ns.Preview.model.log)[0] == "SetCreature"
    m.stub.runTimers()  # the model never reported loading
    assert "SetDisplayInfo" in lua_list(m.ns.Preview.model.log)


def test_model_calls_are_pcall_guarded(env):
    m = make(env, "raising")
    show(m)
    m.slash("test 5")
    m.stub.tick(4)
    m.stub.runTimers()
    assert m.ns.Preview.window.shown and m.same(m.ns.captured["plate"], m.ns.Preview.popAnchor)


def test_a_missing_model_api_breaks_nothing(env):
    m = make(env, "no-model-frame")
    show(m)
    assert m.ns.Preview.window.shown and m.ns.Preview.model is None
    m.slash("test 5")
    assert m.same(m.ns.captured["plate"], m.ns.Preview.popAnchor)
    m.stub.tick(4)
    assert m.ns.Preview.window.scripts.OnUpdate is None


def test_a_client_without_the_preview_still_tests(env):
    m = make(env)
    m.ns.Preview = None
    show(m)
    m.slash("test 5")  # no stand-in: today's origin
    assert m.ns.captured["plate"] is None


# ---------------------------------------------------------------- pop anchor


def pop_y_from_window_top(m, style, zoom_anchor):
    """Where the pop of a test burst forms, in px from the window's top edge (negative = down)."""
    m.db.style, m.db.popMode, m.db.zoomAnchor = style, "nameplate", zoom_anchor
    m.stub.zoom = 15
    m.slash("test 5")
    anchor = m.ns.Preview.popAnchor
    hung = [
        pt
        for f in m.stub.frames.values()
        for pt in lua_list(f.points)
        if len(pt) > 2 and m.same(pt[2], anchor) and f is not anchor
    ]
    assert hung
    anchor_pt = lua_list(anchor.points)[-1]
    assert anchor_pt[1] == "BOTTOM" and m.same(anchor_pt[2], m.ns.Preview.window) and anchor_pt[3] == "TOP"
    rel, offset = hung[-1][3], hung[-1][5]
    base = anchor_pt[5] + (anchor.height / 2 if rel == "CENTER" else 0)
    return base + offset


@pytest.mark.parametrize("zoom_anchor", [True, False])
@pytest.mark.parametrize("style", ["popstream", "crossfade"])
def test_the_pop_forms_between_the_plate_and_the_stream_origin_nearer_the_origin(env, style, zoom_anchor):
    m = make(env)
    show(m)
    y = pop_y_from_window_top(m, style, zoom_anchor)
    pv = m.ns.Preview
    bar_y = -(22 + 4 + 30 - 4)  # the health bar's centre
    origin_y = -(22 + 30 + 8 + 260 - 8) / 2  # the model centre = the stream origin
    assert origin_y < y < bar_y
    assert abs(y - origin_y) < abs(y - bar_y)
    assert y == pytest.approx(pv.anchorY)  # the same point whatever the zoom-anchor setting


# ---------------------------------------------------------------- faction stand-in


@pytest.mark.parametrize(
    ("faction", "npc", "name"),
    [("Alliance", 448, "Hogger"), ("Horde", 6466, "Gamon"), ("Neutral", 448, "Hogger"), (None, 448, "Hogger")],
)
def test_the_stand_in_follows_the_players_faction(env, faction, npc, name):
    m = make(env)
    m.G.UnitFactionGroup = (lambda unit: faction) if faction else None
    show(m)
    assert m.ns.Preview.model.creature == npc
    texts = [f.text for f in m.stub.frames.values() if f.kind == "FontString" and f.text == name]
    assert texts


def test_a_raising_faction_call_falls_back_to_hogger(env):
    m = make(env)
    m.G.UnitFactionGroup = m.lua.eval("function() error('boom') end")
    show(m)
    assert m.ns.Preview.model.creature == 448


def test_gamon_has_no_display_id_fallback(env):
    m = make(env)
    m.G.UnitFactionGroup = lambda unit: "Horde"
    show(m)
    m.stub.runTimers()
    assert "SetDisplayInfo" not in lua_list(m.ns.Preview.model.log)


def test_the_idle_pose_is_stand_variation_zero_frozen(env):
    m = make(env)
    show(m)
    model = m.ns.Preview.model
    assert anims(model)[-1] == 0 and lua_list(model.anims)[-1] == "freeze"


# ---------------------------------------------------------------- the Test burst button


def test_the_test_burst_button_sits_under_the_window(env):
    m = make(env)
    show(m)
    pv = m.ns.Preview
    frame, button = pv.buttonFrame, pv.testButton
    assert (frame.width, frame.height) == (120, 34) and (button.width, button.height) == (100, 22)
    pt = lua_list(frame.points)[0]
    assert (pt[1], pt[3], pt[4], pt[5]) == ("TOP", "BOTTOM", 0, -2) and m.same(pt[2], pv.window)
    assert frame.width < pv.window.width and str(button.text) == "Test burst"
    assert m.same(button.createdParent, frame)


def test_the_window_button_fires_the_stand_in_burst_with_rested_orbs(env):
    m = make(env)
    show(m)
    m.stub.click(m.ns.Preview.testButton)
    p = m.ns.captured
    assert m.same(p["plate"], m.ns.Preview.popAnchor) and p["nPurple"] > 0


def test_the_footer_has_no_test_button_while_the_window_is_up(env):
    m = make(env)
    show(m)
    assert m.opt.footerTest is None
    assert m.opt.resetAll is not None


def test_the_footer_button_returns_when_the_window_cannot_be_built(env):
    m = make(env)
    m.ns.Preview.Sync = lambda self, shown: False
    show(m)
    assert m.opt.footerTest is not None and m.opt.footerTest.shown
    m.stub.click(m.opt.footerTest)
    assert m.ns.captured["plate"] is None


# ---------------------------------------------------------------- slash with no argument


def test_bare_slash_opens_the_options_and_help_still_prints(env):
    m = make(env)
    m.slash("")
    assert len(lua_list(m.stub.settings.opened)) == 1
    m.slash("   ")
    assert len(lua_list(m.stub.settings.opened)) == 2
    m.slash("help")
    assert len(lua_list(m.stub.settings.opened)) == 2
    assert any("/xporbs - open the settings panel" in str(line) for line in m.say())


# ---------------------------------------------------------------- chime play button


def chime_sounds(m):
    return len(lua_list(m.stub.sounds))


def test_play_button_plays_six_chimes_through_the_real_chime_path(env):
    m = make(env)
    m.db.sound = True
    show(m)
    play = ctl(m, "chimeSample")
    assert (
        (play.width, play.height) == (22, 22)
        and play.IsEnabled(play)
        and play.alpha == 1
    )
    m.stub.click(play)
    assert m.orbs.sampleFrame.scripts.OnUpdate is not None
    for _ in range(120):  # real frames: the chime's 70 ms gap only passes with time
        m.stub.tick(0.01)
    assert chime_sounds(m) == 6
    assert m.orbs.sampleFrame.scripts.OnUpdate is None  # removed itself
    assert m.orbs.chime.Open(m.orbs.chime) == 0
    notes = [str(lua_list(s)[0])[-5] for s in lua_list(m.stub.sounds)]
    assert all(
        a != b for a, b in zip(notes, notes[1:])
    )  # the real progression: never the same note twice running


def test_play_button_is_spaced_not_simultaneous(env):
    m = make(env)
    m.db.sound = True
    show(m)
    m.stub.click(ctl(m, "chimeSample"))
    m.stub.tick(0.02)
    assert chime_sounds(m) == 1
    m.stub.tick(0.2)
    assert 1 < chime_sounds(m) < 6  # spaced out, not all at once


def test_play_button_is_dim_and_disabled_with_the_chime_off(env):
    m = make(env)
    m.db.sound = False
    show(m)
    play = ctl(m, "chimeSample")
    assert not play.IsEnabled(play) and play.alpha == pytest.approx(0.4)
    assert m.orbs.PlayChimeSample(m.orbs) is False
    m.stub.tick(1)
    assert chime_sounds(m) == 0
    m.stub.click(ctl(m, "sound"))  # on
    assert play.IsEnabled(play) and play.alpha == 1


def test_play_button_tooltip(env):
    m = make(env)
    show(m)
    m.stub.hover(ctl(m, "chimeSample"))
    assert str(m.stub.tooltip.text) == "Play a sample: a handful of orbs arriving"


def test_play_button_sits_on_the_voice_row(env):
    m = make(env)
    show(m)
    pt = ctl(m, "chimeSample").points[1]
    assert pt[4] == 260 + 156 and m.same(pt[2], m.opt.rows["soundVoice"])


def drawn_offsets(m):
    m.stub.click(ctl(m, "chimeSample"))
    return [m.orbs.sampleOffsets[i] for i in range(1, 7)]


def test_sample_arrivals_are_fast_irregular_and_never_closer_than_the_chime_gap(env):
    m = make(env)
    m.db.sound = True
    show(m)
    seen = set()
    for _ in range(30):
        offsets = drawn_offsets(m)
        gaps = [b - a for a, b in zip(offsets, offsets[1:])]
        assert len(offsets) == 6 and offsets[0] == 0 and offsets == sorted(offsets)
        assert min(gaps) >= 0.07 and offsets[-1] <= 0.45
        assert max(gaps) - min(gaps) > 1e-6  # not evenly spaced
        seen.add(round(offsets[3], 6))
    assert len(seen) > 20  # fresh draw per click


def test_sample_plays_all_six_notes_at_frame_rate(env):
    m = make(env)
    m.db.sound = True
    show(m)
    m.stub.click(ctl(m, "chimeSample"))
    for _ in range(120):
        m.stub.tick(0.01)
    assert chime_sounds(m) == 6 and m.orbs.sampleFrame.scripts.OnUpdate is None
