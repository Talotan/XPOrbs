"""OrbMath: counts, rested split, curves, coordinate maths."""

import math

import pytest


@pytest.fixture
def om(env):
    env.load_addon()
    return env.ns.OrbMath


def test_count_one_percent_gives_one(om):
    assert tuple(om.Count(10, 1000, 100, 40)) == (1, 1)


def test_count_tenth_percent_hits_minimum(om):
    assert tuple(om.Count(1, 1000, 100, 40)) == (1, 1)


def test_count_quarter_bar_gives_25(om):
    assert tuple(om.Count(250, 1000, 100, 40)) == (25, 1)


def test_count_overflow_capped_and_scaled(om):
    n, scale = om.Count(3000, 1000, 100, 40)
    assert n == 40
    assert scale == min(2, math.sqrt(300 / 40)) == 2


def test_count_mild_overflow_scale(om):
    n, scale = om.Count(500, 1000, 100, 40)  # raw 50 -> sqrt(1.25)
    assert n == 40 and scale == pytest.approx(math.sqrt(50 / 40))


@pytest.mark.parametrize(
    "args",
    [
        (100, 0, 100, 40),
        (0, 1000, 100, 40),
        (-5, 1000, 100, 40),
        ("x", 1000, 100, 40),
        (10, None, 100, 40),
    ],
)
def test_count_degenerate(om, args):
    assert tuple(om.Count(*args)) == (0, 1)


def test_rested_split_half(om):
    assert tuple(om.RestedSplit(10, 100, 50)) == (5, 5)


def test_rested_split_nil(om):
    assert tuple(om.RestedSplit(10, 100, None)) == (10, 0)


def test_rested_split_clamped(om):
    assert tuple(om.RestedSplit(10, 100, 500)) == (0, 10)
    assert tuple(om.RestedSplit(10, 0, 50)) == (10, 0)


def test_bezier_endpoints(om):
    assert tuple(om.Bezier(0, 1, 2, 5, 9, 10, 4)) == (1, 2)
    assert tuple(om.Bezier(1, 1, 2, 5, 9, 10, 4)) == (10, 4)


def test_bezier_midpoint(om):
    # 0.25*P0 + 0.5*C + 0.25*P1
    x, y = om.Bezier(0.5, 0, 0, 10, 20, 20, 0)
    assert (x, y) == (10, 10)


def test_ease_in_out_monotonic_and_clamped(om):
    ys = [om.EaseInOut(i / 10) for i in range(11)]
    assert ys[0] == 0 and ys[-1] == 1
    assert all(b >= a for a, b in zip(ys, ys[1:]))
    assert om.EaseInOut(-1) == 0 and om.EaseInOut(2) == 1
    assert om.EaseInOut(0.5) == pytest.approx(0.5)


def test_control_point_lift_and_perpendicular(om):
    # rand() = 0.5 -> no perpendicular offset; straight right, so lift is 0.25 * dist upward
    assert tuple(om.ControlPoint(0, 0, 100, 0, lambda: 0.5)) == (50, 25)
    # rand() = 1.0 -> offset +0.3 * dist along (-dy, dx)/dist = (0, 1)
    x, y = om.ControlPoint(0, 0, 100, 0, lambda: 1.0)
    assert x == pytest.approx(50) and y == pytest.approx(25 + 30)


def test_control_point_zero_distance(om):
    assert tuple(om.ControlPoint(5, 5, 5, 5, lambda: 0.9)) == (5, 5)


def test_to_uiparent(om):
    assert tuple(om.ToUIParent(100, 50, 0.8, 0.4)) == (200, 100)


def test_fill_edge(om):
    assert tuple(om.FillEdge(100, 10, 400, 20, 250, 1000)) == (200, 20)
    assert tuple(om.FillEdge(100, 10, 400, 20, 5000, 1000)) == (500, 20)
    assert tuple(om.FillEdge(100, 10, 400, 20, 50, 0)) == (100, 20)


def test_xpdelta_normal(om):
    assert om.XPDelta(100, 1000, 250, 1000, False) == 150


def test_xpdelta_level_up_wrap(om):
    assert om.XPDelta(900, 1000, 50, 1200, True) == 150
    assert om.XPDelta(900, 1000, 50, 1200, False) == 150  # inferred from newXP < oldXP


def test_xpdelta_no_change_and_never_negative(om):
    assert om.XPDelta(100, 1000, 100, 1000, False) == 0
    assert om.XPDelta(500, 400, 10, 400, True) == 0  # oldXP > oldMax would go negative
