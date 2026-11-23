"""C3: the Vertical glow shape: sanitize, the upright flash (texture and transposed size), aiming at a plain frame's
bottom-to-top fill edge, and a recognised vertical bar getting the vertical glow under Horizontal."""

import pytest
from test_m5 import build
from test_v013 import run_until_flash
from test_v102 import load_db

FLASH = "Interface\\AddOns\\XPOrbs\\media\\flash"
FLASH_V = FLASH + "_v"
ORB = "Interface\\AddOns\\XPOrbs\\media\\orb"
FLASH_W, FLASH_ASPECT = (
    12,
    7,
)  # Orbs.lua: width = size * FLASH_W, height = width / FLASH_ASPECT


@pytest.fixture
def m(env):
    return build(env)


def flash_after_test_burst(m):
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl is not None
    return fl


def texture_of(fl):
    return fl.calls["SetTexture"][1]


def vertical_bar(m, orient="VERTICAL"):
    m.G.MainStatusTrackingBarContainer.shown = False
    return m.stub.makeStatusBar("EQOL_XPBar", 100, 200, 20, 400, 0, 1000, 250, orient)


# ---------------------------------------------------------------- settings


def test_sanitize_accepts_vertical_and_rejects_junk(env):
    assert load_db(env, {"version": 6, "glowShape": "vertical"}).glowShape == "vertical"


def test_sanitize_resets_an_unknown_shape(env):
    assert load_db(env, {"version": 6, "glowShape": "diagonal"}).glowShape == "bar"


def test_the_media_file_exists_and_is_the_flash_transposed():
    from conftest import ROOT

    data = (ROOT / "media" / "flash_v.tga").read_bytes()
    width, height = (
        int.from_bytes(data[12:14], "little"),
        int.from_bytes(data[14:16], "little"),
    )
    assert (width, height) == (32, 128)
    flat = (ROOT / "media" / "flash.tga").read_bytes()
    assert (
        int.from_bytes(flat[12:14], "little"),
        int.from_bytes(flat[14:16], "little"),
    ) == (128, 32)


# ---------------------------------------------------------------- the flash


def test_vertical_shape_uses_the_upright_flash_with_the_transposed_size(m):
    m.db.glowShape = "vertical"
    fl = flash_after_test_burst(m)
    assert texture_of(fl) == FLASH_V
    tall = m.db.size * FLASH_W  # intensity 100: the scale factor is 1
    assert fl.height == pytest.approx(tall) and fl.width == pytest.approx(
        tall / FLASH_ASPECT
    )


def test_the_vertical_flash_scales_with_the_intensity(m):
    m.db.glowShape = "vertical"
    fl = flash_after_test_burst(m)
    base = fl.height
    m.db.glowIntensity = 200  # the size factor is 1.2
    m.stub.tick(0)
    assert fl.height == pytest.approx(base * 1.2) and fl.width == pytest.approx(
        base * 1.2 / FLASH_ASPECT
    )


def test_horizontal_shape_still_uses_the_wide_flash(m):
    fl = flash_after_test_burst(m)
    assert texture_of(fl) == FLASH
    wide = m.db.size * FLASH_W
    assert fl.width == pytest.approx(wide) and fl.height == pytest.approx(
        wide / FLASH_ASPECT
    )


def test_a_vertical_status_bar_under_horizontal_gets_the_vertical_glow(m):
    vertical_bar(m)
    fl = flash_after_test_burst(m)
    assert m.ns.Target.lastVertical is True and m.db.glowShape == "bar"
    assert texture_of(fl) == FLASH_V
    assert fl.height == pytest.approx(m.db.size * FLASH_W) and fl.width < fl.height


def test_a_horizontal_status_bar_under_horizontal_keeps_the_wide_flash(m):
    m.G.MainStatusTrackingBarContainer.shown = False
    m.stub.makeStatusBar("EQOL_XPBar", 100, 200, 400, 20, 0, 1000, 250, "HORIZONTAL")
    fl = flash_after_test_burst(m)
    assert m.ns.Target.lastVertical is False
    assert texture_of(fl) == FLASH and fl.width > fl.height


def test_round_is_unchanged(m):
    m.db.glowShape = "round"
    fl = flash_after_test_burst(m)
    assert texture_of(fl) == ORB and fl.width == fl.height


def test_round_wins_over_a_vertical_status_bar(m):
    vertical_bar(m)
    m.db.glowShape = "round"
    fl = flash_after_test_burst(m)
    assert texture_of(fl) == ORB and fl.width == fl.height


def test_the_flash_follows_a_shape_change_between_bursts(m):
    fl = flash_after_test_burst(m)
    assert texture_of(fl) == FLASH
    m.run(2)
    m.db.glowShape = "vertical"
    fl = flash_after_test_burst(m)
    assert texture_of(fl) == FLASH_V


# ---------------------------------------------------------------- the aim


def tall_frame(m, name="TallBar"):
    m.stub.makeBar(name, 100, 200, 20, 400, True)
    m.G[name].name = name
    m.db.targetFrame = name
    return m.G[name]


def test_a_plain_frame_with_the_vertical_shape_aims_at_the_bottom_to_top_fill_edge(m):
    tall_frame(m)
    m.db.glowShape = "vertical"
    m.stub.xp, m.stub.xpMax = 250, 1000
    T = m.ns.Target
    x, y, ok = T.GetDestination(T, False, False)
    assert ok and T.lastVertical is True
    assert (x, y) == pytest.approx(
        (110, 300)
    )  # centre of the width, a quarter of the way up
    m.stub.xp = 1000
    x, y, _ = T.GetDestination(T, False, False)
    assert (x, y) == pytest.approx((110, 600))


def test_the_same_frame_under_horizontal_fills_left_to_right(m):
    tall_frame(m)
    m.stub.xp, m.stub.xpMax = 250, 1000
    T = m.ns.Target
    x, y, ok = T.GetDestination(T, False, False)
    assert ok and T.lastVertical is False
    assert (x, y) == pytest.approx((105, 400))


def test_an_unreadable_xp_pair_aims_at_the_bottom_edge(m):
    tall_frame(m)
    m.db.glowShape = "vertical"
    m.stub.xp, m.stub.xpMax = 0, 0
    T = m.ns.Target
    x, y, ok = T.GetDestination(T, False, False)
    assert ok and (x, y) == pytest.approx((110, 200))


def test_a_status_bar_keeps_its_own_orientation_under_the_vertical_shape(m):
    m.G.MainStatusTrackingBarContainer.shown = False
    m.stub.makeStatusBar("EQOL_XPBar", 100, 200, 400, 20, 0, 1000, 250, "HORIZONTAL")
    m.db.glowShape = "vertical"
    T = m.ns.Target
    x, y, ok = T.GetDestination(T, False, False)
    assert ok and (x, y) == pytest.approx(
        (200, 210)
    )  # its own left-to-right fill, not bottom-to-top
    assert (
        T.lastVertical is False
    )  # but the shape the player chose still draws the upright flash


def test_the_round_shape_still_aims_at_the_centre(m):
    tall_frame(m)
    m.db.glowShape = "round"
    T = m.ns.Target
    x, y, ok = T.GetDestination(T, True, False)
    assert ok and (x, y) == pytest.approx((110, 400))


def test_a_vertical_frame_orb_flies_to_the_vertical_fill_edge(m):
    tall_frame(m)
    m.db.glowShape = "vertical"
    m.stub.xp, m.stub.xpMax = 500, 1000
    fl = flash_after_test_burst(m)
    assert (fl.points[1][4], fl.points[1][5]) == pytest.approx((110, 400))
