"""Black keeps its hue: the colour picker's wheel stays where it was when the value slider hits 0 (db.colorHS), driven
through the ColorSelect HSV stub of stubs_m5.lua. The colour written to the db stays plain RGB."""

import colorsys

import pytest
from test_m5 import build, ctl

PURPLE_H, PURPLE_S = 0.75, 0.8


@pytest.fixture
def m5(env):
    return build(env)


def rgb(colour):
    return [float(colour[i]) for i in (1, 2, 3)]


def pair(t):
    return [float(t[1]), float(t[2])]


def drag(cp, h, s, v):
    cp.Drag(cp, h, s, v)


def wheel(m5):
    """What the picker's ColorSelect holds: (h, s, v)."""
    sel = m5.G.ColorPickerFrame.Content.ColorPicker
    return tuple(float(x) for x in sel.GetColorHSV(sel))


def open_picker(m5, key="color"):
    m5.stub.click(ctl(m5, key))
    return m5.G.ColorPickerFrame


def test_value_zero_keeps_the_wheel_on_the_hue(m5):
    cp = open_picker(m5)
    drag(cp, PURPLE_H, PURPLE_S, 0.9)
    assert wheel(m5) == pytest.approx((PURPLE_H, PURPLE_S, 0.9))
    drag(
        cp, PURPLE_H, PURPLE_S, 0
    )  # the client's widget drops hue and saturation at black
    assert rgb(m5.db.color) == pytest.approx([0, 0, 0])  # black stays plain black
    assert wheel(m5) == pytest.approx((PURPLE_H, PURPLE_S, 0))
    assert [float(x) for x in cp.GetColorRGB(cp)] == pytest.approx([0, 0, 0])


def test_raising_the_value_again_returns_the_old_hue(m5):
    cp = open_picker(m5)
    drag(cp, PURPLE_H, PURPLE_S, 0.9)
    drag(cp, PURPLE_H, PURPLE_S, 0)
    # the player drags the value slider up: the widget carries on from the hue it holds
    h, s, _ = wheel(m5)
    drag(cp, h, s, 0.5)
    want = colorsys.hsv_to_rgb(PURPLE_H, PURPLE_S, 0.5)
    assert rgb(m5.db.color) == pytest.approx(want)


def test_without_the_fix_the_hue_would_be_lost(m5):
    """The stub models Blizzard's behaviour: a drag to 0 leaves the widget at (0, 0, 0) until we push the hue back."""
    cp = open_picker(m5)
    drag(cp, PURPLE_H, PURPLE_S, 0.9)
    m5.G.XPOrbsDB.colorHS = None  # forget what was remembered
    drag(cp, PURPLE_H, PURPLE_S, 0)
    assert wheel(m5) == pytest.approx((0, 0, 0))


def test_the_hue_is_remembered_in_the_saved_variables_per_key(m5):
    cp = open_picker(m5)
    drag(cp, PURPLE_H, PURPLE_S, 0.6)
    assert pair(m5.db.colorHS.color) == pytest.approx([PURPLE_H, PURPLE_S])
    assert m5.db.colorHS.restedColor is None
    cp = open_picker(m5, "restedColor")
    drag(cp, 0.1, 0.5, 0.7)
    assert pair(m5.db.colorHS.restedColor) == pytest.approx([0.1, 0.5])
    assert pair(m5.db.colorHS.color) == pytest.approx([PURPLE_H, PURPLE_S])
    drag(
        cp, 0.1, 0.5, 0.01
    )  # at or under the threshold nothing is remembered: the old pair stays
    assert pair(m5.db.colorHS.restedColor) == pytest.approx([0.1, 0.5])


def test_reopening_on_black_shows_the_remembered_hue(m5):
    cp = open_picker(m5)
    drag(cp, PURPLE_H, PURPLE_S, 0.9)
    drag(cp, PURPLE_H, PURPLE_S, 0)
    cp = open_picker(m5)  # the stub's setup gives the widget plain RGB black: no hue
    assert rgb(m5.db.color) == pytest.approx([0, 0, 0])
    assert wheel(m5) == pytest.approx((PURPLE_H, PURPLE_S, 0))


def test_opening_on_a_colour_remembers_its_hue(m5):
    m5.db.color = m5.lua.table_from(list(colorsys.hsv_to_rgb(0.3, 0.6, 0.8)))
    cp = open_picker(m5)
    assert pair(m5.db.colorHS.color) == pytest.approx([0.3, 0.6])
    drag(cp, 0.3, 0.6, 0)  # jumping straight to black still keeps it
    assert wheel(m5) == pytest.approx((0.3, 0.6, 0))


def test_reopening_on_black_with_nothing_remembered_is_left_alone(m5):
    m5.db.color = m5.lua.table_from([0, 0, 0])
    m5.db.colorHS = None
    open_picker(m5)
    assert wheel(m5) == pytest.approx((0, 0, 0))
    assert m5.db.colorHS is None


def test_the_echo_of_our_own_hsv_push_does_not_recurse(m5):
    sel = m5.G.ColorPickerFrame.Content.ColorPicker
    sel.echo = (
        True  # SetColorHSV fires OnColorSelect -> swatchFunc, like the real widget
    )
    cp = open_picker(m5)
    drag(cp, PURPLE_H, PURPLE_S, 0.9)
    sets = sel.hsvSets or 0
    drag(cp, PURPLE_H, PURPLE_S, 0)
    assert sel.hsvSets == sets + 1  # exactly one push, its echo ignored
    assert wheel(m5) == pytest.approx((PURPLE_H, PURPLE_S, 0))
    assert rgb(m5.db.color) == pytest.approx([0, 0, 0])


def test_without_an_hsv_api_nothing_changes_and_nothing_errors(m5):
    m5.G.ColorPickerFrame.Content = None  # no ColorSelect to ask
    cp = open_picker(m5)
    cp.r, cp.g, cp.b = 0.9, 0.1, 0.2
    cp.info.swatchFunc()
    assert rgb(m5.db.color) == pytest.approx([0.9, 0.1, 0.2])
    cp.r, cp.g, cp.b = 0, 0, 0
    cp.info.swatchFunc()
    assert rgb(m5.db.color) == pytest.approx([0, 0, 0])
    assert m5.db.colorHS is None


def test_a_colour_select_without_the_hsv_calls_is_ignored(m5):
    m5.G.ColorPickerFrame.Content.ColorPicker = m5.lua.table_from({})
    cp = open_picker(m5)
    cp.r, cp.g, cp.b = 0, 0, 0
    cp.info.swatchFunc()
    assert rgb(m5.db.color) == pytest.approx([0, 0, 0])


def test_a_throwing_hsv_api_is_survived(m5):
    m5.lua.execute(
        "ColorPickerFrame.Content.ColorPicker.GetColorHSV = function() error('boom') end"
    )
    cp = open_picker(m5)
    cp.r, cp.g, cp.b = 0.2, 0.3, 0.4
    cp.info.swatchFunc()
    assert rgb(m5.db.color) == pytest.approx([0.2, 0.3, 0.4])


def test_cancel_restores_the_colour(m5):
    cp = open_picker(m5)
    before = rgb(m5.db.color)
    drag(cp, PURPLE_H, PURPLE_S, 0)
    cp.info.cancelFunc()
    assert rgb(m5.db.color) == pytest.approx(before)


# ---------------------------------------------------------------- saved variables


def test_reset_forgets_the_remembered_hue(m5):
    cp = open_picker(m5)
    drag(cp, PURPLE_H, PURPLE_S, 0.9)
    assert m5.db.colorHS is not None
    m5.slash("reset")
    assert m5.db.colorHS is None


@pytest.mark.parametrize(
    "junk",
    [
        "x",
        5,
        {"color": "x"},
        {"color": [0.5]},
        {"color": [2, 0.5]},
        {"color": [0.5, -0.1]},
        {"color": ["a", "b"]},
        {"color": [float("nan"), 0.5]},
        {"other": [0.5, 0.5]},
    ],
)
def test_sanitize_drops_bad_remembered_hues(env, junk):
    from test_v102 import load_db

    value = env.lua.table_from(junk, recursive=True) if isinstance(junk, dict) else junk
    db = load_db(env, {"colorHS": value})
    assert db.colorHS is None


def test_sanitize_keeps_good_pairs_and_drops_the_rest(env):
    from test_v102 import load_db

    saved = {
        "colorHS": {"color": [0.25, 0.5], "restedColor": [3, 0.5], "other": [0.1, 0.1]}
    }
    db = load_db(env, saved)
    assert pair(db.colorHS.color) == pytest.approx([0.25, 0.5])
    assert db.colorHS.restedColor is None and db.colorHS.other is None
