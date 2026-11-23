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
                    "SetCamDistanceScale", "SetFacing", "SetPosition" }) do
                f[name] = function(self, ...)
                    self.log[#self.log + 1] = name
                    if mode == "raising" then
                        error(name .. " exploded")
                    end
                    if name == "SetAnimation" then
                        self.anims[#self.anims + 1] = (...)
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
    assert m.same(p["plate"], m.ns.Preview.plate)
    assert p["est"] == "mouseover" and p["estW"] == 1
    assert (p["ex"], p["ey"]) == (1500, 600)


@pytest.mark.parametrize("style", ["popstream", "crossfade", "stream", "streampop"])
def test_every_style_gets_the_located_case(env, style):
    m = make(env)
    show(m)
    m.slash("test 5 " + style)
    p = m.ns.captured
    assert (
        p["est"] != "default" and m.same(p["plate"], m.ns.Preview.plate) and p["ex"] == 1500
    )


def test_popstream_pops_on_the_fake_plate(env):
    m = make(env)
    show(m)
    m.db.style, m.db.popMode = "popstream", "nameplate"
    m.slash("test 5")
    plate = m.ns.Preview.plate
    anchored = [
        f
        for f in m.stub.frames.values()
        if any(len(pt) > 2 and m.same(pt[2], plate) for pt in lua_list(f.points))
    ]
    assert anchored  # a pop frame hangs off the fake plate


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
    assert lua_list(model.anims)[-1] == 1  # Death
    m.stub.tick(1.5)
    assert lua_list(model.anims)[-1] == 6  # held on Dead
    m.stub.tick(2.0)
    assert lua_list(model.anims)[-1] == 0  # back to Stand
    assert win.scripts.OnUpdate is None


def test_hiding_mid_death_stops_the_timer(env):
    m = make(env)
    show(m)
    m.slash("test 5")
    hide(m)
    assert m.ns.Preview.window.scripts.OnUpdate is None
    assert lua_list(m.ns.Preview.model.anims)[-1] == 0


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
    assert m.ns.Preview.window.shown and m.same(m.ns.captured["plate"], m.ns.Preview.plate)


def test_a_missing_model_api_breaks_nothing(env):
    m = make(env, "no-model-frame")
    show(m)
    assert m.ns.Preview.window.shown and m.ns.Preview.model is None
    m.slash("test 5")
    assert m.same(m.ns.captured["plate"], m.ns.Preview.plate)
    m.stub.tick(4)
    assert m.ns.Preview.window.scripts.OnUpdate is None


def test_a_client_without_the_preview_still_tests(env):
    m = make(env)
    m.ns.Preview = None
    show(m)
    m.slash("test 5")  # no stand-in: today's origin
    assert m.ns.captured["plate"] is None


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
    for _ in range(40):  # real frames: the chime's 70 ms gap only passes with time
        m.stub.tick(0.05)
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
    assert 1 < chime_sounds(m) < 6


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
