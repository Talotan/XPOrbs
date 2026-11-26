"""Flight speed mode (db.flightMode "speed", the default): the duration follows the length of the flight, the trail
follows the speed, the saved-flight-time migration, the /xporbs flightmode switch, the Flight tab's Speed type dropdown and slider."""

import math
import re
from itertools import pairwise

import pytest
from test_m5 import build
from test_migration import load
from test_p2_unknown import fire, live_recs
from test_v013 import no_template
from test_v09 import make

REF = 1300.0  # OrbShapes.k.refSpeed
GAP_K = 0.3  # OrbShapes.k.ghostGapK: ghost spacing in drawn diameters
NEAR = (700, 300)
FAR = (150, 1000)
CORNER = (1450, 1050)  # the longest way on the test screen: 1300 px/s at 50 % only clamps past ~1625 px


def stream(g, origin, n=1, **kw):
    """A plain stream from `origin` (random pinned at 0.5, so jitter is exactly 1.0)."""
    fire(g, "stream", n=n, x=origin[0], y=origin[1], ex=origin[0], ey=origin[1], **kw)
    return live_recs(g)


def land(g):
    g.stub.tick(5)  # let the burst finish and free its records


def arc(g, o):
    dx, dy = tuple(g.ns.Target.GetDestination(g.ns.Target, False, False))[:2]
    return g.ns.OrbMath.ArcLength(
        o.x0,
        o.y0,
        o.control1X,
        o.control1Y,
        dx,
        dy,
        o.flightDist,
        o.bowX,
        o.bowY,
        o.screenW,
        o.screenH,
        o.clampMargin,
    )


@pytest.fixture
def g(env):
    g = make(env)
    g.db.flightMode = "speed"
    g.db.flightSpeed = 100
    return g


# ---------------------------------------------------------------- duration


def test_constants_are_exposed(g):
    k = g.ns.OrbShapes.k
    assert k.refSpeed == REF and k.ghostGapK == GAP_K and k.ghostLag is None


def test_100_percent_is_1300_px_per_second(g):
    assert g.ns.OrbShapes.k.refSpeed == 1300  # the new 100 % is what 130 % used to be
    o = stream(g, CORNER)[0]
    assert arc(g, o) > 1000  # no clamp involved: duration = arc / 1300 exactly, ~1 s per 1300 px
    assert o.dur == pytest.approx(arc(g, o) / 1300)
    land(g)
    o = stream(g, NEAR)[0]
    assert o.dur == pytest.approx(arc(g, o) / 1300)


def test_duration_follows_the_arc_length(g):
    near = stream(g, NEAR)[0]
    near_dur, near_arc = near.dur, arc(g, near)
    land(g)
    far = stream(g, FAR)[0]
    assert near_dur == pytest.approx(min(2.5, max(0.35, near_arc / REF)))
    assert far.dur == pytest.approx(min(2.5, max(0.35, arc(g, far) / REF)))
    assert arc(g, far) > near_arc and far.dur > near_dur


def test_speed_200_halves_the_duration(g):
    d100 = stream(g, CORNER)[0].dur
    land(g)
    g.db.flightSpeed = 200
    d200 = stream(g, CORNER)[0].dur
    assert 0.35 < d200 and d100 < 2.5
    assert d200 == pytest.approx(d100 / 2)


def test_duration_is_clamped(g):
    g.db.flightSpeed = 250
    assert stream(g, (400, 60))[0].dur == pytest.approx(
        0.35
    )  # a very short way at the top speed
    land(g)
    g.db.flightSpeed = 50
    far = stream(g, CORNER)[0]
    # at 100 % = 1300 px/s the slowest setting (50 %) no longer reaches the 2.5 s cap on this screen
    assert far.dur == pytest.approx(min(2.5, arc(g, far) / (REF * 0.5)))


def test_time_mode_duration_ignores_the_distance(g):
    g.db.flightMode = "time"
    g.db.flightTime = 1.0
    d_near = stream(g, NEAR)[0].dur
    land(g)
    d_far = stream(g, FAR)[0].dur
    assert d_near == pytest.approx(1.0) and d_far == pytest.approx(1.0)


# ---------------------------------------------------------------- trail


def test_trail_progress_per_px_is_one_over_the_path_length_in_both_modes(g):
    o = stream(g, FAR)[0]
    assert o.pxToProgress == pytest.approx(1 / arc(g, o)) and o.ghostStep is None
    land(g)
    g.db.flightMode = "time"
    g.db.flightTime = 1.0
    o = stream(g, FAR)[0]
    assert o.pxToProgress == pytest.approx(1 / arc(g, o))


def at_half(g, shape, speed, mode="speed"):
    """One orb of `shape` flying FAR at `speed` %, ticked to half way; (orb record, body texture, ghost textures)."""
    g.db.orbShape = shape
    g.db.size = 2 if shape == "retro" else 14
    g.db.trail = True
    g.db.flightMode, g.db.flightSpeed = mode, speed
    (o,) = stream(g, FAR)
    while (o.elapsed - o.delay) / o.dur < 0.5:
        g.stub.tick(0.004)
    ghosts = [t for t in (o.ghost1, o.ghost2, o.ghost3, o.ghost4) if t is not None]
    assert ghosts and all(t.shown for t in ghosts)
    return o, o.body, ghosts


def xy(t):
    return t.points[1][4], t.points[1][5]


def chain_gaps(body, ghosts):
    pts = [xy(body)] + [xy(t) for t in ghosts]
    return [math.dist(a, b) for a, b in pairwise(pts)]


@pytest.mark.parametrize("shape", ["starlight", "crackle", "bubble"])
@pytest.mark.parametrize("mode", ["speed", "time"])
def test_ghost_spacing_in_px_does_not_grow_with_flight_speed(g, shape, mode):
    if mode == "time":
        g.db.flightTime = 1.0
    slow = at_half(g, shape, 50, mode)
    slow_gaps, slow_d = chain_gaps(slow[1], slow[2]), slow[1].width
    land(g)
    fast = at_half(g, shape, 250, mode)
    fast_gaps, fast_d = chain_gaps(fast[1], fast[2]), fast[1].width
    assert slow_d == pytest.approx(fast_d, rel=0.1)
    assert fast_gaps == pytest.approx(slow_gaps, rel=0.2, abs=1.5)  # 2.5x faster, the same px


@pytest.mark.parametrize("shape", ["starlight", "crackle", "bubble"])
@pytest.mark.parametrize("speed", [50, 100, 250])
def test_consecutive_ghosts_overlap_at_any_speed(g, shape, speed):
    _, body, ghosts = at_half(g, shape, speed)
    gap = GAP_K * body.width
    for dist, tex in zip(chain_gaps(body, ghosts), ghosts):
        assert 0.5 * gap < dist <= gap * 1.2 + 1.5  # about ghostGapK diameters (the ease changes the pace a little)
        assert dist < tex.width * 0.6  # so each ghost covers the last one: a smear, not echoes


@pytest.mark.parametrize("shape", ["starlight", "crackle"])
def test_third_ghost_sits_three_gaps_behind_and_overlaps_the_second(g, shape):
    o, body, ghosts = at_half(g, shape, 100)
    assert len(ghosts) == 3
    gap = GAP_K * body.width
    to_third = math.dist(xy(body), xy(o.ghost3))
    assert 0.5 * 3 * gap < to_third <= 3 * gap * 1.2 + 2  # ~3 gaps along the path (the path bends a little)
    g1, g2, g3 = ghosts
    k = g.ns.OrbShapes.k  # sizes and alphas are relative to the ghost art's own scale, so compare with ghost 1
    assert g3.width / g1.width == pytest.approx(k.ghost3Size / k.ghost1Size)
    assert g3.alpha / g1.alpha == pytest.approx(k.ghost3Alpha / k.ghost1Alpha, rel=0.05)
    assert math.dist(xy(g2), xy(g3)) < (g2.width + g3.width) / 2  # the circles overlap: no bead gap


def test_ghost3_is_released_with_the_burst_and_trail_off_draws_none(g):
    at_half(g, "starlight", 100)
    third = [f for f in g.stub.frames.values() if f.kind == "Texture" and f.shown]
    assert third
    land(g)
    assert g.orbs.Info(g.orbs)[1] == 0 and g.stub.shownTextures() == 0
    g.db.trailOpacity = 0
    (o,) = stream(g, FAR)
    assert o.ghost1 is None and o.ghost3 is None


@pytest.mark.parametrize("speed", [50, 100, 250])
def test_retro_trail_squares_stay_on_the_grid_and_in_reach_of_the_body(g, speed):
    o, body, ghosts = at_half(g, "retro", speed)
    cell = o.cell
    assert len(ghosts) == 2
    for t in ghosts:
        x, y = xy(t)
        assert (x / cell) % 1 in (0, 0.5) and (y / cell) % 1 in (0, 0.5)  # snapped to cells (or half cells if odd)
    big, small = chain_gaps(body, ghosts)
    assert big <= 5 * cell * 1.5 + cell and small <= 3 * cell + cell  # touching the body, then the big square


def test_retro_trail_does_not_lengthen_with_speed(g):
    o, body, ghosts = at_half(g, "retro", 50)
    slow = math.dist(xy(body), xy(ghosts[1]))
    land(g)
    o, body, ghosts = at_half(g, "retro", 250)
    assert math.dist(xy(body), xy(ghosts[1])) == pytest.approx(slow, abs=3 * o.cell)


# ---------------------------------------------------------------- migration and sanitising


@pytest.mark.parametrize(
    "flight_time, speed", [(1.0, 100), (0.7, 140), (1.5, 70), (0.4, 250), (1.2, 80)]
)
def test_saved_flight_time_becomes_a_speed(env, flight_time, speed):
    db = load(env, {"version": 6, "flightTime": flight_time})
    assert (
        db.flightSpeed == speed
        and db.flightMode == "speed"
        and db.flightTime == flight_time
    )


def test_an_existing_speed_is_kept(env):
    assert (
        load(env, {"version": 6, "flightTime": 0.7, "flightSpeed": 60}).flightSpeed
        == 60
    )


def test_fresh_save_gets_speed_100_in_speed_mode(env):
    db = load(env)
    assert db.flightSpeed == 100 and db.flightMode == "speed" and db.flightTime == 1.0


@pytest.mark.parametrize("bad", ["fast", 3, True])
def test_bad_flight_mode_becomes_speed(env, bad):
    assert load(env, {"version": 6, "flightMode": bad}).flightMode == "speed"


def test_time_mode_is_kept_and_speed_is_clamped(env):
    db = load(env, {"version": 6, "flightMode": "time", "flightSpeed": 9000})
    assert db.flightMode == "time" and db.flightSpeed == 250


# ---------------------------------------------------------------- the debug command


def test_flightmode_command(env):
    m = build(env)
    m.db.flightMode = "speed"
    m.slash("flightmode time")
    assert m.db.flightMode == "time" and m.say()[-1].endswith("flight mode: time")
    m.slash("flightmode speed")
    assert m.db.flightMode == "speed"
    n = len(m.say())
    m.slash("flightmode warp")
    assert m.db.flightMode == "speed" and "use time or speed" in m.say()[n]
    m.slash("flightmode")
    assert m.db.flightMode == "speed" and m.say()[-1].endswith("flight mode: speed")


def test_flightmode_is_not_in_help(env):
    m = build(env)
    m.slash("help")
    assert not any("flightmode" in line for line in m.say())


# ---------------------------------------------------------------- the Flight tab


def row_y(m, key):
    return -m.opt.rows[key].points[1][5]


def test_flight_tab_shows_the_slider_of_the_mode(env):
    m = build(env)
    assert row_y(m, "flightSpeed") == row_y(m, "flightTime")
    m.slash("flightmode speed")
    assert m.opt.rows.flightSpeed.shown and not m.opt.rows.flightTime.shown
    m.slash("flightmode time")
    assert m.opt.rows.flightTime.shown and not m.opt.rows.flightSpeed.shown
    m.slash("flightmode speed")
    assert m.opt.rows.flightSpeed.shown and not m.opt.rows.flightTime.shown
    assert (
        m.opt.controls.flightSpeed is not None and m.opt.controls.flightTime is not None
    )


def test_tab_is_named_flight_and_look_has_no_flight_rows(env):
    m = build(env)
    assert [str(t.xpName) for t in m.opt.tabs.values()] == ["General", "Sound", "Look", "Flight", "Arrival"]
    for key in ("flightPath", "flightMode", "flightSpeed", "flightTime"):
        assert m.lua.eval("rawequal")(m.opt.rows[key].createdParent, m.opt.tabChildren.Flight), key
    # pathing, speed type, the slider row, then the kill style group (header y = Options.killStyleLabelY)
    assert [row_y(m, k) for k in ("flightPath", "flightMode", "flightSpeed")] == [8, 42, 76]
    assert m.opt.killStyleLabelY == 112 and row_y(m, "style_popstream") == 144


def test_kill_style_group_is_indented_under_its_header(env):
    m = build(env)
    for key in ("style_popstream", "style_crossfade", "style_stream"):
        assert ctl(m, key).points[1][4] == 32 + 16 - 2, key  # radio box sits 2 px left of its x
    # descriptions hang off the box, so their x is box-relative (the box starts on the label column, x 32)
    for pm in ("nameplate", "direct"):
        assert ctl(m, "popMode_" + pm).points[1][4] == 32 + 16 + 24 - 2
        assert m.opt.descs[pm].points[1][4] == 16 + 48
    assert m.opt.descs["crossfade"].points[1][4] == 16 + 24
    assert m.opt.descs["zoomSpread"].points[1][4] == 16  # inside the box like the radios, not on the border


def test_kill_style_box_encloses_its_rows(env):
    m = build(env)
    box = m.opt.killBox
    pt = box.points[1]
    assert (pt[1], pt[4], pt[5]) == ("TOPLEFT", 32, -(m.opt.killStyleLabelY + 22))  # right under the header
    assert (box.width, box.height) == (m.opt.shapeBox.width, 10 + 278 + 8)
    top, bottom = -pt[5], -pt[5] + box.height
    keys = ["style_popstream", "popMode_nameplate", "popMode_direct", "style_crossfade", "style_stream", "zoomSpread"]
    for key in keys:
        assert m.lua.eval("rawequal")(m.opt.rows[key].createdParent, box), key
        y = row_y(m, key)
        assert top + 8 <= y and y + m.opt.rows[key].height <= bottom - 8, key
    # the last description (one 14 px line) also fits, with the bottom pad under it
    assert row_y(m, "zoomSpread") + 28 + 14 + 8 <= bottom
    assert top + 8 <= row_y(m, "style_popstream")
    # nothing sits below it: the tab ends 16 px under the box
    assert m.opt.tabHeights.Flight == bottom + 16
    for key in ("flightPath", "flightMode", "flightSpeed"):
        assert row_y(m, key) + 32 <= top


def ctl(m, key):
    return m.opt.controls[key]


def test_speed_type_dropdown_sets_the_mode_and_swaps_the_slider(env):
    m = build(env)
    m.slash("flightmode speed")  # the shared build() harness starts in "time" mode
    dd = m.opt.speedTypeDropdown
    assert dd.template == "WowStyle1DropdownTemplate" and dd.points[1][4] == 260
    assert m.db.flightMode == "speed" and m.opt.rows.flightSpeed.shown and not m.opt.rows.flightTime.shown
    assert m.stub.pickMenu(dd, "Relative speed") is True
    assert m.db.flightMode == "time"
    assert m.opt.rows.flightTime.shown and not m.opt.rows.flightSpeed.shown
    assert m.stub.pickMenu(dd, "Constant speed (default)") is True
    assert m.db.flightMode == "speed"
    assert m.opt.rows.flightSpeed.shown and not m.opt.rows.flightTime.shown


def test_speed_type_reset_restores_constant_speed(env):
    m = build(env)
    m.slash("flightmode speed")
    m.stub.pickMenu(m.opt.speedTypeDropdown, "Relative speed")
    btn = m.opt.resets["flightMode"]
    assert btn.shown
    m.stub.click(btn)
    assert m.db.flightMode == "speed" and not btn.shown
    assert m.opt.rows.flightSpeed.shown and not m.opt.rows.flightTime.shown


def test_speed_type_radio_fallback(env):
    m = build(env, pre=no_template("WowStyle1DropdownTemplate"))
    assert m.opt.speedTypeDropdown is None
    m.slash("flightmode speed")
    m.stub.click(m.opt.controls["flightMode_time"])
    assert m.db.flightMode == "time" and m.opt.controls["flightMode_time"].checked
    assert m.opt.rows.flightTime.shown and not m.opt.rows.flightSpeed.shown
    m.stub.click(m.opt.controls["flightMode_speed"])
    assert m.db.flightMode == "speed" and m.opt.rows.flightSpeed.shown and not m.opt.rows.flightTime.shown


def test_speed_slider_writes_the_speed(env):
    m = build(env)
    m.slash("flightmode speed")
    m.stub.slide(m.opt.controls.flightSpeed, 140)
    assert m.db.flightSpeed == 140


# ---------------------------------------------------------------- the log line


def test_flight_log_line_once_per_burst(g):
    g.db.debug = True
    stream(g, FAR, n=5)
    lines = [x for x in g.log() if "FLIGHT" in x]
    assert len(lines) == 1
    assert re.search(r" FLIGHT mode=speed dist=\d+ dur=\d\.\d\d$", lines[0])
    land(g)
    g.db.flightMode = "time"
    stream(g, FAR, n=3)
    lines = [x for x in g.log() if "FLIGHT" in x]
    assert len(lines) == 2 and "mode=time" in lines[1] and lines[1].endswith("dur=1.00")


def test_no_flight_log_line_without_debug(g):
    g.db.debug = False
    stream(g, FAR, n=2)
    assert not [x for x in g.log() if "FLIGHT" in x]
