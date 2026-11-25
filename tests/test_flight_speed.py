"""Flight speed mode (db.flightMode "speed", the default): the duration follows the length of the flight, the trail
follows the speed, the saved-flight-time migration, the /xporbs flightmode switch, the Flight tab's Speed type dropdown and slider."""

import re

import pytest
from test_m5 import build
from test_migration import load
from test_p2_unknown import fire, live_recs
from test_v013 import no_template
from test_v09 import make

REF = 1000.0  # OrbShapes.k.refSpeed
LAG = 0.015  # OrbShapes.k.ghostLag
NEAR = (700, 300)
FAR = (150, 1000)
CORNER = (1450, 1050)  # the longest way on the test screen: 1000 px/s at 50 % only clamps past ~1250 px


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
    assert k.refSpeed == REF and k.ghostLag == LAG


def test_100_percent_is_1000_px_per_second(g):
    assert g.ns.OrbShapes.k.refSpeed == 1000  # was 500: the new 100 % is what 200 % used to be
    o = stream(g, CORNER)[0]
    assert arc(g, o) > 1000  # no clamp involved: duration = arc / 1000 exactly, ~1 s per 1000 px
    assert o.dur == pytest.approx(arc(g, o) / 1000)
    land(g)
    o = stream(g, NEAR)[0]
    assert o.dur == pytest.approx(arc(g, o) / 1000)


def test_duration_follows_the_arc_length(g):
    near = stream(g, NEAR)[0]
    near_dur, near_arc = near.dur, arc(g, near)
    land(g)
    far = stream(g, FAR)[0]
    assert near_dur == pytest.approx(min(2.5, max(0.35, near_arc / REF)))
    assert far.dur == pytest.approx(min(2.5, max(0.35, arc(g, far) / REF)))
    assert arc(g, far) > near_arc and far.dur > near_dur


def test_speed_200_halves_the_duration(g):
    d100 = stream(g, (400, 650))[0].dur
    land(g)
    g.db.flightSpeed = 200
    d200 = stream(g, (400, 650))[0].dur
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
    assert arc(g, far) / (REF * 0.5) > 2.5  # the clamp is what limits it
    assert far.dur == pytest.approx(2.5)


def test_time_mode_duration_ignores_the_distance(g):
    g.db.flightMode = "time"
    g.db.flightTime = 1.0
    d_near = stream(g, NEAR)[0].dur
    land(g)
    d_far = stream(g, FAR)[0].dur
    assert d_near == pytest.approx(1.0) and d_far == pytest.approx(1.0)


# ---------------------------------------------------------------- trail


def test_starlight_ghost_lag_is_seconds_in_speed_mode(g):
    o = stream(g, FAR)[0]
    assert o.ghostStep == pytest.approx(LAG / o.dur)
    land(g)
    g.db.flightMode = "time"
    g.db.flightTime = 1.0
    assert stream(g, FAR)[0].ghostStep is None  # drawOrb falls back to GHOST_STEP
    assert g.ns.OrbShapes.k.ghostStep == 0.015


@pytest.mark.parametrize("shape", ["retro", "globe"])
def test_trail_gap_in_px_is_the_same_at_any_distance_and_scales_with_speed(g, shape):
    g.db.orbShape = shape
    g.db.size = 2 if shape == "retro" else 14
    gaps = {}
    for speed in (100, 200):
        g.db.flightSpeed = speed
        for name, origin in (("near", (300, 700)), ("far", CORNER)):
            o = stream(g, origin)[0]
            # a trail point `gap` px behind sits gap * pxToProgress of the flight back; times the arc = px along it
            gaps[speed, name] = o.pxToProgress * arc(g, o)
            assert o.dur * REF * speed / 100 == pytest.approx(
                arc(g, o)
            )  # nothing was clamped
            land(g)
    assert gaps[100, "near"] == pytest.approx(1.0) and gaps[
        100, "far"
    ] == pytest.approx(1.0)
    assert gaps[200, "near"] == pytest.approx(2.0) and gaps[
        200, "far"
    ] == pytest.approx(2.0)


def test_time_mode_trail_keeps_the_share_of_the_way(g):
    g.db.flightMode = "time"
    g.db.orbShape = "globe"
    o = stream(g, FAR)[0]
    assert o.pxToProgress is None and o.ghostStep is None


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
    assert m.opt.killStyleLabelY == 112 and row_y(m, "style_popstream") == 134


def test_kill_style_group_is_indented_under_its_header(env):
    m = build(env)
    for key in ("style_popstream", "style_crossfade", "style_stream"):
        assert ctl(m, key).points[1][4] == 32 + 16 - 2, key  # radio box sits 2 px left of its x
    for pm in ("nameplate", "direct"):
        assert ctl(m, "popMode_" + pm).points[1][4] == 32 + 16 + 24 - 2
        assert m.opt.descs[pm].points[1][4] == 32 + 16 + 48
    assert m.opt.descs["crossfade"].points[1][4] == 32 + 16 + 24
    assert ctl(m, "zoomSpread").points[1][4] != 48  # the spread checkbox is back on the label column
    assert m.opt.descs["zoomSpread"].points[1][4] == 32


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
