"""OrbMath: counts, rested split, curves, coordinate maths."""

import math

import pytest


@pytest.fixture
def om(env):
    env.load_addon()
    return env.ns.OrbMath


@pytest.mark.parametrize(
    "gain,xp_max,n",
    [(5.7, 1000, 7), (10, 1000, 8), (50, 1000, 14), (100, 1000, 19), (250, 1000, 28)],
)
def test_count_sqrt_curve(om, gain, xp_max, n):
    assert tuple(om.Count(gain, xp_max, 100, 40)) == (n, 1)


def test_count_tiny_gain_hits_minimum_orbs(om):
    n, scale = om.Count(0.001, 1000, 50, 40)  # raw = (3 + ~0) * 0.5 = 1.5 -> 2; never below 1
    assert n >= 1 and scale == 1
    assert tuple(om.Count(1e-9, 1000, 25, 40))[0] == 1


def test_count_density_is_multiplier(om):
    assert om.Count(100, 1000, 200, 40)[0] == 38  # 2 * 18.8
    assert om.Count(100, 1000, 25, 40)[0] == 5


def test_count_overflow_capped_and_scaled(om):
    n, scale = om.Count(640, 1000, 100, 40)  # 64% -> raw 43
    assert n == 40
    assert scale == pytest.approx(min(1.5, math.sqrt(43 / 40)))


def test_count_scale_clamped_at_1_5(om):
    n, scale = om.Count(1000, 1000, 400, 40)  # raw 32 * 4 = 128 -> sqrt(3.2) > 1.5
    assert n == 40 and scale == 1.5


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


def test_pop_control_stratified_angle_and_radius(om):
    # rand() = 0 -> ang = (i-1)/n * 2pi, R = 45
    x, y, r = om.PopControl(1, 4, 100, 200, lambda: 0)
    assert r == 45
    assert x == pytest.approx(100 + 45 * 2.2) and y == pytest.approx(200 + 0.35 * 45 * 2.2)
    x, y, r = om.PopControl(2, 4, 100, 200, lambda: 0)  # ang = pi/2
    assert x == pytest.approx(100, abs=1e-9) and y == pytest.approx(200 + (0.8 + 0.35) * 45 * 2.2)


def test_pop_control_rand_max(om):
    vals = iter([0.5, 1.0])  # angle jitter then radius
    x, y, r = om.PopControl(1, 2, 0, 0, lambda: next(vals))
    assert r == 100
    ang = (0 + 0.5 * 0.8) / 2 * 2 * math.pi
    assert x == pytest.approx(math.cos(ang) * 220)
    assert y == pytest.approx((0.8 * math.sin(ang) + 0.35) * 220)


def test_home_control(om):
    c2x, c2y = om.HomeControl(500, 300, 100, 50, 400)
    assert c2x == pytest.approx(100 + 400 * 0.15)
    assert c2y == pytest.approx(50 + 120)


def test_pop_ease_monotonic_endpoints(om):
    ys = [om.PopEase(i / 20) for i in range(21)]
    assert ys[0] == 0 and ys[-1] == pytest.approx(1)
    assert all(b > a for a, b in zip(ys, ys[1:]))
    assert om.PopEase(-1) == 0 and om.PopEase(3) == pytest.approx(1)
    assert om.PopEase(0.5) == pytest.approx(0.5 * (1 - 0.125) + 0.5 * 0.5**2.2)


def test_cubic_endpoints_and_midpoint(om):
    assert tuple(om.Cubic(0, 1, 2, 3, 4, 5, 6, 7, 8)) == (1, 2)
    assert tuple(om.Cubic(1, 1, 2, 3, 4, 5, 6, 7, 8)) == (7, 8)
    # t = 0.5: (P0 + 3*P1 + 3*P2 + P3) / 8
    x, y = om.Cubic(0.5, 0, 0, 0, 80, 80, 80, 80, 0)
    assert x == pytest.approx((0 + 0 + 240 + 80) / 8)
    assert y == pytest.approx((0 + 240 + 240 + 0) / 8)


@pytest.mark.parametrize(
    "point,expected",
    [
        ("TOPLEFT", (100, 30)),
        ("TOP", (300, 30)),
        ("TOPRIGHT", (500, 30)),
        ("LEFT", (100, 20)),
        ("CENTER", (300, 20)),
        ("RIGHT", (500, 20)),
        ("BOTTOMLEFT", (100, 10)),
        ("BOTTOM", (300, 10)),
        ("BOTTOMRIGHT", (500, 10)),
    ],
)
def test_anchor_point_names_the_nine_points_of_a_rect(om, point, expected):
    assert tuple(om.AnchorPoint(100, 10, 400, 20, point)) == expected


def test_anchor_point_gives_the_centre_for_anything_else(om):
    for junk in (None, "", "MIDDLE", 5, "fill"):
        assert tuple(om.AnchorPoint(100, 10, 400, 20, junk)) == (300, 20)
