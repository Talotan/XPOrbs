"""The smarter picker: a known addon bar under the cursor saves "@id", an unnamed XP StatusBar saves a path to itself,
and an unnamed bar under an oversized named container is refused (Target.lua smart pick)."""

import pytest
from test_m5 import build, panel_texts, show
from test_pick_scan import click, label_text, over


@pytest.fixture
def m5(env):
    env = build(env)
    env.stub.xp, env.stub.xpMax = 500, 1000
    env.T = env.ns.Target
    return env


def dest(m):
    return m.T.GetDestination(m.T, False, False)


def named_bar(m, name, left, bottom, w, h, visible=True):
    """A named frame (the stub's GetName reads .name, which makeBar leaves unset)."""
    frame = m.stub.makeBar(name, left, bottom, w, h, visible)
    frame.name = name
    return frame


def bar(m, parent, key, left, bottom, w, h, hi, value, level=0):
    """An unnamed visible StatusBar stored under parent[key]."""
    frame = m.stub.makeFreeBar(left, bottom, w, h, True, 0, hi, value)
    frame.level = level
    return m.stub.child(parent, key, frame)


def daylight_panel(m):
    """DaylightUI's XP strip: a big named panel > an unnamed mouse frame > the real bar plus rested and banked bars
    (same max, larger values, same rect). Returns the panel, the mouse frame and the real bar."""
    panel = named_bar(m, "DaylightUIInfoPanel", 100, 100, 600, 200, True)
    mouse = m.stub.child(panel, "xpButton", m.stub.makeFreeBar(120, 110, 300, 14, True))
    banked = bar(m, mouse, "banked", 120, 110, 300, 14, 1000, 1000, level=3)
    rested = bar(m, mouse, "rested", 120, 110, 300, 14, 1000, 800, level=4)
    real = bar(m, mouse, "bar", 120, 110, 300, 14, 1000, 500, level=2)
    m.stub.focus = mouse
    over(m, 200, 117)
    return panel, mouse, real, rested, banked


def daylight_global(m, real):
    xp = m.lua.table(bar=real)
    module = m.lua.table(enabled=True, ns=m.lua.table(XP=xp))
    get_module = m.lua.eval(
        "function(self, name) return name == 'InfoPanel' and self.module or nil end"
    )
    m.G.DaylightUI = m.lua.table(GetModule=get_module, module=module)


# ---------------------------------------------------------------- known bars become source tokens


def test_clicking_the_daylight_bar_saves_the_source_token(m5):
    _panel, _mouse, real, _rested, _banked = daylight_panel(m5)
    daylight_global(m5, real)
    click(m5)
    assert m5.db.targetFrame == "@daylight"
    assert "XP bar frame set to DaylightUI." in m5.say()[-1]
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx((270, 117)) and m5.T.lastSource == "daylight"


def test_the_options_row_and_status_show_the_label_not_the_token(m5):
    _panel, _mouse, real, _rested, _banked = daylight_panel(m5)
    daylight_global(m5, real)
    show(m5)
    click(m5)
    texts = panel_texts(m5)
    assert "DaylightUI (picked)" in texts and not any("@daylight" in t for t in texts)
    m5.slash("status")
    assert any("picked DaylightUI" in line for line in m5.say()) and not any(
        "@" in line for line in m5.say()
    )


def test_the_highlight_label_says_what_a_click_would_save(m5):
    _panel, _mouse, real, _rested, _banked = daylight_panel(m5)
    daylight_global(m5, real)
    m5.slash("pick")
    m5.stub.tick(0.1)
    assert label_text(m5) == "DaylightUI"


def test_a_source_with_a_name_of_its_own_is_still_saved_by_name(m5):
    m5.stub.drawOnly("EQOL_XPBar", 400, 100, 300, 20)
    over(m5, 500, 110)
    click(m5)
    assert m5.db.targetFrame == "EQOL_XPBar"


def test_pick_at_flare_works_and_a_hidden_one_is_reported(m5):
    left = m5.stub.makeFreeBar(100, 700, 400, 12, True, 0, 1, 0.5)
    left.info = m5.lua.table(kind="xp")
    root = named_bar(m5, "FlareUI_XPBar", 50, 650, 1000, 80, True)
    root.Left = left
    m5.slash("pick @flare")
    assert m5.db.targetFrame == "@flare"
    assert m5.say()[-1].endswith("pick: XP bar set to FlareUI")
    assert dest(m5)[2] and m5.T.lastSource == "flare"
    left.shown = False
    m5.slash("pick @Flare")
    assert "not showing right now" in m5.say()[-1]
    m5.slash("pick @nothing")
    assert "no frame called @nothing" in m5.say()[-1]


def test_a_saved_source_that_stops_resolving_falls_back_to_auto_detect(m5):
    m5.db.targetFrame = "@daylight"
    _x, _y, ok = dest(m5)
    assert (
        ok
        and m5.T.lastName == "MainStatusTrackingBarContainer"
        and m5.T.lastSource is None
    )
    show(m5)
    assert any(
        t.startswith("Picked DaylightUI is unavailable; using Main")
        for t in panel_texts(m5)
    )


# ---------------------------------------------------------------- unnamed StatusBars become paths


def test_without_the_addon_table_the_real_bar_is_saved_as_a_path_not_rested_or_banked(
    m5,
):
    daylight_panel(m5)
    click(m5)
    assert m5.db.targetFrame == "DaylightUIInfoPanel.xpButton.bar"
    assert "XP bar frame set to DaylightUIInfoPanel.xpButton.bar." in m5.say()[-1]
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx((270, 117))
    assert m5.T.lastName == "DaylightUIInfoPanel.xpButton.bar"
    show(m5)
    assert "DaylightUIInfoPanel.xpButton.bar (picked)" in panel_texts(m5)


def test_a_fraction_style_bar_matches(m5):
    panel = named_bar(m5, "FractionHolder", 100, 100, 400, 30, True)
    bar(m5, panel, "fill", 110, 105, 380, 12, 1, 0.5)
    m5.stub.focus = panel
    over(m5, 200, 110)
    click(m5)
    assert m5.db.targetFrame == "FractionHolder.fill"
    assert dest(m5)[0] == pytest.approx(300)


def test_a_bar_that_does_not_show_the_players_xp_is_ignored(m5):
    panel = named_bar(m5, "ReputationHolder", 100, 100, 400, 30, True)
    bar(m5, panel, "fill", 110, 105, 380, 12, 1000, 900)
    m5.stub.focus = panel
    over(m5, 200, 110)
    click(m5)
    assert m5.db.targetFrame == "ReputationHolder"


def test_a_path_is_found_by_scanning_when_get_parent_key_is_wrong(m5):
    _panel, _mouse, real, _rested, _banked = daylight_panel(m5)
    real.parentKey = "wrongKey"
    click(m5)
    assert m5.db.targetFrame == "DaylightUIInfoPanel.xpButton.bar"


def test_a_named_xp_bar_is_saved_by_name(m5):
    panel = named_bar(m5, "Holder", 100, 100, 400, 30, True)
    named = m5.stub.makeStatusBar(
        "NamedXPBar", 110, 105, 380, 12, 0, 1000, 500, "HORIZONTAL"
    )
    named.name = "NamedXPBar"
    m5.stub.child(panel, "named", named)
    m5.stub.focus = panel
    over(m5, 200, 110)
    click(m5)
    assert m5.db.targetFrame == "NamedXPBar"


def test_an_unnamed_bar_with_no_path_under_a_huge_container_is_refused(m5):
    huge = named_bar(m5, "HugeContainer", 0, 0, 1500, 800, True)
    anon = m5.stub.makeFreeBar(100, 100, 300, 12, True, 0, 1000, 500)
    anon.createdParent = huge  # a child the parent holds under no key
    m5.stub.focus = anon
    over(m5, 200, 105)
    click(m5)
    assert m5.db.targetFrame is None
    line = m5.say()[-1]
    assert (
        "HugeContainer" in line
        and "not saved" in line
        and "/xporbs pick <FrameName>" in line
        and "/fstack" in line
    )


def test_an_overlay_child_under_the_cursor_still_finds_the_bar_above_it(m5):
    panel = named_bar(m5, "BigPanel", 0, 0, 1500, 800, True)
    xp_bar = bar(m5, panel, "xp", 100, 100, 300, 14, 1000, 500)
    overlay = m5.stub.child(xp_bar, "text", m5.stub.makeFreeBar(100, 100, 300, 14, True))
    m5.stub.focus = overlay  # a mouse-enabled text overlay is what the cursor is over
    over(m5, 200, 105)
    click(m5)
    assert m5.db.targetFrame == "BigPanel.xp"


def test_a_sibling_overlay_under_the_same_holder_finds_the_bar_one_level_up(m5):
    panel = named_bar(m5, "BigPanel", 0, 0, 1500, 800, True)
    holder = m5.stub.child(panel, "strip", m5.stub.makeFreeBar(100, 100, 300, 14, True))
    bar(m5, holder, "fill", 100, 100, 300, 14, 1000, 500)
    overlay = m5.stub.child(holder, "hitbox", m5.stub.makeFreeBar(100, 100, 300, 14, True))
    m5.stub.focus = overlay
    over(m5, 200, 105)
    click(m5)
    assert m5.db.targetFrame == "BigPanel.strip.fill"


def test_a_normal_named_frame_is_saved_as_before(m5):
    holder = named_bar(m5, "MyBarHolder", 100, 50, 600, 12, True)
    m5.stub.focus = holder
    over(m5, 200, 55)
    click(m5)
    assert m5.db.targetFrame == "MyBarHolder"
    assert "XP bar frame set to MyBarHolder" in m5.say()[-1]


def test_a_hidden_pick_is_reported_as_unusable(m5):
    holder = named_bar(m5, "QuietBar", 100, 50, 600, 12, False)
    m5.stub.focus = holder
    over(m5, 200, 55)
    click(m5)
    line = m5.say()[-1]
    assert (
        m5.db.targetFrame == "QuietBar"
        and "can't be measured right now" in line
        and "auto-detection" in line
    )


# ---------------------------------------------------------------- /xporbs pick with paths


def test_pick_by_path_works_and_validates(m5):
    daylight_panel(m5)
    m5.slash("pick DaylightUIInfoPanel.xpButton.bar")
    assert m5.db.targetFrame == "DaylightUIInfoPanel.xpButton.bar"
    assert m5.say()[-1].endswith("pick: XP bar set to DaylightUIInfoPanel.xpButton.bar")
    m5.slash("pick DaylightUIInfoPanel.nothing.here")
    assert "no frame called DaylightUIInfoPanel.nothing.here" in m5.say()[-1]
    assert m5.db.targetFrame == "DaylightUIInfoPanel.xpButton.bar"


def test_pick_by_path_refuses_a_frame_under_a_nameplate(m5):
    plate = m5.stub.namedFrame("NamePlate7")
    m5.stub.child(plate, "bar", m5.stub.makeFreeBar(0, 0, 50, 5, True))
    m5.slash("pick NamePlate7.bar")
    assert m5.db.targetFrame is None and "can't be used" in m5.say()[-1]


def test_a_path_that_stops_resolving_falls_back_to_auto_detect(m5):
    daylight_panel(m5)
    click(m5)
    assert dest(m5)[2] and m5.T.lastName == "DaylightUIInfoPanel.xpButton.bar"
    m5.G.DaylightUIInfoPanel.xpButton = None  # the addon rebuilt its frames
    _x, _y, ok = dest(m5)
    assert ok and m5.T.lastName == "MainStatusTrackingBarContainer"
    m5.G.DaylightUIInfoPanel = None
    assert dest(m5)[2] and m5.T.lastName == "MainStatusTrackingBarContainer"


def test_a_dotted_global_name_is_still_found(m5):
    m5.stub.makeBar("Odd.Name", 100, 50, 600, 12, True)
    m5.db.targetFrame = "Odd.Name"
    assert dest(m5)[2] and m5.T.lastName == "Odd.Name"


# ---------------------------------------------------------------- no per-frame allocation


def measure_steady_state_allocation(m, frames=300):
    """KB the addon allocates over `frames` GetDestination calls with no collection. The loop runs four times and the last
    pass is reported: the early passes absorb one-off warm-up (lazily cached parse, the stub's first calls)."""
    return m.lua.eval(
        """function(target, frames)
            local fn = target.GetDestination
            local grown
            for _ = 1, 4 do
                collectgarbage("collect")
                collectgarbage("stop")
                local before = collectgarbage("count")
                for _ = 1, frames do
                    fn(target, false, false)
                end
                grown = collectgarbage("count") - before
                collectgarbage("restart")
            end
            return grown
        end"""
    )(m.T, frames)


def test_a_bar_source_destination_allocates_nothing_per_frame(m5):
    m5.stub.makeStatusBar("EQOL_XPBar", 100, 700, 400, 12, 0, 1000, 250, "HORIZONTAL")
    assert dest(m5)[2] and m5.T.lastSource == "enhanceqol"
    assert measure_steady_state_allocation(m5) < 1.0
    m5.G.EQOL_XPBar = None
    left = m5.stub.makeFreeBar(100, 700, 400, 12, True, 0, 1, 0.25)
    left.info = m5.lua.table(kind="xp")
    root = named_bar(m5, "FlareUI_XPBar", 50, 650, 1000, 80, True)
    root.Left = left
    assert dest(m5)[2] and m5.T.lastSource == "flare"
    assert measure_steady_state_allocation(m5) < 1.0
    m5.db.targetFrame = "@flare"
    assert dest(m5)[2] and m5.T.lastSource == "flare"
    assert measure_steady_state_allocation(m5) < 1.0


def test_a_dotted_path_destination_allocates_nothing_per_frame(m5):
    daylight_panel(m5)
    m5.db.targetFrame = "DaylightUIInfoPanel.xpButton.bar"
    assert dest(m5)[2] and m5.T.lastName == "DaylightUIInfoPanel.xpButton.bar"
    assert measure_steady_state_allocation(m5) < 1.0
