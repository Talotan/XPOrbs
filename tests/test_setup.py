"""C3: the "find your XP bar" window (Setup.lua): when it opens, what its controls write, the picker round trip."""

import pytest
from conftest import ROOT, lua_list
from test_m5 import build
from test_v013 import no_template


@pytest.fixture
def m(env):
    return build(env)


def no_bar(m):
    m.G.MainStatusTrackingBarContainer.shown = False


def world(m):
    m.ns.fire("PLAYER_ENTERING_WORLD")


def window(m):
    return m.ns.Setup.window


def open_now(m):
    """The window open on a no-bar client: world entry, then the timer."""
    no_bar(m)
    world(m)
    m.stub.runTimers()
    assert window(m) is not None
    return window(m)


def controls(m):
    return m.ns.Setup.controls


def updaters(m):
    return [f for f in lua_list(m.stub.frames) if f.scripts.OnUpdate is not None]


# ---------------------------------------------------------------- when it opens


def test_prompt_appears_after_the_delay_when_no_bar_is_visible(m):
    no_bar(m)
    world(m)
    assert window(m) is None  # nothing yet: the timer has not fired
    assert len(m.stub.timers) == 1 and m.stub.timers[1].delay == 5
    m.stub.runTimers()
    win = window(m)
    assert win is not None and win.shown
    assert win.calls["SetFrameStrata"][1] == "DIALOG" and win.width == 320
    assert m.ns.Setup.statusText.text == "Still not found"


def test_not_when_a_bar_is_found(m):
    world(m)
    m.stub.runTimers()
    assert window(m) is None


def test_not_in_portrait_mode(m):
    no_bar(m)
    m.ns.debugForceMax = True
    world(m)
    m.stub.runTimers()
    assert window(m) is None
    m.slash("test 5")  # and a burst's no-bar notice does not open it either
    assert window(m) is None


def test_not_when_dismissed(m):
    no_bar(m)
    m.db.setupDismissed = True
    world(m)
    m.stub.runTimers()
    m.slash("test 5")
    assert window(m) is None


def test_not_when_the_addon_is_disabled(m):
    no_bar(m)
    m.db.enabled = False
    world(m)
    m.stub.runTimers()
    assert window(m) is None


def test_only_once_per_session(m):
    open_now(m)
    m.ns.Setup.Close(m.ns.Setup)
    assert not window(m).shown
    world(m)
    assert len(m.stub.timers) == 0  # no second look is even scheduled
    m.slash("test 5")  # nor does the burst-time notice reopen it
    assert not window(m).shown


def test_waits_for_combat_to_end(m):
    no_bar(m)
    m.stub.inCombat = True
    world(m)
    m.stub.runTimers()
    assert window(m) is None
    assert m.ns.Setup.eventFrame.events["PLAYER_REGEN_ENABLED"]
    m.stub.inCombat = False
    m.ns.fire("PLAYER_REGEN_ENABLED")
    assert window(m) is not None and window(m).shown
    assert not m.ns.Setup.eventFrame.events[
        "PLAYER_REGEN_ENABLED"
    ]  # registered only while waiting


def test_a_bar_that_shows_up_during_combat_cancels_the_prompt(m):
    no_bar(m)
    m.stub.inCombat = True
    world(m)
    m.stub.runTimers()
    m.G.MainStatusTrackingBarContainer.shown = True
    m.stub.inCombat = False
    m.ns.fire("PLAYER_REGEN_ENABLED")
    assert window(m) is None


def test_waits_while_the_ui_is_hidden_and_skips_if_the_bar_comes_back(m):
    # an intro cinematic (or Alt+Z) hides UIParent, so no bar is visible: that is not "no bar"
    m.G.UIParent.shown = False
    no_bar(m)
    world(m)
    m.stub.runTimers()
    assert window(m) is None
    assert len(m.stub.timers) == 1  # looks again later instead of giving up or opening
    m.slash("test 5")  # a burst's no-bar notice waits too
    assert window(m) is None
    m.G.UIParent.shown = True
    m.G.MainStatusTrackingBarContainer.shown = True
    m.stub.runTimers()
    assert window(m) is None


def test_opens_once_the_ui_is_back_if_there_is_still_no_bar(m):
    m.G.UIParent.shown = False
    no_bar(m)
    world(m)
    m.stub.runTimers()
    m.stub.runTimers()  # still hidden: keeps waiting
    assert window(m) is None
    m.G.UIParent.shown = True
    m.stub.runTimers()
    assert window(m) is not None and window(m).shown


def test_the_burst_time_trigger(m):
    no_bar(m)
    m.slash("test 5")  # a burst whose destination is the bottom-centre fallback
    assert window(m) is not None and window(m).shown


def test_the_burst_time_trigger_waits_for_combat_too(m):
    no_bar(m)
    m.stub.inCombat = True
    m.slash("test 5")
    assert window(m) is None
    m.stub.inCombat = False
    m.ns.fire("PLAYER_REGEN_ENABLED")
    assert window(m) is not None


def test_a_found_bar_burst_never_asks(m):
    m.slash("test 5")
    assert window(m) is None


def test_without_c_timer_the_burst_time_trigger_still_works(m):
    m.G.C_Timer = None
    no_bar(m)
    world(m)  # no timer API: nothing to schedule, and no error
    assert window(m) is None
    m.slash("test 5")
    assert window(m) is not None


def test_a_throwing_timer_api_is_swallowed(m):
    m.lua.execute("C_Timer.After = function() error('no timers today') end")
    no_bar(m)
    world(m)
    assert window(m) is None
    world(m)  # not stuck "pending": a second look is tried
    m.slash("test 5")
    assert window(m) is not None


def test_slash_setup_forces_it_open(m):
    m.db.setupDismissed = True
    m.slash(
        "setup"
    )  # a bar is visible and the prompt is dismissed: the command ignores both
    assert window(m) is not None and window(m).shown
    assert m.ns.Setup.statusText.text == "Using: MainStatusTrackingBarContainer"


def test_help_lists_setup(m):
    m.slash("help")
    assert any("/xporbs setup" in line for line in m.say())


def test_slash_setup_reopens_after_done(m):
    m.slash("setup")
    m.stub.click(controls(m).done)
    assert not window(m).shown
    m.slash("setup")
    assert window(m).shown


# ---------------------------------------------------------------- the controls


def test_shape_radios_write_the_db_and_sync_the_options_panel(m):
    open_now(m)
    c = controls(m)
    assert (
        c.shape_bar.checked
        and not c.shape_vertical.checked
        and not c.shape_round.checked
    )
    m.stub.click(c.shape_vertical)
    assert m.db.glowShape == "vertical"
    assert c.shape_vertical.checked and not c.shape_bar.checked
    assert m.opt.controls["glowShape_vertical"].checked  # the options panel followed
    m.stub.click(c.shape_round)
    assert (
        m.db.glowShape == "round"
        and c.shape_round.checked
        and not c.shape_vertical.checked
    )
    m.stub.click(c.shape_round)  # clicking the selected one keeps it selected
    assert c.shape_round.checked


def test_offset_sliders_write_the_db_with_ranges_from_ns_ranges(m):
    open_now(m)
    c = controls(m)
    for key in ("glowOffsetX", "glowOffsetY"):
        low, high, step = (m.ns.ranges[key][i] for i in (1, 2, 3))
        assert (c[key].minV, c[key].maxV, c[key].step) == (low, high, step)
    m.stub.slide(c.glowOffsetX, -20)
    m.stub.slide(c.glowOffsetY, 35)
    assert (m.db.glowOffsetX, m.db.glowOffsetY) == (-20, 35)
    assert c.glowOffsetX_value.text == "-20 px" and c.glowOffsetY_value.text == "35 px"
    assert m.opt.controls["glowOffsetX"].value == -20  # the options panel followed
    m.stub.slide(c.glowOffsetX, 500)  # clamped to the range
    assert m.db.glowOffsetX == 200


def test_the_window_reads_the_db_when_it_opens(m):
    m.db.glowShape, m.db.glowOffsetX, m.db.glowOffsetY, m.db.setupDismissed = (
        "round",
        12,
        -9,
        True,
    )
    m.slash("setup")
    c = controls(m)
    assert (
        c.shape_round.checked
        and c.glowOffsetX.value == 12
        and c.glowOffsetY.value == -9
    )
    assert c.dismiss.checked
    assert (m.db.glowOffsetX, m.db.glowOffsetY) == (12, -9)  # reading is not writing


def test_no_range_literals_in_setup_lua():
    src = (ROOT / "Setup.lua").read_text(encoding="utf-8")
    assert "-100" not in src and "100, 1" not in src


def test_dont_ask_again_checkbox(m):
    open_now(m)
    c = controls(m)
    assert not c.dismiss.checked and m.db.setupDismissed is False
    m.stub.click(c.dismiss)
    assert m.db.setupDismissed is True
    m.stub.click(c.dismiss)
    assert m.db.setupDismissed is False


def test_done_closes_and_esc_closes(m):
    win = open_now(m)
    m.stub.click(controls(m).done)
    assert not win.shown
    m.slash("setup")
    assert win.shown and win.calls["EnableKeyboard"][1] is True
    win.scripts.OnKeyDown(win, "ESCAPE")
    assert win.calls["SetPropagateKeyboardInput"][1] is False  # Escape is ours
    win.scripts.OnKeyUp(win, "ESCAPE")
    assert not win.shown
    m.slash("setup")
    win.scripts.OnKeyDown(win, "W")
    assert (
        win.calls["SetPropagateKeyboardInput"][1] is True
    )  # movement keys go to the game
    win.scripts.OnKeyUp(win, "W")
    assert win.shown


def test_the_window_is_unnamed_movable_and_draggable(m):
    win = open_now(m)
    assert win.name is None
    assert (
        win.calls["SetMovable"][1] is True
        and win.calls["RegisterForDrag"][1] == "LeftButton"
    )
    win.scripts.OnDragStart(win)
    assert win.calls["StartMoving"] is not None
    win.scripts.OnDragStop(win)
    assert win.calls["StopMovingOrSizing"] is not None


def test_a_plain_frame_stands_in_when_the_backdrop_template_is_missing(env):
    def break_backdrop(e):
        e.lua.execute(
            "local fm = getmetatable(UIParent).__index; fm.SetBackdrop = function() error('no backdrop') end"
        )
        no_template("TooltipBackdropTemplate", "BackdropTemplate")(
            e
        )  # neither window template exists

    m = build(env, pre=break_backdrop)
    win = open_now(m)
    fills = [
        f
        for f in lua_list(m.stub.frames)
        if f.kind == "Texture"
        and f.parentFrame is not None
        and f.calls
        and f.calls["SetColorTexture"]
    ]
    same = m.lua.eval("rawequal")
    assert any(same(f.parentFrame, win) for f in fills)


# ---------------------------------------------------------------- pick and test


def test_pick_hides_the_window_and_shows_it_again_when_picking_ends(m):
    open_now(m)
    c = controls(m)
    m.stub.click(c.pick)
    assert m.ns.Target.IsPicking(m.ns.Target)
    assert not window(m).shown  # out of the way of the bar
    assert m.ns.Setup.pickWatcher.scripts.OnUpdate is not None
    m.stub.tick(0.05)
    assert not window(m).shown  # still picking
    m.stub.mouseDown("RightButton")  # cancelled
    m.stub.tick(0.05)
    assert window(m).shown
    assert m.ns.Setup.pickWatcher.scripts.OnUpdate is None
    assert m.ns.Setup.statusText.text == "Still not found"


def test_a_successful_pick_updates_the_status_line(m):
    open_now(m)
    m.stub.drawOnly("MyXPBar", 100, 10, 500, 12)
    m.stub.focus = m.G.MyXPBar
    m.stub.cursor.x, m.stub.cursor.y = 300, 15
    m.stub.click(controls(m).pick)
    m.stub.mouseDown("LeftButton")
    m.stub.tick(0.05)
    assert m.db.targetFrame == "MyXPBar"
    assert window(m).shown and m.ns.Setup.statusText.text == "Using: MyXPBar"


def test_pick_that_cannot_arm_leaves_the_window_up(m):
    open_now(m)
    m.lua.execute(
        "local fm = getmetatable(UIParent).__index; fm.RegisterEvent = function() error('nope') end"
    )
    m.stub.click(controls(m).pick)
    assert window(m).shown and m.ns.Setup.pickWatcher is None


def test_test_button_fires_a_burst(m):
    open_now(m)
    m.stub.click(controls(m).test)
    assert any("test: 10%" in line for line in m.say())
    assert m.orbs.Info(m.orbs)[0]  # the driver is live: orbs are flying


def test_nothing_keeps_an_onupdate_afterwards(m):
    open_now(m)
    assert updaters(m) == []  # opening starts nothing
    m.stub.click(controls(m).test)
    m.stub.click(controls(m).pick)
    assert len(updaters(m)) == 3  # the driver, the picker and our watcher
    m.stub.mouseDown("RightButton")
    m.run(6)
    assert not m.orbs.Info(m.orbs)[0]
    assert updaters(m) == []


# ---------------------------------------------------------------- settings plumbing


def test_dismissed_default_sanitize_and_reset(m):
    assert m.ns.defaults.setupDismissed is False and m.db.setupDismissed is False
    m.db.setupDismissed = True
    m.slash("reset")
    assert m.db.setupDismissed is False


def test_a_junk_dismissed_value_loads_as_false(env):
    env.G.XPOrbsDB = env.lua.table_from({"version": 6, "setupDismissed": "yes"})
    m = build(env)
    assert m.db.setupDismissed is False


def test_setup_is_in_the_toc_after_options():
    toc = (ROOT / "XPOrbs.toc").read_text(encoding="utf-8").splitlines()
    names = [line.strip() for line in toc]
    assert names.index("Setup.lua") > names.index(
        "Options.lua"
    )  # Preview.lua sits between them
