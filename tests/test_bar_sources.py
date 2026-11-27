"""Bar sources (Target.lua BAR_SOURCES / PICK_ALIASES): other UI suites' XP bars, found by shape, not by a saved pick."""

import pytest
from test_m5 import build


@pytest.fixture
def m5(env):
    env = build(env)
    env.stub.xp, env.stub.xpMax = 500, 1000
    env.T = env.ns.Target
    return env


def dest(m):
    return m.T.GetDestination(m.T, False, False)


def lua_table(m, *items, **fields):
    return m.lua.table(*items, **fields)


def flare(m, kind="xp", visible=True, value=0.25):
    """FlareUI_XPBar: a container whose unnamed StatusBar child .Left (min 0, max 1) draws the fraction."""
    left = m.stub.makeFreeBar(100, 700, 400, 12, visible, 0, 1, value)
    left.info = lua_table(m, kind=kind)
    container = m.stub.makeBar("FlareUI_XPBar", 50, 650, 1000, 80, True)
    container.Left = left
    return container, left


def daylight(m, bar, enabled=True, throws=False):
    """DaylightUI: D:GetModule("InfoPanel").ns.XP.bar."""
    xp = lua_table(m, bar=bar)
    module = lua_table(m, enabled=enabled, ns=lua_table(m, XP=xp))
    if throws:
        get_module = m.lua.eval('function() error("boom") end')
    else:
        get_module = m.lua.eval(
            "function(self, name) return name == 'InfoPanel' and self.module or nil end"
        )
    m.G.DaylightUI = lua_table(m, GetModule=get_module, module=module)
    return module


def blizzard_manager(m, xp_visible=True):
    """A reputation bar in the main container and the experience bar (with ExhaustionTick) in the secondary one."""
    rep_bar = m.stub.makeFreeBar(10, 10, 800, 10, True, 0, 100, 50, "HORIZONTAL")
    xp_status = m.stub.makeFreeBar(
        300, 40, 600, 10, xp_visible, 0, 1000, 250, "HORIZONTAL"
    )
    xp_bar = lua_table(m, ExhaustionTick=True, StatusBar=xp_status)
    main = lua_table(m, bars=lua_table(m, rep_bar))
    secondary = lua_table(m, bars=lua_table(m, xp_bar))
    m.G.StatusTrackingBarManager = lua_table(
        m, barContainers=lua_table(m, main, secondary)
    )
    return rep_bar, xp_status


# ---------------------------------------------------------------- each source


def test_ellesmere_status_bar(m5):
    m5.stub.makeStatusBar(
        "EllesmereEAB_XPBar_Bar", 100, 700, 400, 12, 0, 1000, 250, "HORIZONTAL", False
    )
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx((200, 706))
    assert m5.T.lastSource == "ellesmere" and m5.T.lastName == "EllesmereEAB_XPBar_Bar"


def test_flare_aims_across_the_left_bar_not_the_container(m5):
    flare(m5)
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx(
        (200, 706)
    )  # 25 % of .Left (left 100, width 400), not of the container
    assert m5.T.lastSource == "flare" and m5.T.lastName == "FlareUI"


def test_flare_showing_reputation_is_skipped(m5):
    flare(m5, kind="rep")
    _x, _y, ok = dest(m5)
    assert (
        ok
        and m5.T.lastSource is None
        and m5.T.lastName == "MainStatusTrackingBarContainer"
    )


def test_flare_hidden_bar_is_skipped(m5):
    flare(m5, visible=False)
    dest(m5)
    assert m5.T.lastSource is None


def test_daylight_xp_bar(m5):
    bar = m5.stub.makeFreeBar(100, 700, 400, 12, True, 0, 1000, 750, "HORIZONTAL")
    daylight(m5, bar)
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx((400, 706))
    assert m5.T.lastSource == "daylight" and m5.T.lastName == "DaylightUI"
    assert m5.T.lastSourceLabel == "DaylightUI"


def test_daylight_disabled_module_is_skipped(m5):
    bar = m5.stub.makeFreeBar(100, 700, 400, 12, True, 0, 1000, 750, "HORIZONTAL")
    daylight(m5, bar, enabled=False)
    dest(m5)
    assert m5.T.lastSource is None


def test_a_throwing_daylight_resolver_does_not_escape(m5):
    daylight(m5, None, throws=True)
    _x, _y, ok = dest(m5)
    assert (
        ok
        and m5.T.lastSource is None
        and m5.T.lastName == "MainStatusTrackingBarContainer"
    )


def test_smooth_experience_bar_prefers_the_visible_main_frame(m5):
    m5.stub.makeBar("SmoothExperienceBarFrame", 100, 700, 400, 12, True)
    m5.stub.makeBar("SmoothExperienceBarDefaultFrame", 1000, 300, 200, 10, True)
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx(
        (300, 706)
    )  # UnitXP 500/1000 across the main frame
    assert m5.T.lastSource == "smoothxp" and m5.T.lastName == "SmoothExperienceBarFrame"


def test_smooth_experience_bar_falls_back_to_the_default_frame(m5):
    m5.stub.makeBar("SmoothExperienceBarFrame", 100, 700, 400, 12, False)
    m5.stub.makeBar("SmoothExperienceBarDefaultFrame", 1000, 300, 200, 10, True)
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx((1100, 305))
    assert m5.T.lastName == "SmoothExperienceBarDefaultFrame"


def test_enhanceqol_keeps_working(m5):
    m5.stub.makeBar("EQOL_XPBar", 100, 700, 400, 12, True)
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx((300, 706))
    assert m5.T.lastSource == "enhanceqol" and m5.T.lastName == "EQOL_XPBar"


def test_blizzard_source_picks_the_bar_with_the_exhaustion_tick(m5):
    _rep_bar, _xp_status = blizzard_manager(m5)
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx(
        (450, 45)
    )  # 250/1000 of the XP bar (left 300, width 600)
    assert m5.T.lastSource == "blizzard" and m5.T.lastName == "Blizzard XP bar"


def test_blizzard_source_prefers_a_visible_bar(m5):
    blizzard_manager(m5, xp_visible=False)
    dest(m5)
    # the only XP bar is hidden: the source is skipped and the usual container answers
    assert m5.T.lastSource is None and m5.T.lastName == "MainStatusTrackingBarContainer"


def test_stub_manager_without_containers_leaves_the_fallbacks(m5):
    m5.stub.makeBar("StatusTrackingBarManager", 0, 0, 800, 10, True)
    dest(m5)
    assert m5.T.lastSource is None and m5.T.lastName == "MainStatusTrackingBarContainer"


# ---------------------------------------------------------------- priority and pick aliases


def test_a_visible_ellesmere_bar_beats_the_blizzard_container(m5):
    m5.stub.makeStatusBar(
        "EllesmereEAB_XPBar_Bar", 100, 700, 400, 12, 0, 1000, 250, "HORIZONTAL", False
    )
    blizzard_manager(m5)
    dest(m5)
    assert m5.T.lastSource == "ellesmere"


def test_flare_beats_the_later_sources(m5):
    flare(m5)
    m5.stub.makeBar("EQOL_XPBar", 100, 500, 400, 12, True)
    dest(m5)
    assert m5.T.lastSource == "flare"


def test_a_users_pick_of_a_real_bar_beats_every_source(m5):
    m5.stub.makeStatusBar(
        "EllesmereEAB_XPBar_Bar", 100, 700, 400, 12, 0, 1000, 250, "HORIZONTAL", False
    )
    m5.stub.makeBar("MyBar", 1000, 300, 200, 10, True)
    m5.db.targetFrame = "MyBar"
    dest(m5)
    assert m5.T.lastName == "MyBar" and m5.T.lastSource is None


def test_a_pick_that_is_gone_falls_to_the_sources(m5):
    m5.stub.makeBar("EQOL_XPBar", 100, 700, 400, 12, True)
    m5.db.targetFrame = "NotThere"
    dest(m5)
    assert m5.T.lastSource == "enhanceqol"


def test_pick_aliases_redirect_to_the_source(m5):
    flare(m5)
    m5.db.targetFrame = "FlareUI_XPBar"  # the container the player picked: its centre is not the fill edge
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx((200, 706))
    assert m5.T.lastSource == "flare" and m5.T.lastSourceViaPick
    assert m5.db.targetFrame == "FlareUI_XPBar"  # the saved variable is untouched


@pytest.mark.parametrize("saved", ["DaylightUIInfoPanel", "DaylightUIInfoPanelBody"])
def test_daylight_pick_aliases(m5, saved):
    m5.stub.makeBar(saved, 0, 0, 1500, 60, True)
    bar = m5.stub.makeFreeBar(100, 700, 400, 12, True, 0, 1000, 750, "HORIZONTAL")
    daylight(m5, bar)
    m5.db.targetFrame = saved
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx((400, 706)) and m5.T.lastSource == "daylight"


def test_ellesmere_pick_alias(m5):
    m5.stub.makeBar("EllesmereEAB_XPBar", 0, 0, 1500, 60, True)
    m5.stub.makeStatusBar(
        "EllesmereEAB_XPBar_Bar", 100, 700, 400, 12, 0, 1000, 250, "HORIZONTAL", False
    )
    m5.db.targetFrame = "EllesmereEAB_XPBar"
    x, y, ok = dest(m5)
    assert ok and (x, y) == pytest.approx((200, 706)) and m5.T.lastSource == "ellesmere"


def test_an_alias_whose_source_does_not_resolve_uses_the_container(m5):
    m5.stub.makeBar("DaylightUIInfoPanel", 0, 0, 1000, 60, True)
    m5.db.targetFrame = "DaylightUIInfoPanel"
    dest(m5)
    assert m5.T.lastSource is None and m5.T.lastName == "DaylightUIInfoPanel"


# ---------------------------------------------------------------- reporting


def test_status_and_options_name_the_addon(m5):
    daylight(
        m5, m5.stub.makeFreeBar(100, 700, 400, 12, True, 0, 1000, 750, "HORIZONTAL")
    )
    m5.slash("status chat")
    assert any("xp bar frame: auto, using DaylightUI" in line for line in m5.say())
    assert m5.ns.Options.panel is not None
