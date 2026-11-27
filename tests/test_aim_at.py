"""db.targetAnchor ("Aim at"): the fill edge by default, or a corner, edge or the centre of the bar frame; the
Target.lastRect it exposes; the Arrival tab's Auto radio and 3 x 3 grid."""

import pytest
from test_m5 import build, ctl, show
from test_v013 import run_until_flash

POINTS = [
    "TOPLEFT",
    "TOP",
    "TOPRIGHT",
    "LEFT",
    "CENTER",
    "RIGHT",
    "BOTTOMLEFT",
    "BOTTOM",
    "BOTTOMRIGHT",
]
# the default test bar (MainStatusTrackingBarContainer): left 400, bottom 20, 800 x 10
BAR = {
    "TOPLEFT": (400, 30),
    "TOP": (800, 30),
    "TOPRIGHT": (1200, 30),
    "LEFT": (400, 25),
    "CENTER": (800, 25),
    "RIGHT": (1200, 25),
    "BOTTOMLEFT": (400, 20),
    "BOTTOM": (800, 20),
    "BOTTOMRIGHT": (1200, 20),
}


@pytest.fixture
def m(env):
    m = build(env)
    m.stub.xp, m.stub.xpMax = 250, 1000
    return m


def dest(m, *args):
    tg = m.ns.Target
    return tg.GetDestination(tg, *args)


def same(m, a, b):
    return m.lua.eval("rawequal")(a, b)


def vertical_bar(m):
    """A vertical StatusBar (left 100, bottom 200, 20 x 400) as the only bar."""
    m.G.MainStatusTrackingBarContainer.shown = False
    m.stub.makeStatusBar("EQOL_XPBar", 100, 200, 20, 400, 0, 1000, 250, "VERTICAL")


# ---------------------------------------------------------------- the maths in GetDestination


def test_the_default_is_fill_and_unchanged(m):
    assert m.db.targetAnchor == "fill"
    x, y, ok = dest(m)
    assert ok and (x, y) == (pytest.approx(600), pytest.approx(25))
    x, y, ok = dest(m, True)  # a round frame's centre
    assert (x, y) == (pytest.approx(800), pytest.approx(25))


@pytest.mark.parametrize("point", POINTS)
def test_all_nine_points_of_a_horizontal_bar(m, point):
    m.db.targetAnchor = point
    x, y, ok = dest(m)
    assert ok and (x, y) == pytest.approx(BAR[point])


@pytest.mark.parametrize("point", ["TOPLEFT", "CENTER", "BOTTOMRIGHT"])
def test_the_offset_is_added_after_the_point(m, point):
    m.db.targetAnchor = point
    m.db.glowOffsetX, m.db.glowOffsetY = 150, -200
    x, y, _ = dest(m)
    assert (x, y) == pytest.approx((BAR[point][0] + 150, BAR[point][1] - 200))


def test_the_xp_value_does_not_move_a_chosen_point(m):
    m.db.targetAnchor = "RIGHT"
    for xp in (0, 500, 1000):
        m.stub.xp = xp
        assert tuple(dest(m))[:2] == pytest.approx((1200, 25))


def test_a_chosen_point_also_works_with_an_unreadable_xp(m):
    m.db.targetAnchor = "TOPLEFT"
    m.stub.xp, m.stub.xpMax = m.stub.SECRET, m.stub.SECRET
    x, y, ok = dest(
        m
    )  # no last readable pair: the fill path would fall back to the centre
    assert ok and (x, y) == pytest.approx((400, 30))


def test_a_chosen_point_replaces_the_round_centre_too(m):
    m.db.targetAnchor = "TOPLEFT"
    x, y, _ = dest(m, True)
    assert (x, y) == pytest.approx((400, 30))


def test_a_vertical_status_bar_takes_the_top(m):
    vertical_bar(m)
    m.db.targetAnchor = "TOP"
    x, y, ok = dest(m)
    assert ok and (x, y) == pytest.approx((110, 600))
    m.db.glowOffsetX, m.db.glowOffsetY = 150, -200
    x, y, _ = dest(m)
    assert (x, y) == pytest.approx((260, 400))


def test_a_vertical_status_bar_still_reports_vertical_for_the_flash(m):
    vertical_bar(m)
    tg = m.ns.Target
    dest(m)
    assert tg.lastVertical is True  # today, with fill
    m.db.targetAnchor = "BOTTOMLEFT"
    x, y, _ = dest(m)
    assert (x, y) == pytest.approx((100, 200)) and tg.lastVertical is True


def test_a_horizontal_bar_is_not_vertical_whatever_the_point(m):
    m.db.targetAnchor = "TOP"
    dest(m)
    assert m.ns.Target.lastVertical is False


def test_fill_on_a_vertical_bar_is_unchanged(m):
    vertical_bar(m)
    x, y, _ = dest(m)
    assert (x, y) == pytest.approx((110, 300))


def test_the_vertical_glow_shape_still_flags_a_plain_frame(m):
    m.stub.makeBar("TallBar", 100, 200, 20, 400, True)
    m.db.targetFrame = "TallBar"
    m.db.glowShape = "vertical"
    m.db.targetAnchor = "TOPRIGHT"
    x, y, ok = dest(m)
    assert ok and (x, y) == pytest.approx((120, 600))
    assert m.ns.Target.lastVertical is True


# ---------------------------------------------------------------- portrait and fallback


def test_portrait_mode_ignores_the_point_and_aims_at_the_portrait_centre(m):
    m.stub.makeBar("PlayerPortrait", 100, 700, 90, 90, True)
    for value in ("fill", "TOPLEFT", "BOTTOMRIGHT"):
        m.db.targetAnchor = value
        x, y, ok = dest(m, False, True)
        assert ok and (x, y) == pytest.approx((145, 745))
        assert m.ns.Target.lastName == "PlayerPortrait"


def test_portrait_mode_without_a_usable_portrait_uses_the_point_on_the_bar(m):
    m.db.targetAnchor = "TOPLEFT"
    x, y, ok = dest(m, False, True)  # the stub has no portrait frame at all
    assert ok and (x, y) == pytest.approx((400, 30))


def test_the_fallback_destination_is_offset_only(m):
    m.G.MainStatusTrackingBarContainer.shown = False
    m.db.targetAnchor = "TOPLEFT"
    m.db.glowOffsetX, m.db.glowOffsetY = 10, 5
    x, y, ok = dest(m)
    assert not ok and (x, y) == (pytest.approx(960 + 10), pytest.approx(20 + 5))


# ---------------------------------------------------------------- lastRect


def test_last_rect_holds_the_frame_rect_and_is_one_reused_table(m):
    tg = m.ns.Target
    dest(m)
    rect = tg.lastRect
    assert (rect.left, rect.bottom, rect.w, rect.h) == (400, 20, 800, 10)
    assert (tg.lastW, tg.lastH) == (800, 10)
    m.db.targetAnchor = "TOPLEFT"
    dest(m)
    assert same(m, tg.lastRect, rect)  # not a new table each frame


def test_last_rect_is_the_rect_not_the_aimed_point_or_the_offset(m):
    m.db.targetAnchor = "BOTTOMRIGHT"
    m.db.glowOffsetX = 150
    dest(m)
    rect = m.ns.Target.lastRect
    assert (rect.left, rect.bottom, rect.w, rect.h) == (400, 20, 800, 10)


def test_last_rect_is_the_portrait_rect_in_portrait_mode(m):
    m.stub.makeBar("PlayerPortrait", 100, 700, 90, 90, True)
    dest(m, False, True)
    rect = m.ns.Target.lastRect
    assert (rect.left, rect.bottom, rect.w, rect.h) == (100, 700, 90, 90)


def test_last_rect_is_cleared_on_the_fallback_and_set_again_after(m):
    tg = m.ns.Target
    dest(m)
    assert tg.lastRect is not None
    m.G.MainStatusTrackingBarContainer.shown = False
    dest(m)
    assert tg.lastRect is None
    m.G.MainStatusTrackingBarContainer.shown = True
    dest(m)
    assert tg.lastRect.w == 800


def test_the_orb_flash_lands_on_the_chosen_point(m):
    m.db.targetAnchor = "TOPRIGHT"
    m.db.glowOffsetX = -20
    m.slash("test 5")
    fl = run_until_flash(m)
    assert (fl.points[1][4], fl.points[1][5]) == pytest.approx((1200 - 20, 30))


# ---------------------------------------------------------------- the saved value


@pytest.mark.parametrize("value", ["fill"] + POINTS)
def test_valid_values_survive_a_reload(env, value):
    env.G.XPOrbsDB = env.lua.table_from({"targetAnchor": value})
    assert build(env).db.targetAnchor == value


@pytest.mark.parametrize("bad", ["", "MIDDLE", "topleft", "Fill", 3, True])
def test_a_bad_value_sanitizes_to_fill(env, bad):
    env.G.XPOrbsDB = env.lua.table_from({"targetAnchor": bad})
    assert build(env).db.targetAnchor == "fill"


def test_slash_reset_restores_fill(m):
    m.db.targetAnchor = "BOTTOM"
    m.slash("reset")
    assert m.db.targetAnchor == "fill"


# ---------------------------------------------------------------- the Arrival tab row


def test_the_row_has_an_auto_radio_and_nine_grid_radios(m):
    show(m)
    assert ctl(m, "targetAnchor_fill") is not None
    for point in POINTS:
        assert ctl(m, "targetAnchor_" + point) is not None
    assert m.opt.rows["targetAnchor"].height == 62


def test_the_radios_set_the_key_and_refresh_the_checked_state(m):
    show(m)
    values = ["fill"] + POINTS

    def checked():
        return [v for v in values if ctl(m, "targetAnchor_" + v).checked]

    assert checked() == ["fill"]
    for point in ("TOPLEFT", "CENTER", "BOTTOMRIGHT"):
        m.stub.click(ctl(m, "targetAnchor_" + point))
        assert m.db.targetAnchor == point and checked() == [point]
    m.stub.click(ctl(m, "targetAnchor_fill"))
    assert m.db.targetAnchor == "fill" and checked() == ["fill"]


def test_a_slash_reset_repaints_the_radios(m):
    show(m)
    m.stub.click(ctl(m, "targetAnchor_TOP"))
    m.slash("reset")
    assert ctl(m, "targetAnchor_fill").checked
    assert not ctl(m, "targetAnchor_TOP").checked


def test_the_grid_is_laid_out_like_the_points_it_names(m):
    show(m)
    auto = ctl(m, "targetAnchor_fill")
    cells = {}
    for point in POINTS:
        pt = ctl(m, "targetAnchor_" + point).points[1]
        cells[point] = (pt[4], pt[5])
    xs = sorted({x for x, _ in cells.values()})
    ys = sorted(
        {y for _, y in cells.values()}, reverse=True
    )  # top first (offsets run negative downwards)
    assert len(xs) == 3 and len(ys) == 3
    for i, point in enumerate(POINTS):
        assert cells[point] == (xs[i % 3], ys[i // 3])
    assert xs[0] > auto.points[1][4]  # the grid sits to the right of Auto
    assert xs[1] - xs[0] == xs[2] - xs[1] == 20
    assert ys[0] - ys[1] == ys[1] - ys[2] == 20


def test_each_radio_has_a_tooltip_naming_it(m):
    show(m)
    names = {
        "TOPLEFT": "Top left corner",
        "TOP": "Top edge",
        "TOPRIGHT": "Top right corner",
        "LEFT": "Left edge",
        "CENTER": "Centre",
        "RIGHT": "Right edge",
        "BOTTOMLEFT": "Bottom left corner",
        "BOTTOM": "Bottom edge",
        "BOTTOMRIGHT": "Bottom right corner",
    }
    for point, name in names.items():
        radio = ctl(m, "targetAnchor_" + point)
        m.stub.hover(radio)
        assert str(m.stub.tooltip.text) == name
        m.stub.unhover(radio)
    m.stub.hover(ctl(m, "targetAnchor_fill"))
    assert (
        str(m.stub.tooltip.text)
        == "The XP fill edge on a bar, the centre of a round frame."
    )


def test_the_reset_button_appears_on_a_change_and_restores_auto(m):
    show(m)
    button = m.opt.resets["targetAnchor"]
    assert not button.shown
    m.stub.click(ctl(m, "targetAnchor_LEFT"))
    assert button.shown
    m.stub.click(button)
    assert m.db.targetAnchor == "fill" and not button.shown
    assert ctl(m, "targetAnchor_fill").checked
    assert not ctl(m, "targetAnchor_LEFT").checked


def test_the_row_is_not_dimmed_by_the_glow_or_the_shape(m):
    show(m)
    m.stub.click(ctl(m, "glow"))
    m.stub.click(ctl(m, "glowShape_round"))
    assert m.opt.rows["targetAnchor"].alpha in (None, 1)
    radio = ctl(m, "targetAnchor_TOP")
    assert radio.IsEnabled(radio)
