"""M5 (v0.12): options panel, /xporbs options, /xporbs pick, /xporbs reset. Driven through stubs_m5.lua."""

import re

import pytest
from conftest import TESTS


def build(env, settings=True, colorpicker=True, mouse_foci=True, pre=None):
    env.load_chunk(TESTS / "stubs_m2.lua", "stubs_m2.lua")(env.ns)
    env.load_chunk(TESTS / "stubs_m5.lua", "stubs_m5.lua")(env.ns)
    env.load_chunk(TESTS / "stubs_m3.lua", "stubs_m3.lua")(env.ns)
    if not settings:
        env.G.Settings = None
    if not colorpicker:
        env.G.ColorPickerFrame = None
    if not mouse_foci:
        env.G.GetMouseFoci = None
    if pre:
        pre(env)  # v0.13: tweak the stubs before the addon loads
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    env.stub = env.ns.stub
    env.stub.makeBar("MainStatusTrackingBarContainer", 400, 20, 800, 10, True)
    env.db = env.G.XPOrbsDB
    env.db.zoomAnchor, env.db.zoomA, env.db.zoomB, env.db.zoomMin = False, 10, 500, 2  # old anchor, see Game
    env.db.unknownOrigin = "off"
    env.db.flightMode = "time"  # tests assume a fixed flight time, not a flight speed
    env.opt = env.ns.Options
    env.orbs = env.ns.Orbs
    env.slash = env.G.SlashCmdList.XPORBS
    env.say = lambda: [str(env.stub.chat[i]) for i in range(1, len(env.stub.chat) + 1)]

    def run(seconds, step=0.05):
        for _ in range(int(seconds / step) + 1):
            env.stub.tick(step)

    env.run = run
    return env


@pytest.fixture
def m5(env):
    return build(env)


def ctl(m5, key):
    return m5.opt.controls[key]


def show(m5):
    m5.opt.panel.scripts.OnShow(m5.opt.panel)


def shown_sparkle_widths(m5):
    return [
        f.width
        for f in m5.stub.frames.values()
        if f.kind == "Texture"
        and f.shown
        and f.calls
        and f.calls["SetTexture"] is not None
        and "sparkle" in f.calls["SetTexture"][1]
    ]


def burst_count(m5):
    """Orbs from the last /xporbs test line."""
    m5.slash("test 5")
    return int(re.search(r"-> (\d+) orbs", m5.say()[-1]).group(1))


def panel_texts(m5):
    return [
        f.text for f in m5.stub.frames.values() if f.kind == "FontString" and f.text
    ]


# ---------------------------------------------------------------- panel


def test_panel_registers_a_canvas_category(m5):
    reg, added = m5.stub.settings.registered, m5.stub.settings.added
    assert len(reg) == 1 and len(added) == 1
    assert reg[1].name == "XP Orbs" and m5.lua.eval("rawequal")(added[1], reg[1])
    assert m5.lua.eval("rawequal")(m5.opt.panel, reg[1].frame)
    for key in ("enabled", "restedTint", "trail", "questBursts", "showAtMax", "debug"):
        assert ctl(m5, key).template == "UICheckButtonTemplate"
    for key in ("density", "cap", "size", "flightTime"):
        assert ctl(m5, key).template == "OptionsSliderTemplate"


def test_options_command_opens_the_category(m5):
    m5.slash("options")
    assert list(m5.stub.settings.opened.values()) == [m5.stub.settings.registered[1].id]


def test_options_without_settings_api_prints_a_fallback(env):
    m5 = build(env, settings=False)
    assert m5.opt.category is None
    m5.slash("options")
    assert "isn't available" in m5.say()[-1]
    m5.slash("status")
    assert any("options panel: unavailable" in line for line in m5.say())


def test_options_open_failure_is_caught(m5):
    m5.G.Settings.OpenToCategory = m5.lua.eval("function() error('boom') end")
    m5.slash("options")
    assert "couldn't open" in m5.say()[-1]


def test_a_broken_build_is_reported_not_thrown(env):
    env.load_chunk(TESTS / "stubs_m2.lua", "stubs_m2.lua")(env.ns)
    env.load_chunk(TESTS / "stubs_m5.lua", "stubs_m5.lua")(env.ns)
    env.G.Settings.RegisterAddOnCategory = env.lua.eval("function() error('nope') end")
    env.load_addon()  # must not raise
    assert env.ns.Options.category is None and "nope" in str(env.ns.Options.err)


def test_controls_refresh_on_show(m5):
    m5.db.trail = False
    m5.db.cap = 12
    m5.db.style = "crossfade"
    show(m5)
    assert ctl(m5, "trail").checked is False and ctl(m5, "enabled").checked is True
    assert ctl(m5, "cap").value == 12
    assert ctl(m5, "style_crossfade").checked and not ctl(m5, "style_popstream").checked


def test_refreshing_does_not_write_back_snapped_values(m5):
    m5.db.density = (
        130  # off the 25-step grid: the control shows 125 but the db keeps what it had
    )
    show(m5)
    assert m5.db.density == 130


@pytest.mark.parametrize(
    "key", ["enabled", "restedTint", "trail", "questBursts", "showAtMax", "debug"]
)
def test_checkbox_writes_db(m5, key):
    show(m5)
    before = m5.db[key]
    m5.stub.click(ctl(m5, key))
    assert m5.db[key] is (not before)
    m5.stub.click(ctl(m5, key))
    assert m5.db[key] is before


@pytest.mark.parametrize(
    "key,value,expect",
    [
        ("density", 200, 200),
        ("density", 130, 125),
        ("cap", 20, 20),
        ("size", 20, 20),
        ("flightTime", 1.0, 1.0),
        ("flightTime", 0.77, 0.75),
        ("cap", 500, 80),
        ("size", 1, 8),
    ],
)
def test_slider_writes_db(m5, key, value, expect):
    show(m5)
    m5.stub.slide(ctl(m5, key), value)
    assert m5.db[key] == pytest.approx(expect)


def test_slider_ranges_and_steps(m5):
    spec = [
        ("density", 25, 400, 25),
        ("cap", 5, 80, 1),
        ("size", 8, 32, 1),
        ("flightTime", 0.4, 1.5, 0.05),
    ]
    for key, lo, hi, step in spec:
        s = ctl(m5, key)
        assert (s.minV, s.maxV, s.step) == (lo, hi, step)


def test_slider_shows_its_value(m5):
    show(m5)
    m5.stub.slide(ctl(m5, "density"), 250)
    m5.stub.slide(ctl(m5, "flightTime"), 1.25)
    texts = panel_texts(m5)
    assert "250%" in texts and "1.25 s" in texts


def test_density_changes_the_next_test_burst(m5):
    base = burst_count(m5)
    m5.run(3)
    m5.stub.slide(ctl(m5, "density"), 200)
    assert burst_count(m5) > base
    m5.run(3)
    m5.stub.slide(ctl(m5, "density"), 25)
    assert burst_count(m5) < base


def test_size_changes_the_next_burst(m5):
    m5.stub.slide(ctl(m5, "size"), 24)
    m5.slash("test 5")
    m5.run(0.5)
    widths = shown_sparkle_widths(m5)
    assert widths and max(widths) == pytest.approx(24 * 1.9)  # others are shrinking towards the bar


def test_flight_time_changes_the_next_burst(m5):
    m5.stub.slide(ctl(m5, "flightTime"), 1.5)
    m5.slash("test 5")
    m5.run(1.0)
    assert m5.orbs.Info(m5.orbs)[
        0
    ]  # still flying well past the default 1.0 s flight + stagger


def test_enabled_checkbox_writes_the_flag_kills_read(m5):
    show(m5)
    m5.stub.click(ctl(m5, "enabled"))
    assert m5.db.enabled is False


def test_style_selector_writes_db(m5):
    m5.stub.click(ctl(m5, "style_crossfade"))
    assert m5.db.style == "crossfade"
    assert ctl(m5, "style_crossfade").checked and not ctl(m5, "style_popstream").checked
    m5.stub.click(ctl(m5, "style_stream"))
    assert m5.db.style == "stream" and not ctl(m5, "style_crossfade").checked
    m5.stub.click(
        ctl(m5, "style_stream")
    )  # clicking the selected one must not leave nothing selected
    assert m5.db.style == "stream" and ctl(m5, "style_stream").checked


def test_slash_style_change_shows_on_next_show(m5):
    m5.slash("style stream")
    show(m5)
    assert ctl(m5, "style_stream").checked


# ---------------------------------------------------------------- colours


def test_swatch_callback_writes_colour_and_cancel_restores(m5):
    prev = [m5.db.color[i] for i in (1, 2, 3)]
    m5.stub.click(ctl(m5, "color"))
    cp = m5.G.ColorPickerFrame
    info = cp.info
    assert [info.r, info.g, info.b] == pytest.approx(prev) and info.hasOpacity is False
    cp.r, cp.g, cp.b = 0.9, 0.1, 0.2
    info.swatchFunc()
    assert [m5.db.color[i] for i in (1, 2, 3)] == pytest.approx([0.9, 0.1, 0.2])
    cp.r, cp.g, cp.b = 0.4, 0.4, 0.4
    info.swatchFunc()
    info.cancelFunc()
    assert [m5.db.color[i] for i in (1, 2, 3)] == pytest.approx(prev)


def test_rested_swatch_writes_rested_colour(m5):
    m5.stub.click(ctl(m5, "restedColor"))
    cp = m5.G.ColorPickerFrame
    cp.r, cp.g, cp.b = 0.1, 0.2, 0.3
    cp.info.swatchFunc()
    assert [m5.db.restedColor[i] for i in (1, 2, 3)] == pytest.approx([0.1, 0.2, 0.3])


def test_missing_colour_picker_hides_swatches(env):
    m5 = build(env, colorpicker=False)
    assert ctl(m5, "color").shown is False and ctl(m5, "restedColor").shown is False
    m5.stub.click(ctl(m5, "color"))  # no error
    assert m5.opt.category is not None


def test_swatches_are_shown_with_a_colour_picker(m5):
    assert ctl(m5, "color").shown and ctl(m5, "restedColor").shown


# ---------------------------------------------------------------- buttons, reset


def buttons(m5):
    return {
        f.text: f
        for f in m5.stub.frames.values()
        if f.kind == "Button" and f.template == "UIPanelButtonTemplate"
    }


def test_test_burst_button_fires_a_burst(m5):
    show(m5)  # the button lives under the Test target window, built when the panel is shown
    m5.stub.click(buttons(m5)["Test Kill"])
    assert not any("test: 5%" in line for line in m5.say())  # the button is quiet; only /xporbs test prints
    assert m5.orbs.Info(m5.orbs)[0]


def test_pick_button_arms_the_picker(m5):
    m5.stub.click(buttons(m5)["Pick XP bar frame"])
    assert armed(m5)


def test_reset_restores_defaults_and_refreshes_controls(m5):
    m5.db.density, m5.db.cap, m5.db.trail, m5.db.style = 300, 10, False, "stream"
    m5.db.color = m5.lua.table_from([1, 1, 1])
    m5.db.targetFrame = "Foo"
    m5.db.debug = True
    m5.db.log = m5.lua.table_from(["x"])
    show(m5)
    assert ctl(m5, "cap").value == 10
    m5.stub.click(buttons(m5)["Reset all to default"])  # v0.13: footer button, asks first
    assert m5.db.cap == 10
    m5.G.StaticPopupDialogs["XPORBS_RESET_ALL"].OnAccept()
    assert (m5.db.density, m5.db.cap, m5.db.trail, m5.db.style) == (
        100,
        40,
        True,
        "popstream",
    )
    assert [m5.db.color[i] for i in (1, 2, 3)] == pytest.approx([0.72, 0.28, 1.0])
    assert m5.db.targetFrame is None
    assert m5.db.debug is True and m5.db.log[1] == "x" and m5.db.version == 6
    assert ctl(m5, "cap").value == 40 and ctl(m5, "density").value == 100
    assert ctl(m5, "trail").checked is True and ctl(m5, "style_popstream").checked
    assert "settings reset" in m5.say()[-1]


def test_reset_works_without_a_panel(env):
    m5 = build(env, settings=False)
    m5.db.cap = 7
    m5.slash("reset")
    assert m5.db.cap == 40 and "settings reset" in m5.say()[-1]


def test_reset_colours_are_fresh_tables(m5):
    m5.slash("reset")
    assert m5.db.color is not m5.ns.defaults.color


# ---------------------------------------------------------------- cap lowered mid-flight


def test_lowering_cap_with_live_orbs_drains_cleanly(m5):
    m5.db.trail = True
    m5.slash("test 400")
    m5.run(0.3)
    _, in_use, created, _ = m5.orbs.Info(m5.orbs)
    assert in_use > 0
    m5.stub.slide(ctl(m5, "cap"), 5)
    assert m5.orbs.Info(m5.orbs)[3] == 5 * 6 * 2 + 8
    m5.slash("test 400")  # over the new ceiling: draws nothing new, must not error
    m5.run(0.5)
    assert m5.orbs.Info(m5.orbs)[1] <= max(in_use, 5 * 6 * 2 + 7)
    m5.run(4)
    active, in_use, created2, _ = m5.orbs.Info(m5.orbs)
    assert in_use == 0 and not active
    assert created2 <= created + 5 * 6 * 2 + 8  # nothing leaked past the old pool
    m5.slash("test 5")  # fresh bursts respect the new, lower ceiling
    m5.run(0.1)
    assert m5.orbs.Info(m5.orbs)[1] <= 5 * 6 * 2 + 7
    m5.run(4)
    assert m5.orbs.Info(m5.orbs)[1] == 0


def test_raising_cap_allows_more_orbs(m5):
    m5.stub.slide(ctl(m5, "cap"), 5)
    m5.slash("test 400")
    n_low = m5.orbs.Info(m5.orbs)[1]
    m5.run(4)
    m5.stub.slide(ctl(m5, "cap"), 80)
    m5.slash("test 400")
    assert m5.orbs.Info(m5.orbs)[1] > n_low


# ---------------------------------------------------------------- picker


def armed(m5):
    pf = m5.ns.Target.pickFrame
    return bool(pf and pf.events["GLOBAL_MOUSE_DOWN"])


def chain(m5, names):
    """UIParent > f1 > f2 ...; a None name makes an unnamed frame. Returns the frames, outermost first."""
    create = m5.lua.eval("CreateFrame")
    parent = m5.G.UIParent
    out = []
    for n in names:
        f = m5.stub.namedFrame(n, parent) if n else create("Frame", None, parent)
        out.append(f)
        parent = f
    return out


def test_pick_arms_and_prints_prompt(m5):
    assert not armed(m5)
    m5.slash("pick")
    assert armed(m5) and "Click the XP bar (right-click to cancel)" in m5.say()[-1]
    assert m5.ns.Target.IsPicking(m5.ns.Target)


def test_pick_left_click_saves_nearest_named_ancestor(m5):
    leaf = chain(m5, ["MyBarHolder", None, None])[-1]
    m5.stub.focus = leaf
    m5.slash("pick")
    m5.stub.mouseDown("LeftButton")
    assert m5.db.targetFrame == "MyBarHolder"
    assert "XP bar frame set to MyBarHolder" in m5.say()[-1]
    assert not armed(m5)


def test_pick_prefers_the_frame_itself_when_named(m5):
    m5.stub.focus = chain(m5, ["Outer", "Mid", "Leaf"])[-1]
    m5.slash("pick")
    m5.stub.mouseDown("LeftButton")
    assert m5.db.targetFrame == "Leaf"


def test_pick_unnamed_chain_to_uiparent_saves_nothing(m5):
    m5.stub.focus = chain(m5, [None, None, None])[-1]
    m5.db.targetFrame = "Keep"
    m5.slash("pick")
    m5.stub.mouseDown("LeftButton")
    assert m5.db.targetFrame == "Keep"
    assert "no named frame" in m5.say()[-1] and not armed(m5)


def test_pick_never_picks_uiparent_worldframe_or_our_frames(m5):
    m5.slash("test 5")  # creates the overlay
    world = m5.stub.namedFrame("WorldFrame")
    m5.G.WorldFrame = world
    for target in (m5.G.UIParent, world, m5.orbs.overlay, m5.orbs.driver, m5.opt.panel):
        m5.stub.focus = target
        m5.slash("pick")
        m5.stub.mouseDown("LeftButton")
        assert m5.db.targetFrame is None and not armed(m5)


def test_pick_walk_stops_at_our_frames_below_the_root(m5):
    m5.slash("test 5")
    child = m5.lua.eval("CreateFrame")("Frame", None, m5.orbs.overlay)
    m5.stub.focus = child
    m5.slash("pick")
    m5.stub.mouseDown("LeftButton")
    assert m5.db.targetFrame is None


def test_pick_right_click_cancels(m5):
    m5.stub.focus = chain(m5, ["Whatever"])[-1]
    m5.slash("pick")
    m5.stub.mouseDown("RightButton")
    assert m5.db.targetFrame is None and not armed(m5)
    assert "cancelled" in m5.say()[-1]


def test_pick_ignores_other_buttons(m5):
    m5.stub.focus = chain(m5, ["Whatever"])[-1]
    m5.slash("pick")
    m5.stub.mouseDown("MiddleButton")
    assert armed(m5) and m5.db.targetFrame is None
    m5.stub.mouseDown("LeftButton")
    assert m5.db.targetFrame == "Whatever"


def test_pick_times_out_after_15s(m5):
    m5.slash("pick")
    m5.stub.tick(14.9)
    assert armed(m5)
    m5.stub.tick(0.2)
    assert not armed(m5) and "timed out" in m5.say()[-1]
    assert m5.ns.Target.pickFrame.scripts.OnUpdate is None
    assert not m5.ns.Target.IsPicking(m5.ns.Target)


def test_pick_is_idle_when_unarmed_and_after_a_pick(m5):
    m5.stub.focus = chain(m5, ["X"])[-1]
    m5.slash("pick")
    m5.stub.mouseDown("LeftButton")
    assert not armed(m5) and m5.ns.Target.pickFrame.scripts.OnUpdate is None
    m5.db.targetFrame = None
    m5.stub.mouseDown("LeftButton")  # a stray event while unarmed does nothing
    assert m5.db.targetFrame is None


def test_pick_registration_failure_prints_unavailable(m5):
    m5.stub.failEvents["GLOBAL_MOUSE_DOWN"] = True
    m5.slash("pick")
    assert not armed(m5) and "isn't available" in m5.say()[-1]


def test_pick_falls_back_to_getmousefocus(env):
    m5 = build(env, mouse_foci=False)
    f = chain(m5, ["OldStyle"])[-1]
    m5.G.GetMouseFocus = lambda: f
    m5.slash("pick")
    m5.stub.mouseDown("LeftButton")
    assert m5.db.targetFrame == "OldStyle"


def test_pick_survives_throwing_frames(m5):
    f = m5.stub.namedFrame("Weird")
    f.GetName = m5.lua.eval("function() error('secret') end")
    f.GetParent = m5.lua.eval("function() error('secret') end")
    m5.stub.focus = f
    m5.slash("pick")
    m5.stub.mouseDown("LeftButton")  # no error, nothing saved
    assert m5.db.targetFrame is None and not armed(m5)


def test_pick_clear_goes_back_to_auto(m5):
    m5.db.targetFrame = "Foo"
    m5.slash("pick")
    m5.slash("pick clear")
    assert m5.db.targetFrame is None and "auto-detect" in m5.say()[-1] and not armed(m5)


def test_pick_with_an_unknown_name_is_refused(m5):
    m5.slash("pick banana")
    assert "no frame called banana" in m5.say()[-1] and not armed(m5) and m5.db.targetFrame is None


def test_picked_frame_is_used_and_a_hidden_one_falls_back(m5):
    bar = m5.stub.makeBar("MyBar", 100, 50, 600, 12, True)
    bar.name = "MyBar"
    m5.stub.focus = bar
    m5.slash("pick")
    m5.stub.mouseDown("LeftButton")
    assert m5.db.targetFrame == "MyBar"
    tg = m5.ns.Target
    _, _, ok = tg.GetDestination(tg)
    assert ok and tg.lastName == "MyBar"
    m5.slash("status")
    assert any("xp bar frame: picked MyBar, using MyBar" in line for line in m5.say())
    bar.shown = False
    _, _, ok = tg.GetDestination(tg)
    assert ok and tg.lastName == "MainStatusTrackingBarContainer"
    m5.db.targetFrame = "DoesNotExist"
    _, _, ok = tg.GetDestination(tg)
    assert ok and tg.lastName == "MainStatusTrackingBarContainer"


def test_panel_destination_line(m5):
    show(m5)
    assert "MainStatusTrackingBarContainer (auto)" in panel_texts(m5)  # v0.13: the row label says "XP bar frame"
    m5.db.targetFrame = "Nope"
    show(m5)
    assert any(
        t.startswith("Picked frame Nope is unavailable; using Main")
        for t in panel_texts(m5)
    )


def test_pick_refreshes_an_open_panel(m5):
    bar = m5.stub.makeBar("MyBar", 100, 50, 600, 12, True)
    bar.name = "MyBar"
    show(m5)
    m5.stub.focus = bar
    m5.slash("pick")
    m5.stub.mouseDown("LeftButton")
    assert "MyBar (picked)" in panel_texts(m5)


def test_status_shows_auto_without_a_pick(m5):
    m5.slash("status")
    assert any(
        "xp bar frame: auto, using MainStatusTrackingBarContainer" in line
        for line in m5.say()
    )
