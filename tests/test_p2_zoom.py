"""Zoom-aware mob anchor: OrbMath.ZoomOffset / FitZoom, the once-per-burst anchor, the estimate lift, the commands and
the calibration panel (opt-in; everything off by default must behave exactly as before)."""

import pytest
from conftest import lua_list
from test_m6 import make as make_m6
from test_m6 import updaters
from test_v09 import OWN, burst, pop_frames, restricted_plate
from test_v010 import hover, mo_estimate


def make(env):
    """test_m6's harness (it loads the options-panel stubs the calibration panel needs) with the old Game surface."""
    env.lua.execute("math.random = function() return 0.5 end")
    g = make_m6(env)
    g.env = g
    g.G = env.G
    return g


def chat_tail(g, n=1):
    return [
        str(g.stub.chat[i])
        for i in range(len(g.stub.chat) - n + 1, len(g.stub.chat) + 1)
    ]


def pts(g):
    return [(p["z"], p["off"]) for p in lua_list(g.db.zoomPoints)]


def set_points(g, pairs):
    g.db.zoomPoints = g.env.lua.table_from(
        [g.env.lua.table_from({"z": z, "off": o}) for z, o in pairs]
    )


# ---------------------------------------------------------------- pure maths


def test_zoom_offset(env):
    env.load_addon()
    zo = env.ns.OrbMath.ZoomOffset
    assert zo(10, 10, 500, 2) == pytest.approx(60)
    assert zo(1, 10, 500, 2) == pytest.approx(260)  # floored at zMin
    assert zo(0, 10, 500, 2) == pytest.approx(260)
    assert zo(None, 10, 500, 2) is None
    assert zo("x", 10, 500, 2) is None
    assert zo(float("nan"), 10, 500, 2) is None
    assert zo(10, None, 500, 2) is None


def test_fit_exact_two_and_three_points(env):
    env.load_addon()
    om = env.ns.OrbMath
    t = env.lua.table_from

    def points(pairs):
        return t([t({"z": z, "off": 20 + 300 / max(z, 2)}) for z in pairs])

    a, b = om.FitZoom(points([5, 20]), 2)
    assert (a, b) == (pytest.approx(20), pytest.approx(300))
    a, b = om.FitZoom(points([3, 8, 40]), 2)
    assert (a, b) == (pytest.approx(20), pytest.approx(300))


def test_fit_degenerate_and_invalid(env):
    env.load_addon()
    om = env.ns.OrbMath
    t = env.lua.table_from
    one = t([t({"z": 5, "off": 50})])
    same = t([t({"z": 5, "off": 50}), t({"z": 5, "off": 60})])
    assert om.FitZoom(one, 2) is None
    assert om.FitZoom(t([]), 2) is None
    assert om.FitZoom(same, 2) is None
    assert om.FitZoom(None, 2) is None
    # two zooms below zMin share one x, so they are degenerate too
    low = t([t({"z": 1, "off": 50}), t({"z": 1.5, "off": 60})])
    assert om.FitZoom(low, 2) is None
    junk = t(
        [t({"z": 5, "off": 50}), t({"z": -1, "off": 60}), t({"z": "x", "off": 1}), 7]
    )
    assert om.FitZoom(junk, 2) is None


def test_fit_negative_slope_clamps_to_mean(env):
    env.load_addon()
    t = env.lua.table_from
    p = t(
        [t({"z": 5, "off": 40}), t({"z": 20, "off": 80})]
    )  # farther out, bigger offset: b < 0
    a, b = env.ns.OrbMath.FitZoom(p, 2)
    assert (a, b) == (pytest.approx(60), 0)


# ---------------------------------------------------------------- defaults and sanitising


def test_defaults_are_the_fitted_curve_and_on(env):
    g = make(env)
    d = g.ns.defaults  # (make() pins the old numbers on the live db)
    assert (d.zoomAnchor, d.zoomA, d.zoomB, d.zoomMin) == (True, 5, 175, 5)
    assert pts(g) == []
    assert "zoomA" not in g.ns.ranges and "zoomAnchor" not in g.ns.ranges


def test_initdb_sanitises_junk(env):
    g = make(env)
    t = env.lua.table_from
    g.db.zoomAnchor = "yes"
    g.db.zoomA = "x"
    g.db.zoomB = 99999
    g.db.zoomMin = -5
    g.db.zoomPoints = t(
        [
            t({"z": 5, "off": 50}),
            t({"z": -1, "off": 1}),
            t({"z": "a", "off": 1}),
            3,
            t({"z": 4}),
        ]
        + [t({"z": 6 + i, "off": 60 + i}) for i in range(10)]
    )
    g.ns.InitDB(g.ns)
    d = g.db
    assert d.zoomAnchor is True and d.zoomA == 5 and d.zoomB == 3000 and d.zoomMin == 0.5
    got = pts(g)
    assert len(got) == 8 and got[-1] == (15, 69)  # oldest dropped, junk gone
    g.db.zoomPoints = "junk"
    g.db.zoomA = 1000
    g.ns.InitDB(g.ns)
    assert pts(g) == [] and g.db.zoomA == 300


def test_old_untouched_defaults_migrate_to_the_fitted_curve(env):
    g = make(env)
    g.db.zoomAnchor = False  # the old default; the switch itself is left alone
    g.db.zoomA, g.db.zoomB, g.db.zoomMin = 10, 500, 2
    set_points(g, [(5, 50)])
    g.ns.InitDB(g.ns)
    d = g.db
    assert (d.zoomA, d.zoomB, d.zoomMin) == (5, 175, 5)
    assert d.zoomAnchor is False and pts(g) == [(5, 50)]
    for a, b, zmin in [(10, 500, 3), (11, 500, 2), (10, 400, 2)]:  # any custom value is kept
        d.zoomA, d.zoomB, d.zoomMin = a, b, zmin
        g.ns.InitDB(g.ns)
        assert (d.zoomA, d.zoomB, d.zoomMin) == (a, b, zmin)


def test_reset_restores_defaults_with_a_fresh_points_table(env):
    g = make(env)
    g.slash("zoomanchor on")
    g.db.zoomA = 55
    set_points(g, [(5, 50), (10, 40)])
    g.slash("reset")
    d = g.db
    assert (d.zoomAnchor, d.zoomA, d.zoomB, d.zoomMin) == (True, 5, 175, 5)
    assert pts(g) == []
    assert not OWN(g, d.zoomPoints, g.ns.defaults.zoomPoints)


# ---------------------------------------------------------------- anchors


def anchor_of(f):
    assert len(f.points) == 1
    pt = f.points[1]
    return pt[1], pt[3], pt[4], pt[5]


def test_off_by_default_keeps_todays_anchors(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    burst(g, plate=plate, n=5, x=300, y=300, kind="kill")
    (G,) = pop_frames(g)
    assert anchor_of(G) == ("CENTER", "CENTER", 0, -20)
    g.stub.tick(8)
    burst(g, plate=plate, n=3, x=300, y=300, kind="kill", style="crossfade")
    xf = [f for f in pop_frames(g) if f.shown]
    assert anchor_of(xf[0]) == ("CENTER", "BOTTOM", 0, 0)
    assert g.stub.restrictedHits == 0


def test_estimate_unchanged_when_off(env):
    g = make(env)
    hover(g, cursor=(700, 500))
    assert mo_estimate(g, "G1")[:2] == (pytest.approx(700), pytest.approx(540))


@pytest.mark.parametrize("zoom", [15, 1, 40])
def test_on_anchors_both_frames_below_the_plate(env, zoom):
    g = make(env)
    g.slash("zoomanchor on")
    g.stub.zoom = zoom
    want = -(10 + 500 / max(zoom, 2))
    plate = restricted_plate(g, cx=700, cy=400)
    burst(g, plate=plate, n=5, x=300, y=300, kind="kill")
    (G,) = pop_frames(g)
    assert anchor_of(G) == ("CENTER", "BOTTOM", 0, pytest.approx(want))
    g.stub.tick(8)
    burst(g, plate=plate, n=3, x=300, y=300, kind="kill", style="crossfade")
    xf = [f for f in pop_frames(g) if f.shown]
    assert anchor_of(xf[0]) == ("CENTER", "BOTTOM", 0, pytest.approx(want))
    assert g.ns.Orbs.lastZoom == zoom and g.ns.Orbs.lastOffset == pytest.approx(-want)
    assert g.stub.restrictedHits == 0


def test_anchor_is_decided_once_per_burst(env):
    g = make(env)
    g.slash("zoomanchor on")
    g.stub.zoom = 15
    plate = restricted_plate(g)
    burst(g, plate=plate, n=5, x=300, y=300, kind="kill")
    (G,) = pop_frames(g)
    g.stub.zoom = 5
    g.stub.tick(0.2)
    assert anchor_of(G)[3] == pytest.approx(-(10 + 500 / 15))


def test_on_uses_body_offset_in_the_estimate(env):
    g = make(env)
    g.slash("zoomanchor on")
    hover(g, cursor=(700, 500))
    assert g.ns.MobEstimate.BODY_OFFSET == 0
    assert mo_estimate(g, "G1")[:2] == (pytest.approx(700), pytest.approx(500))
    # an explicit head offset on the estimator itself
    est = g.ns.Mouseover.est
    est.AddSample(est, "Z", 100, 100)
    x, y, _, _ = est.Estimate(est, "Z", None, None, 1920, 1080, 12)
    assert (x, y) == (pytest.approx(100), pytest.approx(112))


@pytest.mark.parametrize("how", ["secret", "absent", "raises", "string"])
def test_unreadable_zoom_falls_back(env, how):
    g = make(env)
    g.slash("zoomanchor on")
    if how == "secret":
        g.stub.zoom = g.stub.SECRET
    elif how == "absent":
        g.env.G.GetCameraZoom = None
    elif how == "raises":
        g.stub.zoomError = True
    else:
        g.stub.zoom = "far"
    plate = restricted_plate(g)
    burst(g, plate=plate, n=5, x=300, y=300, kind="kill")
    (G,) = pop_frames(g)
    assert anchor_of(G) == ("CENTER", "CENTER", 0, -20)
    g.slash("status chat")  # must not raise either
    status = [str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1) if "anchor: zoom=" in str(g.stub.chat[i])]
    assert status and "offset=n/a" in status[-1]


# ---------------------------------------------------------------- commands


def test_zoomanchor_command_persists_and_reports(env):
    g = make(env)
    g.slash("zoomanchor on")
    assert g.db.zoomAnchor is True
    line = chat_tail(g)[0]
    assert (
        "anchor: zoom=on" in line
        and "a=10.0" in line
        and "b=500.0" in line
        and "zMin=2.0" in line
    )
    assert "camera=15.0" in line and "offset=43.3" in line
    g.slash("zoomanchor off")
    assert g.db.zoomAnchor is False
    g.slash("zoomanchor")
    assert "zoom=off" in chat_tail(g)[0] and g.db.zoomAnchor is False
    g.slash("zoomanchor bogus")
    assert "usage" in chat_tail(g)[0]


def test_status_line(env):
    g = make(env)
    set_points(g, [(5, 50)])
    g.slash("status chat")
    lines = [str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1)]
    assert any(
        "anchor: zoom=off a=10.0 b=500.0 zMin=2.0 camera=15.0 offset=43.3 points=1" in ln
        for ln in lines
    )


def test_calib_save_fit_reset(env):
    g = make(env)
    g.stub.zoom = 5
    g.slash("calib save")
    g.stub.zoom = 20
    g.slash("calib save")
    assert pts(g) == [(5, pytest.approx(110)), (20, pytest.approx(35))]
    g.slash("calib fit")
    assert g.db.zoomA == pytest.approx(10) and g.db.zoomB == pytest.approx(500)
    g.slash("calib reset")
    assert pts(g) == [] and (g.db.zoomA, g.db.zoomB, g.db.zoomMin) == (5, 175, 5)
    g.slash("calib fit")
    assert "two or more different zooms" in chat_tail(g)[0]
    g.stub.zoom = 5
    g.slash("calib save")
    g.slash("calib save")  # same zoom twice: degenerate
    g.slash("calib fit")
    assert "two or more different zooms" in chat_tail(g)[0]


def test_save_keeps_eight_points_and_needs_a_readable_zoom(env):
    g = make(env)
    for z in range(3, 15):
        g.stub.zoom = z
        g.slash("calib save")
    assert len(pts(g)) == 8 and pts(g)[0][0] == 7
    g.stub.zoom = g.stub.SECRET
    g.slash("calib save")
    assert len(pts(g)) == 8 and "unreadable" in chat_tail(g)[0]


# ---------------------------------------------------------------- calibration panel


def marker_anchor(g):
    m = g.ns.Calib.marker
    assert len(m.points) <= 1
    return m.points[1] if m.points else None


def test_calib_open_close_leaves_no_onupdate(env):
    g = make(env)
    assert updaters(g) == []
    g.slash("calib")
    assert g.ns.Calib.panel.shown
    assert g.ns.Calib.panel.scripts.OnUpdate is not None
    assert len(updaters(g)) == 1
    g.slash("calib off")
    assert not g.ns.Calib.panel.shown and not g.ns.Calib.marker.shown
    assert updaters(g) == []


def test_marker_tracks_the_target_plate_with_one_anchor(env):
    g = make(env)
    plate = restricted_plate(g, hostile=True, cx=700, cy=400)
    g.stub.units["target"] = g.stub.units["nameplate1"]
    g.stub.plates["target"] = plate
    g.stub.zoom = 15
    g.slash("calib")
    m = g.ns.Calib.marker
    pt = marker_anchor(g)
    assert m.shown and pt[1] == "CENTER" and OWN(g, pt[2], plate) and pt[3] == "BOTTOM"
    assert pt[5] == pytest.approx(-(10 + 500 / 15))
    g.stub.zoom = 5
    g.stub.tick(0.2)  # the 10 Hz tick re-anchors
    assert marker_anchor(g)[5] == pytest.approx(-110)
    assert len(plate.points) == 0  # nothing was ever anchored on the plate's side
    assert g.stub.restrictedHits == 0
    # no target plate: the marker hides
    g.stub.plates["target"] = None
    g.stub.tick(0.2)
    assert not m.shown
    g.slash("calib off")
    assert g.stub.restrictedHits == 0


def test_nudge_save_and_fit_through_the_panel(env):
    g = make(env)
    plate = restricted_plate(g, hostile=True)
    g.stub.plates["target"] = plate
    g.slash("calib")
    panel = g.ns.Calib.panel
    wheel = panel.scripts.OnMouseWheel
    wheel(panel, -1)  # +2 (wheel down moves the marker down)
    wheel(panel, -1)  # +4
    wheel(panel, 1)  # +2
    g.stub.zoom = 5
    g.slash("calib save")
    assert pts(g) == [(5, pytest.approx(10 + 100 + 2))]
    g.db.zoomPoints = g.env.lua.table_from([g.db.zoomPoints[1]])  # keep only the nudged point
    g.db.zoomA, g.db.zoomB = 10, 500  # undo the curve shift the save made
    g.stub.zoom = 20
    g.slash("calib save")  # off 35, nudge already reset
    assert pts(g)[1] == (20, pytest.approx(35))
    g.slash("calib fit")
    assert g.db.zoomB == pytest.approx(77 / 0.15)
    assert g.db.zoomA == pytest.approx(112 - 77 / 0.15 * 0.2)
    assert g.stub.restrictedHits == 0
    g.slash("calib off")


def test_panel_buttons_call_the_handlers(env):
    g = make(env)
    g.slash("calib")
    buttons = {
        str(f.text): f
        for f in lua_list(g.stub.frames)
        if f.kind == "Button"
    }
    assert {"Down", "Up", "Save point", "Fit", "Close"} <= set(buttons)
    g.stub.zoom = 10
    buttons["Save point"].scripts.OnClick(buttons["Save point"])
    assert len(pts(g)) == 1
    buttons["Close"].scripts.OnClick(buttons["Close"])
    assert not g.ns.Calib.panel.shown
    assert updaters(g) == []


# ---------------------------------------------------------------- design-review fixes: direction, reticle, readout


def panel_texts(g):
    fs = [f for f in lua_list(g.stub.frames) if f.kind == "FontString" and OWN(g, f.parentFrame, g.ns.Calib.panel)]
    return {str(f.text)[:4]: f for f in fs if f.text}


def panel_buttons(g):
    return {str(f.text): f for f in lua_list(g.stub.frames) if f.kind == "Button" and f.text}


def target_plate(g, zoom=10):
    plate = restricted_plate(g, hostile=True, cx=700, cy=400)
    g.stub.plates["target"] = plate
    g.stub.zoom = zoom
    return plate


def test_up_button_moves_the_marker_up_and_down_moves_it_down(env):
    g = make(env)
    target_plate(g)
    g.slash("calib")
    b = panel_buttons(g)
    y0 = marker_anchor(g)[5]
    b["Up"].scripts.OnClick(b["Up"])
    y1 = marker_anchor(g)[5]
    assert y1 == pytest.approx(y0 + 2)  # less negative = higher on screen
    b["Down"].scripts.OnClick(b["Down"])
    b["Down"].scripts.OnClick(b["Down"])
    assert marker_anchor(g)[5] == pytest.approx(y0 - 2)
    assert (b["Down"].width, b["Up"].width) == (44, 44)


def test_mouse_wheel_up_moves_the_marker_up(env):
    g = make(env)
    target_plate(g)
    g.slash("calib")
    y0 = marker_anchor(g)[5]
    panel = g.ns.Calib.panel
    panel.scripts.OnMouseWheel(panel, 1)
    assert marker_anchor(g)[5] == pytest.approx(y0 + 2)
    panel.scripts.OnMouseWheel(panel, -1)
    panel.scripts.OnMouseWheel(panel, -1)
    assert marker_anchor(g)[5] == pytest.approx(y0 - 2)


def test_fit_is_disabled_until_two_points_are_saved(env):
    g = make(env)
    target_plate(g)
    g.slash("calib")
    fit = panel_buttons(g)["Fit"]
    assert fit.disabled is True
    g.stub.zoom = 10
    g.slash("calib save")
    assert fit.disabled is True
    g.stub.zoom = 20
    g.slash("calib save")
    assert fit.disabled is False
    g.slash("calib reset")
    assert fit.disabled is True


def test_readout_sits_under_the_title_and_cannot_spill(env):
    g = make(env)
    g.slash("calib")
    panel = g.ns.Calib.panel
    fs = [f for f in lua_list(g.stub.frames) if f.kind == "FontString" and OWN(g, f.parentFrame, panel)]
    title = next(f for f in fs if str(f.text) == "XP Orbs Calibration")
    readout = panel_texts(g)["zoom"]
    assert readout.points[1][5] < title.points[1][5]  # lower on screen than the title
    assert readout.points[1][4] + readout.width <= panel.width - 12  # inside the 12 px side padding


def test_readout_says_what_is_missing_without_a_plate(env):
    g = make(env)
    plate = target_plate(g, zoom=12)
    g.slash("calib")
    assert "offset" in str(panel_texts(g)["zoom"].text) and "target a mob" not in str(panel_texts(g)["zoom"].text)
    g.stub.plates["target"] = None
    g.stub.tick(0.2)
    text = str(panel_texts(g)["zoom"].text)
    assert "target a mob with its nameplate showing" in text and "zoom 12.0" in text
    assert not g.ns.Calib.marker.shown
    assert plate is not None


def test_marker_is_a_four_arm_reticle_beyond_the_orb(env):
    g = make(env)
    g.slash("calib")
    arms = list(lua_list(g.ns.Calib.marker.arms))
    assert len(arms) == 4
    assert sorted((a.width, a.height) for a in arms) == [(2, 12), (2, 12), (12, 2), (12, 2)]
    for a in arms:
        pt = a.points[1]
        assert max(abs(pt[4]), abs(pt[5])) == 12  # arm centre; arms span 6..18 px from the centre


# ---------------------------------------------------------------- save refits at once


def marker_off(g):
    return -marker_anchor(g)[5]


def panel_setup(g):
    plate = restricted_plate(g, hostile=True)
    g.stub.plates["target"] = plate
    g.slash("calib")
    return g.ns.Calib.panel.scripts.OnMouseWheel, g.ns.Calib.panel


def test_save_one_point_shifts_a_and_the_marker_stays(env):
    g = make(env)
    wheel, panel = panel_setup(g)
    g.stub.zoom = 5
    for _ in range(5):
        wheel(panel, -1)  # wheel down: +10 px in all
    before = marker_off(g)
    assert before == pytest.approx(120)
    g.slash("calib save")
    assert g.db.zoomB == pytest.approx(500) and g.db.zoomA == pytest.approx(20)
    g.stub.tick(0.2)
    assert marker_off(g) == pytest.approx(before, abs=0.5)


def test_save_two_or_more_points_refits_and_the_marker_stays(env):
    g = make(env)
    wheel, panel = panel_setup(g)
    g.stub.zoom = 5
    g.slash("calib save")
    g.stub.zoom = 20
    wheel(panel, -1)  # +2 px
    before = marker_off(g)
    g.slash("calib save")
    g.stub.tick(0.2)
    assert marker_off(g) == pytest.approx(before, abs=0.5)
    assert "curve refit" in "".join(chat_lines_of(g))


def chat_lines_of(g):
    return [str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1)]


DEV_POINTS = [(14.78, 15.83), (4.78, 42.64), (38.77, 6.90), (50, 8), (24.46, 14.44), (14.45, 22.60),
               (6.45, 27.47), (0.78, 40)]  # fmt: skip


def test_fit_of_the_calibration_points_matches_the_defaults(env):
    g = make(env)
    t = g.env.lua.table_from
    a, b = g.ns.OrbMath.FitZoom(t([t({"z": z, "off": o}) for z, o in DEV_POINTS]), 5)
    assert a == pytest.approx(5.27, abs=0.02) and b == pytest.approx(174.4, abs=0.2)
