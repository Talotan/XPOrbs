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
        if kind == "Frame" then
            f.raised = 0
            f.SetToplevel = function(self, v) self.calls = self.calls or {}; self.calls.SetToplevel = { v } end
            f.Raise = function(self) self.raised = self.raised + 1 end
        end
        if kind == "PlayerModel" then
            if mode == "blank" or mode == "blank-then-loads" then
                -- reports no file until it is loaded; "blank" never loads, the other loads on the 2nd SetCreature
                f.clears = 0
                f.GetModelFileID = function(self) return self.loaded and 123456 or nil end
                f.ClearModel = function(self) self.clears = self.clears + 1 end
            end
            f.log, f.anims = {}, {}
            for _, name in ipairs({ "SetCreature", "SetDisplayInfo", "SetAnimation", "SetPortraitZoom",
                    "SetCamDistanceScale", "SetFacing", "SetPosition" }) do
                f[name] = function(self, ...)
                    self.log[#self.log + 1] = name
                    if mode == "raising" then
                        error(name .. " exploded")
                    end
                    if name == "SetAnimation" then
                        self.anims[#self.anims + 1] = (...)
                    elseif name == "SetCreature" then
                        self.creature = (...)
                    elseif name == "SetDisplayInfo" then
                        self.displayId = (...)
                    elseif name == "SetFacing" then
                        self.facing = (...)
                    elseif name == "SetCamDistanceScale" then
                        self.camDistance = (...)
                    end
                end
            end
            f.cx, f.cy = 1500, 600
            if mode == "readback" then
                -- a model that loads: GetModelFileID reports a file once SetDisplayInfo ran
                f.GetModelFileID = function(self) return self.displayId and 123456 or nil end
            end
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


def make(env, mode=None, atlas=True):
    def pre(e):
        e.lua.eval(MODEL_STUB)(mode)
        if not atlas:
            e.ns.stub.atlases["transmog-icon-revert"] = None

    m = build(env, pre=pre)
    env.lua.eval(CAPTURE)(m.ns)
    m.lua = env.lua
    m.same = env.lua.eval("rawequal")
    # the left mouse button as IsMouseButtonDown reports it
    m.mouse = env.lua.eval(
        "function() local t = { held = false }; IsMouseButtonDown = function() return t.held end; return t end"
    )()
    return m


def anims(model):
    """The SetAnimation ids the model received."""
    return lua_list(model.anims)


def hide(m):
    m.opt.panel.scripts.OnHide(m.opt.panel)


def test_a_failed_build_hides_its_frame_and_is_not_retried(env):
    m = make(env)
    pv = m.ns.Preview
    # the Test Kill button is the last thing the build makes: failing there strands the window, plate and model
    created = m.lua.eval(
        """
        function()
            local base, made, failed = CreateFrame, {}, false
            CreateFrame = function(kind, name, parent, template)
                -- only the first such button (the preview's own) fails; the options footer's must still work
                if kind == "Button" and template == "UIPanelButtonTemplate" and not failed then
                    failed = true
                    error("template missing")
                end
                local f = base(kind, name, parent, template)
                made[#made + 1] = f
                return f
            end
            return made
        end
        """
    )()
    show(m)
    first = len(lua_list(created))
    assert (
        first > 0 and not created[1].shown
    )  # the half-built window is hidden, not left on screen
    assert pv.window is None and pv.model is None and pv.popAnchor is None
    hide(m)
    show(m)
    assert len(lua_list(created)) == first  # the second open built nothing
    assert pv.Sync(pv, True) is False
    assert pv.TestTarget(pv) is None


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
    assert pv.window.width == 200 and pv.window.height == pv.WINDOW_H == 286
    assert (
        pv.window.calls["SetFrameStrata"][1] == "DIALOG"
    )  # the settings panel's strata, raised above it


def test_docks_to_the_settings_panel_when_there_is_no_orb_preview(env):
    m = make(env)
    panel = m.lua.eval("{}")
    m.G.SettingsPanel = panel
    m.ns.ShapePreview = None  # (with the preview window up it docks under that instead)
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
    assert p["ex"] == 1500 and p["ey"] == pytest.approx(600 + m.ns.Preview.originRise())
    assert p["ey"] > 600


@pytest.mark.parametrize("style", ["popstream", "crossfade", "stream", "streampop"])
def test_every_style_gets_the_located_case(env, style):
    m = make(env)
    show(m)
    m.slash("test 5 " + style)
    p = m.ns.captured
    assert (
        p["est"] != "default"
        and m.same(p["plate"], m.ns.Preview.popAnchor)
        and p["ex"] == 1500
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
    assert anims(model)[-1] == 26  # back to the Ready1H idle
    assert win.scripts.OnUpdate is None


def test_hiding_mid_death_stops_the_timer(env):
    m = make(env)
    show(m)
    m.slash("test 5")
    hide(m)
    assert m.ns.Preview.window.scripts.OnUpdate is None
    assert anims(m.ns.Preview.model)[-1] == 26


def test_model_load_tries_the_display_id_then_the_creature(env):
    m = make(env)
    show(m)
    log = lua_list(m.ns.Preview.model.log)
    assert log[0] == "SetDisplayInfo" and "SetCreature" not in log
    m.stub.runTimers()  # nothing reported a load: the other method runs
    assert "SetCreature" in lua_list(m.ns.Preview.model.log)
    assert m.ns.Preview.model.displayId == 108956


def test_no_creature_fallback_when_the_model_file_id_reads_back(env):
    m = make(env, "readback")
    show(m)
    m.stub.runTimers()
    assert "SetCreature" not in lua_list(m.ns.Preview.model.log)


def test_no_creature_fallback_when_the_load_event_fired(env):
    m = make(env)
    show(m)
    model = m.ns.Preview.model
    model.scripts.OnModelLoaded(model)
    m.stub.runTimers()
    assert "SetCreature" not in lua_list(model.log)


def test_idle_is_reapplied_on_load_and_show(env):
    m = make(env)
    show(m)
    model = m.ns.Preview.model
    model.scripts.OnModelLoaded(model)
    assert anims(model)[-1] == 26
    hide(m)
    n = len(anims(model))
    show(m)
    assert len(anims(model)) > n and anims(model)[-1] == 26


def test_model_calls_are_pcall_guarded(env):
    m = make(env, "raising")
    show(m)
    m.slash("test 5")
    m.stub.tick(4)
    m.stub.runTimers()
    assert m.ns.Preview.window.shown and m.same(
        m.ns.captured["plate"], m.ns.Preview.popAnchor
    )


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
    assert (
        anchor_pt[1] == "BOTTOM"
        and m.same(anchor_pt[2], m.ns.Preview.window)
        and anchor_pt[3] == "TOP"
    )
    rel, offset = hung[-1][3], hung[-1][5]
    base = anchor_pt[5] + (anchor.height / 2 if rel == "CENTER" else 0)
    return base + offset


@pytest.mark.parametrize("zoom_anchor", [True, False])
@pytest.mark.parametrize("style", ["popstream", "crossfade"])
def test_the_stream_origin_rises_with_the_model_and_the_pop_anchor_stays_put(
    env, style, zoom_anchor
):
    m = make(env)
    show(m)
    y = pop_y_from_window_top(m, style, zoom_anchor)
    pv = m.ns.Preview
    bar_y = -(12 + 44 - 4)  # the health bar's centre
    area_h = 260 - 8 - (12 + 44 + 4)  # the model area's height
    centre_y = -(12 + 44 + 4 + 260 - 8) / 2  # the model area's centre
    origin_y = centre_y + (
        m.ns.captured["ey"] - 600
    )  # the stream origin (the model's GetCenter y is 600)
    anchor_y = bar_y + 0.6 * (
        centre_y - bar_y
    )  # ANCHOR_FRACTION: the same absolute spot as before the model rose
    assert pv.modelAreaHeight == area_h
    assert y == pytest.approx(anchor_y) and y == pytest.approx(
        pv.anchorY
    )  # whatever the zoom-anchor setting
    assert anchor_y == pytest.approx(-114.4)  # unchanged by the raise
    # Hogger (the Alliance stand-in): the origin is the old spot (half way from the centre to the anchor) plus 15 %
    old_origin_y = centre_y + (anchor_y - centre_y) / 2
    assert origin_y - old_origin_y == pytest.approx(0.10 * area_h)
    assert pv.originRise() == pytest.approx(origin_y - centre_y)
    assert (
        bar_y > centre_y and origin_y > centre_y and bar_y > origin_y
    )  # all still inside the window, bar on top


def test_gamon_is_zoomed_in_and_not_raised(env):
    m = make(env)
    m.G.UnitFactionGroup = lambda unit: "Horde"
    show(m)
    assert m.ns.Preview.originRise() == pytest.approx(
        20.8
    )  # the old origin spot: no raise
    assert m.ns.Preview.model.camDistance == pytest.approx(0.80)


def test_default_facing_is_five_degrees_clockwise_of_before(env):
    m = make(env)
    show(m)
    assert m.ns.Preview.model.facing == pytest.approx(0.6 - 0.087)


def test_the_window_has_no_title_and_the_name_uses_a_big_font(env):
    m = make(env)
    show(m)
    texts = [f.text for f in m.stub.frames.values() if f.kind == "FontString"]
    assert "Test target" not in texts and "Hogger" in texts


# ---------------------------------------------------------------- faction stand-in


@pytest.mark.parametrize(
    ("faction", "npc", "name"),
    [
        ("Alliance", 448, "Hogger"),
        ("Horde", 6466, "Gamon"),
        ("Neutral", 448, "Hogger"),
        (None, 448, "Hogger"),
    ],
)
def test_the_stand_in_follows_the_players_faction(env, faction, npc, name):
    m = make(env)
    m.G.UnitFactionGroup = (lambda unit: faction) if faction else None
    show(m)
    m.stub.runTimers()
    assert m.ns.Preview.model.creature == npc
    texts = [
        f.text
        for f in m.stub.frames.values()
        if f.kind == "FontString" and f.text == name
    ]
    assert texts


def test_a_raising_faction_call_falls_back_to_hogger(env):
    m = make(env)
    m.G.UnitFactionGroup = m.lua.eval("function() error('boom') end")
    show(m)
    m.stub.runTimers()
    assert m.ns.Preview.model.creature == 448


@pytest.mark.parametrize(
    ("faction", "display_id", "npc"), [("Horde", 5205, 6466), ("Alliance", 108956, 448)]
)
def test_both_stand_ins_load_by_display_id_with_the_creature_as_fallback(
    env, faction, display_id, npc
):
    m = make(env)
    m.G.UnitFactionGroup = lambda unit: faction
    show(m)
    model = m.ns.Preview.model
    assert model.displayId == display_id and model.creature is None
    m.stub.runTimers()
    assert model.creature == npc


def test_a_failing_display_id_call_goes_straight_to_the_creature(env):
    m = make(env)
    m.lua.execute(
        "local f = CreateFrame; CreateFrame = function(kind, ...) local x = f(kind, ...); "
        "if kind == 'PlayerModel' then x.SetDisplayInfo = function() error('no') end end; return x end"
    )
    show(m)
    assert m.ns.Preview.model.creature == 448


def test_the_idle_pose_is_ready_1h_with_no_freeze(env):
    m = make(env)
    show(m)
    model = m.ns.Preview.model
    assert anims(model)[-1] == 26
    assert "FreezeAnimation" not in lua_list(model.log)


# ---------------------------------------------------------------- the Test Kill button


def test_the_test_kill_button_sits_inside_the_window_under_the_model(env):
    m = make(env)
    show(m)
    pv = m.ns.Preview
    button = pv.testButton
    assert pv.buttonFrame is None  # no separate frame any more
    assert (button.width, button.height) == (100, 22) and str(
        button.text
    ) == "Test Kill"
    assert m.same(button.createdParent, pv.window)
    pt = lua_list(button.points)[0]
    assert (pt[1], pt[3], pt[4], pt[5]) == ("BOTTOM", "BOTTOM", 0, 8) and m.same(
        pt[2], pv.window
    )
    # the model area ends above the button row: 8 px padding + the 22 px button + a 4 px gap
    low = lua_list(pv.model.points)[1]
    assert (low[1], low[3], low[4], low[5]) == ("BOTTOMRIGHT", "BOTTOMRIGHT", -8, 34)
    assert pv.BOTTOM_H == 34
    assert pv.modelAreaHeight == 192 and pv.WINDOW_H == 60 + 192 + 34


def test_there_is_no_divider_above_the_button(env):
    m = make(env)
    show(m)
    assert m.ns.Preview.dividerLine is None and m.ns.Preview.divider is None


# ---------------------------------------------------------------- moving the window


def test_the_window_is_movable_clamped_and_dragged_by_its_frame(env):
    m = make(env)
    show(m)
    win = m.ns.Preview.window
    assert (
        win.calls["SetMovable"][1] is True
        and win.calls["SetClampedToScreen"][1] is True
    )
    assert win.calls["RegisterForDrag"][1] == "LeftButton"
    win.scripts.OnDragStart(win)
    assert win.calls["StartMoving"] is not None
    win.scripts.OnDragStop(win)
    assert win.calls["StopMovingOrSizing"] is not None
    assert (
        m.ns.Preview.model.scripts.OnMouseDown is not None
    )  # the model still turns on left-drag


def icon_textures(m, frame):
    """The textures a button owns."""
    return [
        t
        for t in m.stub.frames.values()
        if t.kind == "Texture"
        and t.parentFrame is not None
        and m.same(t.parentFrame, frame)
    ]


def test_the_move_cross_is_top_left_always_shown_and_gold(env):
    m = make(env)
    show(m)
    pv = m.ns.Preview
    handle = pv.moveHandle
    pt = lua_list(handle.points)[0]
    assert (pt[1], pt[3], pt[4], pt[5]) == ("TOPLEFT", "TOPLEFT", 8, -8) and m.same(
        pt[2], pv.window
    )
    assert (handle.width, handle.height) == (16, 16)
    assert handle.shown and handle.alpha == pytest.approx(0.75)  # no hover needed
    assert (
        not pv.window.scripts.OnEnter and not pv.model.scripts.OnEnter
    )  # nothing shows or hides it any more
    rects = icon_textures(m, handle)
    assert rects and all(
        lua_list(t.calls["SetColorTexture"])[:3] == [1.0, 0.78, 0.18] for t in rects
    )
    handle.scripts.OnEnter(handle)
    assert handle.alpha == 1  # full while the cross itself is hovered
    handle.scripts.OnLeave(handle)
    assert handle.alpha == pytest.approx(0.75) and handle.shown


def test_the_move_cross_drags_the_window_and_has_a_tooltip(env):
    m = make(env)
    show(m)
    pv = m.ns.Preview
    handle = pv.moveHandle
    handle.scripts.OnMouseDown(handle, "LeftButton")
    assert pv.window.calls["StartMoving"] is not None
    pv.window.calls["StopMovingOrSizing"] = None
    handle.scripts.OnMouseUp(handle, "LeftButton")
    assert pv.window.calls["StopMovingOrSizing"] is not None
    handle.scripts.OnEnter(handle)
    assert str(m.stub.tooltip.text) == "Drag to reposition"


def test_the_reset_icon_is_top_right_with_the_options_art_and_a_tooltip(env):
    m = make(env)
    show(m)
    pv = m.ns.Preview
    btn = pv.resetButton
    pt = lua_list(btn.points)[0]
    assert (pt[1], pt[3], pt[4], pt[5]) == ("TOPRIGHT", "TOPRIGHT", -8, -8) and m.same(
        pt[2], pv.window
    )
    assert (btn.width, btn.height) == (16, 16)
    (icon,) = icon_textures(m, btn)
    assert icon.atlas == "transmog-icon-revert" and "SetVertexColor" not in dict(
        icon.calls or {}
    )
    assert (
        btn.calls["SetHighlightTexture"][1]
        == "Interface\\Buttons\\ButtonHilight-Square"
    )
    assert btn.shown and btn.alpha == pytest.approx(0.75)
    btn.scripts.OnEnter(btn)
    assert btn.alpha == 1 and str(m.stub.tooltip.text) == "Reset position"
    btn.scripts.OnLeave(btn)
    assert btn.alpha == pytest.approx(0.75)


def test_the_reset_icon_falls_back_to_a_gold_tinted_texture(env):
    m = make(env, atlas=False)
    show(m)
    (icon,) = icon_textures(m, m.ns.Preview.resetButton)
    assert (
        icon.atlas is None
        and icon.calls["SetTexture"][1] == "Interface\\Buttons\\UI-RefreshButton"
    )
    assert lua_list(icon.calls["SetVertexColor"]) == [1.0, 0.78, 0.18]


def test_clicking_the_reset_icon_docks_the_window_again(env):
    m = make(env)
    m.G.SettingsPanel = m.lua.eval("{}")
    show(m)
    pv = m.ns.Preview
    pv.window.ClearAllPoints(pv.window)
    pv.window.SetPoint(pv.window, "CENTER", m.G.UIParent, "CENTER", 300, 200)
    assert lua_list(pv.window.points)[0][1] == "CENTER"
    m.stub.click(pv.resetButton)
    back = lua_list(pv.window.points)
    assert len(back) == 1 and (back[0][1], back[0][3], back[0][4], back[0][5]) == (
        "TOP",
        "BOTTOM",
        0,
        -2,
    )
    assert m.same(back[0][2], m.ns.ShapePreview.window)


def test_the_window_docks_again_when_the_panel_hides_and_shows(env):
    m = make(env)
    m.G.SettingsPanel = m.lua.eval("{}")
    show(m)
    pv = m.ns.Preview
    first = lua_list(pv.window.points)[0]
    assert (first[1], first[3], first[4], first[5]) == ("TOP", "BOTTOM", 0, -2)
    # the player drags it somewhere (the client re-anchors it to the screen)
    pv.window.ClearAllPoints(pv.window)
    pv.window.SetPoint(pv.window, "CENTER", m.G.UIParent, "CENTER", 300, 200)
    assert lua_list(pv.window.points)[0][1] == "CENTER"
    hide(m)
    assert not pv.window.shown
    show(m)
    back = lua_list(pv.window.points)
    assert len(back) == 1 and (back[0][1], back[0][3], back[0][4], back[0][5]) == (
        "TOP",
        "BOTTOM",
        0,
        -2,
    )
    assert m.same(back[0][2], m.ns.ShapePreview.window)


def test_no_onupdate_is_left_on_the_test_target_after_the_panel_hides(env):
    m = make(env)
    show(m)
    pv = m.ns.Preview
    m.stub.click(pv.testButton)
    pv.PlayDeath(pv)
    assert pv.window.scripts.OnUpdate is not None  # the death sequence runs
    hide(m)
    assert pv.window.scripts.OnUpdate is None and pv.model.scripts.OnUpdate is None
    assert pv.moveHandle.scripts.OnUpdate is None
    # showing it does not start anything either
    show(m)
    assert pv.window.scripts.OnUpdate is None


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
    assert str(m.opt.footerTest.text) == "Test Kill" and not m.say()


def test_the_window_button_prints_nothing_but_the_slash_command_does(env):
    m = make(env)
    show(m)
    before = len(m.say())
    m.stub.click(m.ns.Preview.testButton)
    assert m.ns.captured is not None and len(m.say()) == before
    m.slash("test 5")
    assert "test: 5%" in m.say()[-1]


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
    assert pt[4] == 260 + 204 and m.same(
        pt[2], m.opt.rows["soundVoice"]
    )  # right of the dropdown's right arrow


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
        assert min(gaps) >= 0.085 - 1e-9 and offsets[-1] <= 0.50 + 1e-9
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


# ---------------------------------------------------------------- drag to rotate


def drag_start(m, x=1000):
    show(m)
    model = m.ns.Preview.model
    m.stub.cursor.x = x
    m.mouse.held = True
    model.scripts.OnMouseDown(model, "LeftButton")
    return model


def test_dragging_rotates_the_model_around_its_vertical_axis(env):
    m = make(env)
    model = drag_start(m)
    start = model.facing
    assert model.scripts.OnUpdate is not None
    m.stub.cursor.x = 1100
    m.stub.tick(0.016)
    assert model.facing == pytest.approx(start + 100 * 0.012)
    m.stub.cursor.x = 900
    m.stub.tick(0.016)
    assert model.facing == pytest.approx(start - 100 * 0.012)


def test_the_drag_divides_by_the_effective_scale(env):
    m = make(env)
    show(m)
    model = m.ns.Preview.model
    model.scale = 2
    m.stub.cursor.x = 1000
    m.mouse.held = True
    model.scripts.OnMouseDown(model, "LeftButton")
    start = model.facing
    m.stub.cursor.x = 1100
    m.stub.tick(0.016)
    assert model.facing == pytest.approx(start + 50 * 0.012)


def test_mouse_up_removes_the_drag_update_and_keeps_the_facing(env):
    m = make(env)
    model = drag_start(m)
    m.stub.cursor.x = 1050
    m.stub.tick(0.016)
    turned = model.facing
    model.scripts.OnMouseUp(model, "LeftButton")
    assert model.scripts.OnUpdate is None
    m.stub.cursor.x = 1500
    m.stub.tick(0.016)
    assert model.facing == turned
    model.scripts.OnModelLoaded(model)  # a load re-applies the kept facing
    assert model.facing == pytest.approx(turned)
    hide(m)
    show(m)
    assert model.facing == pytest.approx(turned)


def test_a_new_drag_continues_from_the_kept_facing(env):
    m = make(env)
    model = drag_start(m)
    m.stub.cursor.x = 1100
    m.stub.tick(0.016)
    turned = model.facing
    model.scripts.OnMouseUp(model, "LeftButton")
    m.stub.cursor.x = 400
    model.scripts.OnMouseDown(model, "LeftButton")
    m.stub.cursor.x = 450
    m.stub.tick(0.016)
    assert model.facing == pytest.approx(turned + 50 * 0.012)


def test_hiding_removes_the_drag_update(env):
    m = make(env)
    model = drag_start(m)
    hide(m)
    assert model.scripts.OnUpdate is None


def test_a_release_outside_the_frame_removes_the_drag_update(env):
    m = make(env)
    model = drag_start(m)
    m.mouse.held = False  # no OnMouseUp arrives
    m.stub.tick(0.016)
    assert model.scripts.OnUpdate is None


def test_the_other_mouse_buttons_do_not_start_a_drag(env):
    m = make(env)
    show(m)
    model = m.ns.Preview.model
    model.scripts.OnMouseDown(model, "RightButton")
    assert model.scripts.OnUpdate is None


def test_death_keeps_the_dragged_facing(env):
    m = make(env)
    model = drag_start(m)
    m.stub.cursor.x = 1200
    m.stub.tick(0.016)
    model.scripts.OnMouseUp(model, "LeftButton")
    turned = model.facing
    m.slash("test 5")
    m.stub.tick(4)
    assert model.facing == pytest.approx(turned)


def test_a_client_without_ismousebuttondown_still_drags(env):
    m = make(env)
    model = drag_start(m)
    m.G.IsMouseButtonDown = None
    m.stub.cursor.x = 1010
    m.stub.tick(0.016)
    assert model.scripts.OnUpdate is not None


# ---------------------------------------------------------------- pop size ignores the camera


LIVE_RECS = """function(fn)
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


def ring_radii(m, zoom, with_window):
    """Max pop ring radius and spread of the orbs of one seeded Popstream test burst at a stubbed camera zoom."""
    m.db.style, m.db.popMode, m.db.zoomSpread = "streampop", "nameplate", True
    if with_window:
        show(m)
    m.stub.zoom = zoom
    m.lua.eval("math.randomseed")(7)
    m.slash("test 15")
    recs = list(m.lua.eval(LIVE_RECS)(m.ns.Orbs.driver.scripts.OnUpdate).values())
    assert recs
    radii = [((o.ringX - o.px) ** 2 + (o.ringY - o.py) ** 2) ** 0.5 for o in recs]
    spread = max(o.ringX for o in recs) - min(o.ringX for o in recs)
    return max(radii), spread


def test_the_test_target_pop_is_the_same_size_at_any_camera_zoom(env):
    m = make(env)
    near = ring_radii(m, 5, True)
    assert (
        m.ns.captured["zoomFactor"] == 1
    )  # the stand-in tells Burst not to read the camera
    m.stub.tick(5)
    far = ring_radii(m, 40, True)
    assert near == pytest.approx(far)


def test_a_test_without_the_window_still_scales_with_the_camera(env):
    m = make(env)
    near = ring_radii(m, 5, False)
    assert m.ns.captured["zoomFactor"] is None
    m.stub.tick(5)
    far = ring_radii(m, 40, False)
    assert near[0] > far[0]


def test_the_name_font_is_two_pixels_smaller_than_the_big_font_object(env):
    m = make(env)
    m.G.GameFontNormalHuge = m.lua.eval(
        "{ GetFont = function() return 'Fonts/FRIZQT__.TTF', 32, 'OUTLINE' end }"
    )
    show(m)
    name = [
        f
        for f in m.stub.frames.values()
        if f.kind == "FontString" and f.text == "Hogger"
    ][0]
    assert lua_list(name.calls["SetFont"]) == ["Fonts/FRIZQT__.TTF", 30, "OUTLINE"]


def count(model, name):
    return lua_list(model.log).count(name)


def test_the_test_target_is_high_strata_toplevel_and_raised(env):
    # the orb preview window is checked in test_shape_look
    m = make(env)
    show(m)
    win = m.ns.Preview.window
    assert win.calls["SetFrameStrata"][1] == "DIALOG"
    assert win.calls["SetToplevel"][1] is True
    assert win.raised >= 1  # raised on show


def test_a_drag_start_raises_the_test_target(env):
    m = make(env)
    show(m)
    win = m.ns.Preview.window
    before = win.raised
    win.scripts.OnDragStart(win)
    assert win.raised == before + 1


def test_a_blank_model_is_cleared_and_retried_then_falls_back_to_the_display_id(env):
    m = make(env, "blank")
    show(m)
    model = m.ns.Preview.model
    assert count(model, "SetDisplayInfo") == 1 and count(model, "SetCreature") == 0
    m.stub.runTimers()  # first check: the creature
    assert count(model, "SetCreature") == 1 and model.clears == 0
    m.stub.runTimers()  # retry 1: cleared, the creature again
    assert count(model, "SetCreature") == 2 and model.clears == 1
    m.stub.runTimers()  # retry 2: cleared, the display id
    assert count(model, "SetDisplayInfo") == 2 and model.clears == 2
    m.stub.runTimers()  # out of retries: nothing more
    assert count(model, "SetDisplayInfo") == 2 and count(model, "SetCreature") == 2
    assert len(m.stub.timers) == 0


def test_a_retry_stops_once_the_model_reports_a_file(env):
    m = make(env, "blank")
    show(m)
    model = m.ns.Preview.model
    m.stub.runTimers()
    m.stub.runTimers()
    assert count(model, "SetCreature") == 2
    model.loaded = True
    m.stub.runTimers()
    assert count(model, "SetCreature") == 2 and count(model, "SetDisplayInfo") == 1
    assert len(m.stub.timers) == 0


def test_a_retry_logs_one_debug_line(env):
    m = make(env, "blank")
    m.ns.db.debug = True
    show(m)
    m.stub.runTimers()
    m.stub.runTimers()
    log = lua_list(m.ns.db.log)
    assert sum("preview model not loaded" in str(line) for line in log) == 1


def test_a_loaded_model_is_not_retried(env):
    m = make(env, "readback")
    show(m)
    m.stub.runTimers()
    model = m.ns.Preview.model
    assert count(model, "SetCreature") == 0 and len(m.stub.timers) == 0


def test_no_errors_without_get_model_file_id_or_timers(env):
    m = make(env)  # the stub model has no GetModelFileID or ClearModel
    show(m)
    m.stub.runTimers()
    m.stub.runTimers()
    m.stub.runTimers()
    assert m.ns.Preview.window.shown
    m2 = make(env)
    m2.lua.eval("function() C_Timer = nil end")()
    hide(m2)
    show(m2)
    assert m2.ns.Preview.window.shown


def test_orb_frames_are_dialog_above_the_windows(env):
    m = make(env)
    show(m)
    m.slash("test 5")
    pops = [
        f
        for f in lua_list(m.stub.frames)
        if f.width == 1 and f.height == 1 and f.calls and f.calls["SetFrameStrata"]
    ]
    assert pops
    for f in [m.ns.Orbs.overlay] + pops:
        assert f.calls["SetFrameStrata"][1] == "FULLSCREEN_DIALOG"
    assert (
        m.ns.Preview.window.calls["SetFrameStrata"][1] == "DIALOG"
    )  # below the orbs' FULLSCREEN_DIALOG
