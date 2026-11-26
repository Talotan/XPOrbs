"""Round 5: the options panel and the floating windows use Blizzard's own templates (stepper slider, stepper dropdown,
tooltip nine-slice border) and fall back to the old widgets when the client lacks them."""

import pytest
from conftest import ROOT
from test_m5 import build, ctl, show
from test_setup import open_now
from test_v013 import no_template

SLIDER = "MinimalSliderWithSteppersTemplate"
DROPDOWN = "XPOrbsDropdownWithSteppersTemplate"
TOOLTIP = "TooltipBackdropTemplate"

COUNT_LOOK_WRITES = """
function(ns)
    local base, n = ns.SetLook, 0
    ns.SetLook = function(...)
        n = n + 1
        return base(...)
    end
    return function()
        return n
    end
end
"""


@pytest.fixture
def m(env):
    return build(env)


def selected(dd):
    entries = dd.menuRoot.entries
    return [bool(entries[i]["selected"]) for i in range(1, len(entries) + 1)]


def counting(env):
    """build() with ns.SetLook wrapped: returns (m, count) where count() is the number of look writes so far."""
    m = build(env)
    return m, m.lua.eval(COUNT_LOOK_WRITES)(m.ns)


def up(m):
    """The panel shown on a client with the Settings panel (the orb preview docks to it)."""
    m.G.SettingsPanel = m.lua.eval("{}")
    show(m)


# ---------------------------------------------------------------- the toc and the template file


def test_templates_xml_is_in_the_toc_before_the_options_panel():
    toc = [
        line.strip()
        for line in (ROOT / "XPOrbs.toc").read_text(encoding="utf-8").splitlines()
    ]
    assert "Templates.xml" in toc and toc.index("Templates.xml") < toc.index(
        "Options.lua"
    )
    xml = (ROOT / "Templates.xml").read_text(encoding="utf-8")
    assert (
        'name="XPOrbsDropdownWithSteppersTemplate"' in xml
        and 'parentKey="Dropdown"' in xml
    )


# ---------------------------------------------------------------- sliders


def test_sliders_use_the_stepper_template_and_hide_its_captions(m):
    cap = ctl(m, "cap")
    assert cap.template == SLIDER and cap.Slider is not None
    # ns.ranges.cap = { 5, 80, 1 }: min, max and a step COUNT of 75, with no template captions
    args = cap.initArgs
    assert (args["min"], args["max"], args["steps"]) == (5, 80, 75)
    assert len(list(args["formatters"].keys())) == 0
    assert not any(
        cap[k].shown for k in ("LeftText", "RightText", "TopText", "MinText", "MaxText")
    )
    assert (cap.minV, cap.maxV, cap.step) == (5, 80, 1)


def test_sliders_fall_back_to_the_old_template_when_the_stepper_one_is_missing(env):
    m = build(env, pre=no_template(SLIDER))
    show(m)
    cap = ctl(m, "cap")
    assert cap.template == "OptionsSliderTemplate" and cap.Slider is None
    m.stub.slide(cap, 12)
    assert m.db.cap == 12 and cap.value == 12


def test_sliders_still_work_with_no_slider_template_at_all(env):
    m = build(env, pre=no_template(SLIDER, "OptionsSliderTemplate"))
    show(m)
    m.stub.slide(ctl(m, "cap"), 9)
    assert m.db.cap == 9


def test_a_template_that_lacks_the_mixin_falls_back(env):
    m = build(env, pre=lambda e: e.lua.execute("MinimalSliderWithSteppersMixin = nil"))
    assert ctl(m, "cap").template == "OptionsSliderTemplate"


def test_one_write_per_user_change_and_none_on_refresh(env):
    m, count = counting(env)
    show(m)
    show(m)
    assert count() == 0  # opening and refreshing the panel writes nothing
    size = ctl(m, "size")
    m.stub.slide(size, 20)
    assert count() == 1 and m.db.size == 20
    m.stub.slide(size, 20)  # same value: no event, no write
    assert count() == 1
    show(m)  # a refresh puts the stored value back without writing it again
    assert count() == 1 and size.value == 20
    size.Forward.scripts.OnClick(size.Forward)  # the right arrow: one step, one write
    assert count() == 2 and m.db.size == 21 and size.value == 21
    size.Back.scripts.OnClick(size.Back)
    assert count() == 3 and m.db.size == 20


def test_changing_the_range_does_not_write(env):
    m, count = counting(env)
    show(m)
    before = m.stub.initCalls
    m.slash("shape retro")  # the size slider's limits follow the orb shape
    show(m)
    assert m.stub.initCalls > before
    assert (
        count() <= 1
    )  # at most the shape switch's own write, never the slider's re-Init


def test_slider_enable_and_disable_reach_the_template(m):
    show(m)
    trail = ctl(m, "trailOpacity")
    trail.Disable(trail)
    assert trail.IsEnabled(trail) is False and trail.tplEnabled is False
    trail.Enable(trail)
    assert trail.IsEnabled(trail) is True and trail.tplEnabled is True


# ---------------------------------------------------------------- dropdowns


def test_dropdowns_use_the_stepper_template(m):
    dd = m.opt.soundDropdown
    host = dd.xpHost
    same = m.lua.eval("rawequal")
    assert host.template == DROPDOWN and dd.template == "WowStyle2DropdownTemplate"
    assert host.IncrementButton is not None and host.DecrementButton is not None
    assert same(host.Dropdown, dd) and same(m.opt.controls["soundVoice"], dd)


def test_dropdowns_fall_back_to_the_plain_menu_button(env):
    m = build(env, pre=no_template(DROPDOWN))
    dd = m.opt.soundDropdown
    assert dd.template == "WowStyle1DropdownTemplate" and dd.xpHost is None
    assert m.stub.pickMenu(dd, "Coin") is True and m.db.soundVoice == "coin"


def test_the_voice_arrows_cycle_the_choices_and_write(m):
    show(m)
    dd = m.opt.soundDropdown
    host = dd.xpHost
    assert selected(dd) == [True, False, False, False] and m.db.soundVoice == "glass"
    host.DecrementButton.scripts.OnClick(
        host.DecrementButton
    )  # already at the first: nothing
    assert m.db.soundVoice == "glass"
    host.IncrementButton.scripts.OnClick(host.IncrementButton)
    assert m.db.soundVoice == "coin" and selected(dd) == [False, True, False, False]
    host.IncrementButton.scripts.OnClick(host.IncrementButton)
    assert m.db.soundVoice == "swish"
    host.DecrementButton.scripts.OnClick(host.DecrementButton)
    assert m.db.soundVoice == "coin" and selected(dd) == [False, True, False, False]


def test_the_choice_arrows_use_the_same_write_path_as_the_menu(m):
    show(m)
    dd = m.opt.flightDropdown
    assert m.db.flightPath == "smooth"
    dd.xpHost.IncrementButton.scripts.OnClick(dd.xpHost.IncrementButton)
    via_arrow = m.db.flightPath
    assert via_arrow != "smooth" and selected(dd).count(True) == 1
    m.stub.pickMenu(dd, "Smooth (default)")
    assert m.db.flightPath == "smooth"
    m.stub.pickMenu(dd, dd.menuRoot.entries[2]["text"])
    assert m.db.flightPath == via_arrow  # a pick from the list lands on the same value


def test_with_no_dropdown_template_at_all_the_radios_stand_in(env):
    m = build(env, pre=no_template(DROPDOWN, "WowStyle1DropdownTemplate"))
    assert m.opt.soundDropdown is None and m.opt.flightDropdown is None
    assert m.opt.controls["soundVoice_coin"] is not None


# ---------------------------------------------------------------- window borders


def assert_native_border(win):
    assert win.template == TOOLTIP and win.NineSlice is not None
    colour = win.calls["SetBackdropColor"]
    assert [round(colour[i], 2) for i in (1, 2, 3, 4)] == [0.07, 0.07, 0.10, 0.95]
    assert (
        win.calls["SetBackdropBorderColor"] is None and win.calls["SetBackdrop"] is None
    )  # the art, untinted


def assert_old_border(win):
    assert win.template == "BackdropTemplate"
    assert (
        win.calls["SetBackdropBorderColor"] is not None
    )  # today's tinted tooltip border


def test_the_preview_windows_use_the_tooltip_border(m):
    up(m)
    pv, sp = m.ns.Preview, m.ns.ShapePreview
    assert pv.window is not None and sp.window is not None
    assert_native_border(pv.window)
    assert_native_border(sp.window)


def test_the_preview_windows_fall_back_to_the_tinted_backdrop(env):
    m = build(env, pre=no_template(TOOLTIP))
    up(m)
    assert_old_border(m.ns.Preview.window)
    assert_old_border(m.ns.ShapePreview.window)


def test_the_setup_window_uses_the_tooltip_border(m):
    assert_native_border(open_now(m))


def test_the_setup_window_falls_back_to_the_tinted_backdrop(env):
    assert_old_border(open_now(build(env, pre=no_template(TOOLTIP))))


def test_the_calibration_panel_uses_the_tooltip_border(m):
    m.ns.Calib.Open()
    win = m.ns.Calib.panel
    assert win.template == TOOLTIP and win.calls["SetBackdropBorderColor"] is None
    assert win.calls["SetBackdropColor"] is not None


def test_the_calibration_panel_falls_back_to_the_tinted_backdrop(env):
    m = build(env, pre=no_template(TOOLTIP))
    m.ns.Calib.Open()
    assert_old_border(m.ns.Calib.panel)
