"""v0.14: glow intensity, circular shape independent of Show glow, landing-point offsets, picker hint.
Driven through stubs_m5.lua (same harness as test_v013)."""

import pytest
from test_m5 import build, ctl, panel_texts, show
from test_v013 import flash_tex, reset_shown, right_click, run_until_flash


@pytest.fixture
def m(env):
    return build(env)


def portrait(m, x=100, y=700, w=90, h=90):
    m.stub.makeBar("Portrait", x, y, w, h, True)
    m.G.Portrait.name = "Portrait"
    m.db.targetFrame = "Portrait"


def spy_centre_flags(m):
    """Record the `centre` argument of every Target:GetDestination call."""
    m.lua.execute(
        """
        local T = ...
        T.seen = {}
        local base = T.GetDestination
        function T:GetDestination(centre)
            T.seen[#T.seen + 1] = centre and true or false
            return base(self, centre)
        end
        """,
        m.ns.Target,
    )
    return m.ns.Target.seen


# ---------------------------------------------------------------- defaults


def test_new_defaults_are_deep_filled_without_a_bump(env):
    env.G.XPOrbsDB = env.lua.table_from({"version": 4, "glow": False})
    m = build(env)
    d = m.db
    assert (d.glowIntensity, d.glowOffsetX, d.glowOffsetY) == (100, 0, 0)
    assert d.glow is False and d.version == 6


def test_stored_new_values_survive_a_reload(env):
    env.G.XPOrbsDB = env.lua.table_from(
        {"version": 4, "glowIntensity": 50, "glowOffsetX": -7, "glowOffsetY": 12}
    )
    m = build(env)
    assert (m.db.glowIntensity, m.db.glowOffsetX, m.db.glowOffsetY) == (50, -7, 12)


# ---------------------------------------------------------------- OrbMath helpers


def test_glow_intensity_maths(m):
    g = m.ns.OrbMath.GlowIntensity
    assert tuple(g(100)) == (pytest.approx(1.0), pytest.approx(1.0))
    assert tuple(g(200)) == (pytest.approx(2.0), pytest.approx(1.2))
    assert tuple(g(25)) == (pytest.approx(0.25), pytest.approx(0.85))
    assert tuple(g(50)) == (pytest.approx(0.5), pytest.approx(0.9))
    # clamped, and junk counts as 100%
    assert g(1000)[0] == pytest.approx(2.0) and g(-5)[0] == pytest.approx(0.25)
    for junk in (None, "x", float("nan"), float("inf")):
        assert tuple(g(junk)) == (pytest.approx(1.0), pytest.approx(1.0))


def test_apply_offset(m):
    f = m.ns.OrbMath.ApplyOffset
    assert tuple(f(10, 20, 5, -3)) == (15, 17)
    assert tuple(f(10, 20, None, "x")) == (10, 20)
    assert tuple(f(10, 20, float("nan"), float("inf"))) == (10, 20)


def test_offset_snap_and_clamp_including_negatives(m):
    snap = m.ns.OrbMath.Snap
    assert snap(-37.4, -100, 100, 1) == -37
    assert snap(-37.6, -100, 100, 1) == -38
    assert snap(150, -100, 100, 1) == 100
    assert snap(-150, -100, 100, 1) == -100
    assert snap(0.4, -100, 100, 1) == 0
    assert snap(2.6, 25, 200, 5) == 25 and snap(63, 25, 200, 5) == 65


def test_parse_number_accepts_px_and_negatives(m):
    p = m.ns.OrbMath.ParseNumber
    assert p("-37") == -37 and p(" 12 px ") == 12 and p("-5px") == -5 and p("40%") == 40


# ---------------------------------------------------------------- the flash uses the intensity


def flash_alpha_and_size(m, percent):
    m.db.glowIntensity = percent
    m.stub.tick(0)  # same age, so only the intensity differs
    fl = flash_tex(m)
    return fl.alpha, (fl.width, fl.height)


def test_flash_alpha_and_size_scale_with_intensity(m):
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl is not None
    a100, (w100, h100) = flash_alpha_and_size(m, 100)
    assert 0 < a100 < 1
    a50, (w50, h50) = flash_alpha_and_size(m, 50)
    assert a50 == pytest.approx(a100 * 0.5)
    assert w50 == pytest.approx(w100 * 0.9) and h50 == pytest.approx(h100 * 0.9)
    a200, (w200, h200) = flash_alpha_and_size(m, 200)
    assert a200 == pytest.approx(min(1, a100 * 2))
    assert w200 == pytest.approx(w100 * 1.2) and h200 == pytest.approx(h100 * 1.2)
    a25, (w25, _) = flash_alpha_and_size(m, 25)
    assert a25 == pytest.approx(a100 * 0.25) and w25 == pytest.approx(w100 * 0.85)


def test_flash_alpha_is_clamped_to_one(m):
    m.db.glowIntensity = 200
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl is not None
    seen = []
    for _ in range(40):
        m.stub.tick(0.005)
        if fl.shown:
            seen.append(fl.alpha)
    assert seen and max(seen) <= 1.0


def test_round_flash_scales_with_intensity(m):
    portrait(m)
    m.db.glowShape = "round"
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl.width == fl.height == pytest.approx(90 * 1.3)
    m.db.glowIntensity = 200
    m.stub.tick(0)
    assert fl.width == fl.height == pytest.approx(90 * 1.3 * 1.2)
    m.db.glowIntensity = 25
    m.stub.tick(0)
    assert fl.width == pytest.approx(90 * 1.3 * 0.85)


def test_default_intensity_leaves_the_v013_flash_unchanged(m):
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl.width == pytest.approx(14 * 12) and fl.height == pytest.approx(
        14 * 12 / 7
    )


# ---------------------------------------------------------------- circular aims at the centre with the glow off


def test_round_aims_at_the_centre_with_the_glow_off(m):
    portrait(m)
    seen = spy_centre_flags(m)
    m.db.glowShape, m.db.glow = "round", False
    m.stub.xp, m.stub.xpMax = 900, 1000
    m.slash("test 5")
    m.run(2)
    assert len(seen) > 0 and all(seen[i] for i in range(1, len(seen) + 1))
    assert not flash_tex(m).shown


def test_bar_shape_never_asks_for_the_centre(m):
    seen = spy_centre_flags(m)
    m.db.glow = False
    m.slash("test 5")
    m.run(2)
    assert len(seen) > 0 and not any(seen[i] for i in range(1, len(seen) + 1))


def test_round_with_the_glow_on_lands_on_the_centre(m):
    portrait(m)
    m.db.glowShape = "round"
    m.stub.xp, m.stub.xpMax = 900, 1000
    m.slash("test 5")
    fl = run_until_flash(m)
    assert (fl.points[1][4], fl.points[1][5]) == (
        pytest.approx(145),
        pytest.approx(745),
    )


# ---------------------------------------------------------------- dimming


def test_shape_rows_stay_live_with_the_glow_off_but_intensity_dims(m):
    show(m)
    m.stub.click(ctl(m, "glow"))
    assert m.db.glow is False
    for k in ("glowShape", "glowShapeDesc", "glowOffsetX", "glowOffsetY"):
        assert m.opt.rows[k].alpha in (None, 1), k
    for k in ("glowShape_bar", "glowShape_round", "glowOffsetX", "glowOffsetY"):
        c = ctl(m, k)
        assert c.IsEnabled(c), k
    ri, si = m.opt.rows["glowIntensity"], ctl(m, "glowIntensity")
    assert ri.alpha == pytest.approx(0.4) and not si.IsEnabled(si)
    m.stub.click(ctl(m, "glow"))
    assert ri.alpha == 1 and si.IsEnabled(si)


# ---------------------------------------------------------------- offsets


def test_bar_offset_shifts_the_fill_edge(m):
    tg = m.ns.Target
    m.stub.xp, m.stub.xpMax = 250, 1000
    m.db.glowOffsetX, m.db.glowOffsetY = 15, -4
    x, y, ok = tg.GetDestination(tg)
    assert ok and (x, y) == (pytest.approx(600 + 15), pytest.approx(25 - 4))
    assert (tg.lastW, tg.lastH) == (800, 10)  # sizes are not offset


def test_round_offset_shifts_the_centre(m):
    tg = m.ns.Target
    m.db.glowOffsetX, m.db.glowOffsetY = -30, 22
    x, y, ok = tg.GetDestination(tg, True)
    assert ok and (x, y) == (pytest.approx(800 - 30), pytest.approx(25 + 22))


def test_fallback_destination_is_offset_too(m):
    tg = m.ns.Target
    m.G.MainStatusTrackingBarContainer.shown = False
    m.db.glowOffsetX, m.db.glowOffsetY = 10, 5
    x, y, ok = tg.GetDestination(tg)
    assert not ok and (x, y) == (pytest.approx(960 + 10), pytest.approx(20 + 5))


def test_offset_defaults_change_nothing(m):
    tg = m.ns.Target
    m.stub.xp, m.stub.xpMax = 250, 1000
    x, y, ok = tg.GetDestination(tg)
    assert (x, y) == (pytest.approx(600), pytest.approx(25))


def test_junk_offsets_in_the_db_are_ignored(m):
    tg = m.ns.Target
    m.db.glowOffsetX, m.db.glowOffsetY = "oops", False
    x, y, ok = tg.GetDestination(tg, True)
    assert (x, y) == (pytest.approx(800), pytest.approx(25))


def test_test_command_flash_lands_on_the_offset_point(m):
    m.stub.xp, m.stub.xpMax = 250, 1000
    m.db.glowOffsetX, m.db.glowOffsetY = 20, -3
    m.slash("test 5")
    fl = run_until_flash(m)
    assert (fl.points[1][4], fl.points[1][5]) == (pytest.approx(620), pytest.approx(22))


def test_round_flash_lands_on_the_centre_plus_offset(m):
    portrait(m)
    m.db.glowShape = "round"
    m.db.glowOffsetX, m.db.glowOffsetY = -50, 40
    m.slash("test 5")
    fl = run_until_flash(m)
    assert (fl.points[1][4], fl.points[1][5]) == (pytest.approx(95), pytest.approx(785))


# ---------------------------------------------------------------- panel rows


@pytest.mark.parametrize(
    "key,y,h",
    [
        ("glowShape", 554, 24),
        ("glowShapeDesc", 580, 84),
        ("glowOffsetX", 670, 32),
        ("glowOffsetY", 702, 32),
        ("glow", 760, 28),
        ("glowIntensity", 788, 32),
    ],
)
def test_new_rows_follow_the_grid(m, key, y, h):
    row = m.opt.rows[key]
    pt = row.points[1]
    assert (pt[1], pt[4], pt[5]) == ("TOPLEFT", 0, -y) and row.height == h


def test_new_sliders_use_the_slider_columns_and_ranges(m):
    for key, lo, hi, step in (
        ("glowIntensity", 25, 200, 5),
        ("glowOffsetX", -100, 100, 1),
        ("glowOffsetY", -100, 100, 1),
    ):
        s = ctl(m, key)
        assert (s.minV, s.maxV, s.step) == (lo, hi, step)
        assert s.points[1][4] == 260 and s.width == 200
        assert m.opt.valueButtons[key].points[1][4] == 472 and m.opt.editBoxes[key]
    labels = panel_texts(m)
    for t in ("Glow intensity", "Target offset X", "Target offset Y"):
        assert t in labels


def test_offset_description_line(m):
    d = m.opt.offsetDesc
    assert d.text == "Moves where orbs land and the glow appears (pixels)."
    assert (d.points[1][4], d.points[1][5]) == (32, -738)
    assert [d.textColor[i] for i in (1, 2, 3)] == pytest.approx([0.7, 0.7, 0.7])


def test_shape_description_text(m):
    assert m.opt.shapeDesc.text == (
        "Horizontal: orbs land on the bar's fill edge (a vertical bar the addon recognises gets the vertical glow "
        "automatically). Vertical: a bar that fills bottom to top. Circular: the centre of a round frame "
        "such as a portrait."
    )


def test_sliders_drive_the_db_and_show_units(m):
    show(m)
    m.stub.slide(ctl(m, "glowIntensity"), 150)
    m.stub.slide(ctl(m, "glowOffsetX"), -20)
    m.stub.slide(ctl(m, "glowOffsetY"), 35)
    assert (m.db.glowIntensity, m.db.glowOffsetX, m.db.glowOffsetY) == (150, -20, 35)
    texts = panel_texts(m)
    assert "150%" in texts and "-20 px" in texts and "35 px" in texts


def test_typed_offsets_snap_and_clamp(m):
    show(m)
    for key, typed, expect in (
        ("glowOffsetX", "-37.4", -37),
        ("glowOffsetX", "150", 100),
        ("glowOffsetY", "-150", -100),
        ("glowOffsetY", "12 px", 12),
        ("glowIntensity", "300", 200),
        ("glowIntensity", "2", 25),
        ("glowIntensity", "62", 60),
    ):
        right_click(m, key)
        assert m.opt.editBoxes[key].shown
        m.stub.enterText(m.opt.editBoxes[key], typed)
        assert m.db[key] == expect, (key, typed)
        assert ctl(m, key).value == expect


def test_edit_box_shows_a_negative_number(m):
    m.db.glowOffsetX = -37
    show(m)
    right_click(m, "glowOffsetX")
    assert m.opt.editBoxes["glowOffsetX"].text == "-37"


def test_hover_tip_names_the_negative_range(m):
    show(m)
    m.stub.hover(m.opt.valueButtons["glowOffsetX"])
    assert m.stub.tooltip.text == "Right-click to type a value (-100–100 px)"


# ---------------------------------------------------------------- per-row resets


@pytest.mark.parametrize(
    "key,value,tip",
    [
        ("glowIntensity", 150, "Reset to default: 100%"),
        ("glowOffsetX", -20, "Reset to default: 0 px"),
        ("glowOffsetY", 35, "Reset to default: 0 px"),
    ],
)
def test_reset_buttons_for_the_new_keys(m, key, value, tip):
    show(m)
    assert not reset_shown(m, key)
    m.stub.slide(ctl(m, key), value)
    assert m.db[key] == value and reset_shown(m, key)
    m.stub.hover(m.opt.resets[key])
    assert m.stub.tooltip.text == tip
    m.stub.click(m.opt.resets[key])
    assert m.db[key] == m.ns.defaults[key] and ctl(m, key).value == m.ns.defaults[key]
    assert not reset_shown(m, key)


def test_reset_all_covers_the_new_keys(m):
    m.db.glowIntensity, m.db.glowOffsetX, m.db.glowOffsetY = 50, 9, -9
    m.ns.commands.reset()
    assert (m.db.glowIntensity, m.db.glowOffsetX, m.db.glowOffsetY) == (100, 0, 0)


# ---------------------------------------------------------------- picker hint and layout


def test_picker_hint_fontstring(m):
    h = m.opt.pickHint
    assert h.kind == "FontString"
    assert h.text == (
        "Use this if another addon replaces the default XP bar, or to send the orbs somewhere else, such as "
        "your portrait with the Circular shape."
    )
    assert [h.textColor[i] for i in (1, 2, 3)] == pytest.approx([0.7, 0.7, 0.7])
    assert h.width == 520 and h.calls["SetWordWrap"][1] is True
    assert (h.points[1][4], h.points[1][5]) == (32, -1336)
    assert h.text in panel_texts(m)


def test_content_height_grew_and_rows_below_moved(m):
    assert m.opt.CONTENT_H == 1448 and m.opt.child.height == 1448
    assert m.opt.rows["debug"].points[1][5] == -1404
    assert 1404 + 28 + 16 == m.opt.CONTENT_H
    # the blocks above stack without overlap
    assert 678 + 16 <= 700 and 1106 + 30 <= 1140 and 1140 + 28 <= 1182


# ---------------------------------------------------------------- design-review fixes (docs/review-v013)


def fontstring(m, text):
    return next(f for f in m.stub.frames.values() if f.kind == "FontString" and f.text == text)


def test_top_rule_under_the_title(m):
    t = m.opt.topRule
    pt = t.points[1]
    assert (pt[1], pt[4], pt[5]) == ("TOPLEFT", 16, -38) and (t.width, t.height) == (552, 1)
    sp = m.opt.scroll.points[1]
    assert (sp[1], sp[4], sp[5]) == ("TOPLEFT", 0, -40)


def test_footer_rule_and_reset_all_share_the_right_edge(m):
    r = m.opt.footerRule
    pt = r.points[1]
    assert (pt[1], pt[4], pt[5]) == ("BOTTOMLEFT", 16, 44) and (r.width, r.height) == (552, 1)
    assert r.points[2] is None  # no BOTTOMRIGHT anchor any more
    ra = m.opt.resetAll
    rp = ra.points[1]
    assert (rp[1], rp[4], rp[5]) == ("BOTTOMLEFT", 408, 11) and ra.width == 160
    assert rp[4] + ra.width == 568 == pt[4] + r.width


@pytest.mark.parametrize(
    "key,name,x",
    [
        ("glowShape_bar", "Horizontal", 260),
        ("glowShape_vertical", "Vertical", 360),
        ("glowShape_round", "Circular", 460),
        ("style_crossfade", "Crossfade", 32),
    ],
)
def test_radio_owns_its_label_and_its_hit_rect_covers_it(m, key, name, x):
    rb = ctl(m, key)
    assert (rb.width, rb.height) == (20, 20) and rb.points[1][4] == x - 2
    lab = fontstring(m, name)
    assert lab.points[1][4] == x + 24
    ins = rb.calls["SetHitRectInsets"]
    assert (ins[1], ins[3], ins[4]) == (0, -4, -4) and ins[2] < 0
    reach = rb.points[1][4] + rb.width - ins[2]  # right edge of the clickable area
    assert reach >= lab.points[1][4] + lab.GetStringWidth(lab)
    m.stub.click(rb)  # the click the label region forwards to the button
    assert rb.checked


def test_radio_without_hit_rect_support_still_builds(env):
    env.lua.execute("local fm = getmetatable(UIParent).__index; fm.SetHitRectInsets = nil")
    m = build(env)
    assert m.opt.category is not None


def test_shape_description_width_and_spacing(m):
    sd = m.opt.shapeDesc
    assert sd.width == 280 and sd.calls["SetSpacing"][1] == 2


def test_section_is_named_arrival(m):
    texts = panel_texts(m)
    assert "Arrival" in texts and "Arrival glow" not in texts


def test_content_height_equals_the_cursor_result(m):
    last = m.opt.rows["debug"]
    assert m.opt.CONTENT_H == m.opt.child.height == -last.points[1][5] + last.height + 16
