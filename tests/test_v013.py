"""v0.13: options panel rework (scroll frame, grid, per-row resets, radios, value editing, Reset all), class colour,
arrival glow options, picker highlight. Driven through stubs_m5.lua."""

import re

import pytest
from conftest import make_runtime  # noqa: F401  (keeps the conftest import path obvious)
from test_m5 import armed, build, chain, ctl, panel_texts, show

DASH = "–"
PINK = (0.96, 0.55, 0.73)
BLUE = (0.20, 0.50, 1.00)
RESTED = (1.0, 0.30, 0.85)
UNDER = (0.02, 0.08, 0.30)


@pytest.fixture
def m(env):
    return build(env)


def no_template(*names):
    """pre-hook: CreateFrame raises for the given templates (a client that lacks them)."""

    def pre(env):
        env.lua.execute(
            """
            local names = ...
            local base = CreateFrame
            function CreateFrame(kind, name, parent, template)
                if names[template] then error("template not found: " .. tostring(template)) end
                return base(kind, name, parent, template)
            end
            """,
            env.lua.table_from({n: True for n in names}),
        )

    return pre


def rgb(c):
    return tuple(c[i] for i in (1, 2, 3))


def raw(m):
    return m.lua.eval("rawequal")


def rest(m):
    return pytest.approx


def tex_frames(m):
    return [f for f in m.stub.frames.values() if f.kind == "Texture"]


def orb_colours(m):
    """Vertex colours of every orb-art texture (not the underlay) that exists."""
    out = set()
    for f in tex_frames(m):
        st, vc = (
            f.calls and f.calls["SetTexture"],
            f.calls and f.calls["SetVertexColor"],
        )
        if st and vc and "media\\orb" in st[1]:
            c = tuple(round(vc[i], 3) for i in (1, 2, 3))
            if c != tuple(round(x, 3) for x in UNDER):
                out.add(c)
    return out


def sparkle_colours(m):
    out = set()
    for f in tex_frames(m):
        st, vc = (
            f.calls and f.calls["SetTexture"],
            f.calls and f.calls["SetVertexColor"],
        )
        if st and vc and "sparkle" in st[1]:
            out.add(tuple(round(vc[i], 3) for i in (1, 2, 3)))
    return out


def flash_tex(m):
    ov = m.orbs.overlay
    for f in tex_frames(m):
        if f.parentFrame is not None and raw(m)(f.parentFrame, ov):
            return f  # the first texture the overlay creates is the arrival flash
    raise AssertionError("no flash texture")


def run_until_flash(m, limit=4.0):
    fl, t = flash_tex(m), 0.0
    while t < limit:
        m.stub.tick(0.01)
        t += 0.01
        if fl.shown:
            return fl
    return None


def near(c, ref, tol=0.002):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def lerp_white(c, k=0.45):
    return tuple(x + (1 - x) * k for x in c)


def buttons(m):
    return {
        f.text: f
        for f in m.stub.frames.values()
        if f.kind == "Button" and f.template == "UIPanelButtonTemplate"
    }


def purple_of_last_test(m):
    return int(re.search(r"\((\d+) purple\)", m.say()[-1]).group(1))


def reset_shown(m, key):
    return bool(m.opt.resets[key].shown)


# ---------------------------------------------------------------- DB defaults (no schema bump)


def test_defaults_exist_and_a_v4_db_is_deep_filled_without_a_bump(env):
    env.G.XPOrbsDB = env.lua.table_from(
        {"version": 4, "cap": 7, "style": "crossfade"}, recursive=True
    )
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    db = env.G.XPOrbsDB
    assert (
        db.version == 4
    )  # InitDB's deep-fill adds the new keys: no schema bump needed
    assert db.classColor is False and db.glow is True and db.glowShape == "bar"
    assert db.cap == 7 and db.style == "crossfade"


def test_stored_new_values_survive_a_reload(env):
    env.G.XPOrbsDB = env.lua.table_from(
        {"version": 4, "classColor": True, "glow": False, "glowShape": "round"},
        recursive=True,
    )
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    db = env.G.XPOrbsDB
    assert db.classColor is True and db.glow is False and db.glowShape == "round"


# ---------------------------------------------------------------- class colour


def test_class_colour_off_by_default_orbs_are_blue(m):
    m.stub.setClass("PALADIN", *PINK)
    m.slash("test 5")
    assert orb_colours(m) == {BLUE}


def test_class_colour_orbs_sparkle_and_trail(m):
    m.stub.setClass("PALADIN", *PINK)
    m.db.classColor = True
    m.slash("test 5")
    assert orb_colours(m) == {PINK}  # orbs and their two trail ghosts
    spark = tuple(round(x + (1 - x) * 0.25, 3) for x in PINK)
    assert sparkle_colours(m) == {spark}


def test_class_colour_leaves_rested_orbs_alone(m):
    m.stub.setClass("PALADIN", *PINK)
    m.db.classColor = True
    m.slash("test 5 rested")
    assert orb_colours(m) == {PINK, RESTED}


def test_class_colour_reaches_the_arrival_flash(m):
    m.stub.setClass("PALADIN", *PINK)
    m.db.classColor = True
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl is not None
    vc = fl.calls["SetVertexColor"]
    assert near(tuple(vc[i] for i in (1, 2, 3)), lerp_white(PINK))


def test_rested_last_arrival_flashes_rested_colour(m):
    m.stub.setClass("PALADIN", *PINK)
    m.db.classColor = True
    m.orbs.Burst(m.orbs, m.lua.table_from({"x": 300, "y": 600, "n": 1, "nPurple": 1}))
    fl = run_until_flash(m)
    vc = fl.calls["SetVertexColor"]
    assert near(tuple(vc[i] for i in (1, 2, 3)), lerp_white(RESTED))


def test_class_colour_without_c_classcolor_uses_raid_class_colors(m):
    m.stub.setClass("PALADIN", *PINK, False)
    m.db.classColor = True
    m.slash("test 5")
    assert orb_colours(m) == {PINK}


@pytest.mark.parametrize("how", ["none", "noUnitClass"])
def test_class_colour_falls_back_to_db_colour(m, how):
    m.stub.setClass("PALADIN", *PINK, "none")
    if how == "noUnitClass":
        m.G.UnitClass = None
    m.db.classColor = True
    m.slash("test 5")  # no error
    assert orb_colours(m) == {BLUE}


def test_class_colour_with_a_throwing_api_falls_back(m):
    m.stub.setClass("PALADIN", *PINK)
    m.G.C_ClassColor = m.lua.eval("{ GetClassColor = function() error('boom') end }")
    m.db.classColor = True
    m.slash("test 5")
    assert orb_colours(m) == {BLUE}


def test_class_colour_checkbox_disables_the_swatch(m):
    show(m)
    sw, cb = ctl(m, "color"), ctl(m, "classColor")
    assert sw.IsEnabled(sw) and sw.alpha == 1
    m.stub.click(cb)
    assert m.db.classColor is True
    assert not sw.IsEnabled(sw) and sw.alpha == pytest.approx(0.35)
    m.stub.click(sw)  # a disabled swatch doesn't open the picker
    assert m.G.ColorPickerFrame.info is None
    m.stub.click(cb)
    assert sw.IsEnabled(sw) and sw.alpha == 1
    m.stub.click(sw)
    assert m.G.ColorPickerFrame.info is not None


def test_class_colour_checkbox_refreshes_from_the_db(m):
    m.db.classColor = True
    show(m)
    assert ctl(m, "classColor").checked is True and not ctl(m, "color").IsEnabled(
        ctl(m, "color")
    )


# ---------------------------------------------------------------- panel structure


def test_scroll_frame_exists_with_the_specified_anchors_and_content_height(m):
    o = m.opt
    assert o.scrollTemplate == "ScrollFrameTemplate"
    assert raw(m)(o.scroll.scrollChild, o.child)
    pts = [
        [p[i] for i in (1, 2, 3, 4, 5)]
        for p in (o.scroll.points[1], o.scroll.points[2])
    ]
    assert pts[0][0] == "TOPLEFT" and (pts[0][3], pts[0][4]) == (0, -40)
    assert pts[1][0] == "BOTTOMRIGHT" and (pts[1][3], pts[1][4]) == (-28, 44)
    assert o.child.width == 584 and o.child.height == pytest.approx(1076, abs=2)  # v0.14: 894 + 176


def test_scroll_template_falls_back(env):
    m = build(env, pre=no_template("ScrollFrameTemplate"))
    assert (
        m.opt.scrollTemplate == "UIPanelScrollFrameTemplate"
        and m.opt.category is not None
    )


def test_scroll_frame_without_any_template_still_scrolls(env):
    m = build(env, pre=no_template("ScrollFrameTemplate", "UIPanelScrollFrameTemplate"))
    s = m.opt.scroll
    assert m.opt.scrollTemplate is None and m.opt.category is not None
    s.scripts.OnMouseWheel(s, -1)
    assert s.vscroll == 40
    s.scripts.OnMouseWheel(s, 5)
    assert s.vscroll == 0


@pytest.mark.parametrize(
    "key,y",
    [
        ("enabled", 34),
        ("trail", 62),
        ("questBursts", 90),
        ("showAtMax", 118),
        ("density", 186),
        ("cap", 218),
        ("size", 250),
        ("flightTime", 282),
        ("color", 314),
        ("restedTint", 342),
        ("restedColor", 370),
        ("glow", 616),
        ("glowShape", 438),
        ("style_popstream", 716),
        ("style_crossfade", 762),
        ("style_stream", 808),
        ("targetFrame", 894),
        ("debug", 1032),
    ],
)
def test_row_positions_follow_the_spec(m, key, y):
    pt = m.opt.rows[key].points[1]
    assert (pt[1], pt[4], pt[5]) == ("TOPLEFT", 0, -y)
    assert raw(m)(pt[2], m.opt.child)


def test_row_heights(m):
    h = {
        k: m.opt.rows[k].height
        for k in (
            "enabled",
            "density",
            "color",
            "glowShape",
            "style_popstream",
            "targetFrame",
        )
    }
    assert h == {
        "enabled": 28,
        "density": 32,
        "color": 28,
        "glowShape": 24,
        "style_popstream": 24,
        "targetFrame": 36,
    }


def test_labels_are_in_the_label_column_controls_in_the_control_column(m):
    row = m.opt.rows["trail"]
    cb = ctl(m, "trail")
    assert (cb.points[1][4], cb.points[1][1]) == (257, "LEFT")  # CTRL_X - 3
    assert ctl(m, "cap").points[1][4] == 260 and (
        ctl(m, "cap").width,
        ctl(m, "cap").height,
    ) == (200, 16)
    assert (
        m.opt.valueButtons["cap"].points[1][4] == 472
        and m.opt.resets["cap"].points[1][4] == 548
    )
    assert row.width == 584


def test_the_title_is_fixed_and_the_footer_buttons_are_on_the_panel(m):
    b = buttons(m)
    assert set(b) >= {"Test burst", "Reset all to default", "Pick XP bar frame"}
    assert raw(m)(b["Test burst"].createdParent, m.opt.panel)
    assert raw(m)(b["Reset all to default"].createdParent, m.opt.panel)
    assert (b["Test burst"].width, b["Test burst"].height) == (110, 22)
    assert (b["Reset all to default"].width, b["Reset all to default"].height) == (
        160,
        22,
    )
    assert "XPOrbs" in panel_texts(m)


def test_label_rename(m):
    texts = panel_texts(m)
    assert "Orb quantity multiplier" in texts and "Orb multiplier" not in texts
    for t in (
        "Enabled",
        "Trail",
        "Quest bursts",
        "Show at max level",
        "Orb colour",
        "Class colour",
        "Rested tint",
        "Rested colour",
        "Show glow",
        "Target frame shape",
        "Horizontal",
        "Circular",
        "XP bar frame",
        "Debug log",
    ):
        assert t in texts, t


# ---------------------------------------------------------------- radios and descriptions


def test_style_radios_use_the_radio_template_and_each_has_a_description(m):
    descs = {st: m.opt.descs[st] for st in ("popstream", "crossfade", "stream")}
    texts = {st: d.text for st, d in descs.items()}
    assert texts == {
        "popstream": "A burst at the corpse, then a stream to the bar.",
        "crossfade": "Orbs bloom at the corpse, then fly straight to the bar.",
        "stream": "A plain stream from the target frame to the bar.",
    }
    assert all(d.kind == "FontString" for d in descs.values())
    objs = list(descs.values())
    assert (
        not raw(m)(objs[0], objs[1])
        and not raw(m)(objs[1], objs[2])
        and not raw(m)(objs[0], objs[2])
    )
    for st in descs:
        assert ctl(m, "style_" + st).template == "UIRadioButtonTemplate"
        assert (ctl(m, "style_" + st).width, ctl(m, "style_" + st).height) == (20, 20)  # v0.14 review: 20 px radios
    # the old run-together hint line is gone
    assert not any("popstream: a burst" in t for t in panel_texts(m))


def test_style_description_positions(m):
    d = m.opt.descs
    for st, y in (
        ("popstream", 716 + 24),
        ("crossfade", 762 + 24),
        ("stream", 808 + 24),
    ):
        pt = d[st].points[1]
        assert (pt[4], pt[5]) == (56, -y) and d[st].width == 490  # flush with the label (x + 24)
        assert [d[st].textColor[i] for i in (1, 2, 3)] == pytest.approx([0.7, 0.7, 0.7])


def test_radio_falls_back_to_a_check_button(env):
    m = build(env, pre=no_template("UIRadioButtonTemplate"))
    assert ctl(m, "style_popstream").template == "UICheckButtonTemplate"
    m.stub.click(ctl(m, "style_stream"))
    assert (
        m.db.style == "stream"
        and ctl(m, "style_stream").checked
        and not ctl(m, "style_popstream").checked
    )


def test_glow_shape_radios(m):
    show(m)
    assert ctl(m, "glowShape_bar").template == "UIRadioButtonTemplate"
    assert ctl(m, "glowShape_bar").checked and not ctl(m, "glowShape_round").checked
    m.stub.click(ctl(m, "glowShape_round"))
    assert m.db.glowShape == "round"
    assert ctl(m, "glowShape_round").checked and not ctl(m, "glowShape_bar").checked
    m.stub.click(
        ctl(m, "glowShape_round")
    )  # clicking the selected one keeps it selected
    assert ctl(m, "glowShape_round").checked
    assert m.opt.shapeDesc.text.startswith("Horizontal: orbs land on the bar's fill edge.")  # v0.14 wording


# ---------------------------------------------------------------- dimming


def test_rested_colour_dims_with_rested_tint(m):
    show(m)
    row, sw = m.opt.rows["restedColor"], ctl(m, "restedColor")
    assert row.alpha == 1 and sw.IsEnabled(sw)
    m.stub.click(ctl(m, "restedTint"))
    assert m.db.restedTint is False
    assert row.alpha == pytest.approx(0.4) and not sw.IsEnabled(sw)
    m.stub.click(ctl(m, "restedTint"))
    assert row.alpha == 1 and sw.IsEnabled(sw)


def test_glow_shape_does_not_dim_with_show_glow(m):
    # v0.14: the shape describes the target frame, so only the glow intensity dims (see test_v014.py)
    show(m)
    row, desc = m.opt.rows["glowShape"], m.opt.rows["glowShapeDesc"]
    rb = [ctl(m, "glowShape_bar"), ctl(m, "glowShape_round")]
    m.stub.click(ctl(m, "glow"))
    assert m.db.glow is False
    assert row.alpha in (None, 1) and desc.alpha in (None, 1)
    assert all(r.IsEnabled(r) for r in rb)


def test_dimming_follows_slash_and_db_changes_on_show(m):
    m.db.glow = False
    m.db.restedTint = False
    show(m)
    assert m.opt.rows["glowIntensity"].alpha == pytest.approx(0.4)
    assert m.opt.rows["restedColor"].alpha == pytest.approx(0.4)


# ---------------------------------------------------------------- per-row reset buttons


def test_all_resets_start_hidden_at_defaults(m):
    show(m)
    for key in (
        "enabled",
        "trail",
        "questBursts",
        "showAtMax",
        "density",
        "cap",
        "size",
        "flightTime",
        "color",
        "restedTint",
        "restedColor",
        "glow",
        "glowShape",
        "style",
        "targetFrame",
        "debug",
    ):
        assert not reset_shown(m, key), key


def test_checkbox_reset_shows_when_changed_and_resets(m):
    show(m)
    m.stub.click(ctl(m, "trail"))
    assert m.db.trail is False and reset_shown(m, "trail")
    m.stub.click(m.opt.resets["trail"])
    assert (
        m.db.trail is True and ctl(m, "trail").checked and not reset_shown(m, "trail")
    )


def test_slider_reset_logic_and_action(m):
    show(m)
    m.stub.slide(ctl(m, "cap"), 10)
    assert reset_shown(m, "cap")
    m.stub.click(m.opt.resets["cap"])
    assert m.db.cap == 40 and ctl(m, "cap").value == 40 and not reset_shown(m, "cap")
    # floats compare within 1e-4
    m.db.flightTime = 0.75 + 5e-5
    show(m)
    assert not reset_shown(m, "flightTime")
    m.db.flightTime = 0.75 + 5e-4
    show(m)
    assert reset_shown(m, "flightTime")
    m.stub.click(m.opt.resets["flightTime"])
    assert m.db.flightTime == pytest.approx(0.75)


def test_colour_reset_tolerance_and_action(m):
    d = list(rgb(m.ns.defaults.restedColor))
    m.db.restedColor = m.lua.table_from([d[0] + 0.004, d[1], d[2]])
    show(m)
    assert not reset_shown(m, "restedColor")
    m.db.restedColor = m.lua.table_from([d[0] - 0.006, d[1], d[2]])
    show(m)
    assert reset_shown(m, "restedColor")
    m.stub.click(m.opt.resets["restedColor"])
    assert rgb(m.db.restedColor) == pytest.approx(d)
    assert not raw(m)(
        m.db.restedColor, m.ns.defaults.restedColor
    )  # a copy, not the shared default table
    assert not reset_shown(m, "restedColor")


def test_swatch_change_through_the_picker_shows_the_reset(m):
    show(m)
    m.stub.click(ctl(m, "restedColor"))
    cp = m.G.ColorPickerFrame
    cp.r, cp.g, cp.b = 0.1, 0.2, 0.3
    cp.info.swatchFunc()
    assert reset_shown(m, "restedColor")


def test_orb_colour_row_reset_covers_colour_and_class_colour(m):
    show(m)
    m.stub.click(ctl(m, "classColor"))
    assert (
        reset_shown(m, "color") and raw(m)(m.opt.resets["classColor"], m.opt.resets["color"])
    )
    m.db.color = m.lua.table_from([0.9, 0.9, 0.1])
    m.stub.click(m.opt.resets["color"])
    assert m.db.classColor is False and rgb(m.db.color) == pytest.approx(BLUE)
    assert not ctl(m, "classColor").checked and ctl(m, "color").IsEnabled(
        ctl(m, "color")
    )
    assert not reset_shown(m, "color")
    m.db.color = m.lua.table_from([0.9, 0.9, 0.1])  # the colour alone also shows it
    show(m)
    assert reset_shown(m, "color")


def test_style_reset_on_the_popstream_row(m):
    show(m)
    m.stub.click(ctl(m, "style_crossfade"))
    assert reset_shown(m, "style")
    assert raw(m)(m.opt.resets["style"].createdParent, m.opt.rows["style_popstream"])
    m.stub.click(m.opt.resets["style"])
    assert (
        m.db.style == "popstream"
        and ctl(m, "style_popstream").checked
        and not reset_shown(m, "style")
    )


def test_glow_shape_and_glow_resets(m):
    show(m)
    m.stub.click(ctl(m, "glowShape_round"))
    m.stub.click(ctl(m, "glow"))
    assert reset_shown(m, "glowShape") and reset_shown(m, "glow")
    m.stub.click(m.opt.resets["glowShape"])
    m.stub.click(m.opt.resets["glow"])
    assert m.db.glowShape == "bar" and m.db.glow is True


def test_target_frame_reset_shows_for_any_non_nil_value(m):
    show(m)
    assert not reset_shown(m, "targetFrame")
    m.db.targetFrame = "MyBar"
    show(m)
    assert reset_shown(m, "targetFrame")
    m.stub.click(m.opt.resets["targetFrame"])
    assert m.db.targetFrame is None and not reset_shown(m, "targetFrame")
    assert "MainStatusTrackingBarContainer (auto)" in panel_texts(m)


def test_pick_shows_the_target_frame_reset_live(m):
    bar = m.stub.makeBar("MyBar", 100, 50, 600, 12, True)
    bar.name = "MyBar"
    show(m)
    m.stub.focus = bar
    m.slash("pick")
    m.stub.mouseDown("LeftButton")
    assert reset_shown(m, "targetFrame")
    m.slash("pick clear")
    assert not reset_shown(m, "targetFrame")


def test_slash_changes_update_the_resets_without_reopening(m):
    show(m)
    m.slash("style stream")
    assert reset_shown(m, "style") and ctl(m, "style_stream").checked
    m.slash("pop on")
    assert not reset_shown(m, "style")
    m.slash("debug on")
    assert reset_shown(m, "debug") and ctl(m, "debug").checked
    m.slash("debug off")
    assert not reset_shown(m, "debug")


def test_hidden_reset_buttons_keep_their_space(m):
    show(m)
    btn = m.opt.resets["trail"]
    before = [btn.points[1][i] for i in (1, 4, 5)]
    assert not btn.shown
    m.stub.click(ctl(m, "trail"))
    assert btn.shown and [btn.points[1][i] for i in (1, 4, 5)] == before
    assert (btn.width, btn.height) == (20, 20) and before[1] == 548


@pytest.mark.parametrize(
    "key,change,expect",
    [
        ("trail", lambda m: m.stub.click(ctl(m, "trail")), "Reset to default: on"),
        ("debug", lambda m: m.stub.click(ctl(m, "debug")), "Reset to default: off"),
        ("cap", lambda m: m.stub.slide(ctl(m, "cap"), 10), "Reset to default: 40"),
        (
            "density",
            lambda m: m.stub.slide(ctl(m, "density"), 200),
            "Reset to default: 100%",
        ),
        (
            "flightTime",
            lambda m: m.stub.slide(ctl(m, "flightTime"), 1.0),
            "Reset to default: 0.75 s",
        ),
        (
            "color",
            lambda m: m.stub.click(ctl(m, "classColor")),
            "Reset to default: #3380FF, class colour off",
        ),
        (
            "style",
            lambda m: m.stub.click(ctl(m, "style_stream")),
            "Reset to default: Popstream (default)",
        ),
        (
            "glowShape",
            lambda m: m.stub.click(ctl(m, "glowShape_round")),
            "Reset to default: Horizontal",
        ),
    ],
)
def test_reset_tooltip_names_the_default(m, key, change, expect):
    show(m)
    change(m)
    btn = m.opt.resets[key]
    assert btn.alpha == pytest.approx(0.75)
    m.stub.hover(btn)
    assert m.stub.tooltip.shown and m.stub.tooltip.text == expect
    assert btn.alpha == 1
    m.stub.unhover(btn)
    assert not m.stub.tooltip.shown and btn.alpha == pytest.approx(0.75)


def test_reset_target_frame_tooltip(m):
    m.db.targetFrame = "X"
    show(m)
    m.stub.hover(m.opt.resets["targetFrame"])
    assert m.stub.tooltip.text == "Reset to default: auto-detect"


def test_reset_icon_atlas_and_fallback(m, env):
    btn = m.opt.resets["trail"]
    icon = [
        t
        for t in tex_frames(m)
        if t.parentFrame is not None and raw(m)(t.parentFrame, btn)
    ][0]
    assert icon.atlas == "transmog-icon-revert"
    assert (
        btn.calls["SetHighlightTexture"][1]
        == "Interface\\Buttons\\ButtonHilight-Square"
    )
    assert btn.calls["SetHighlightTexture"][2] == "ADD"


def _fallback_icon(env, pre):
    m = build(env, pre=pre)
    btn = m.opt.resets["trail"]
    icon = [
        t
        for t in tex_frames(m)
        if t.parentFrame is not None and raw(m)(t.parentFrame, btn)
    ][0]
    return m, icon


def test_reset_icon_falls_back_when_the_atlas_is_missing(env):
    m, icon = _fallback_icon(
        env, lambda e: e.ns.stub.atlases.__setitem__("transmog-icon-revert", None)
    )
    assert (
        icon.atlas is None
        and icon.calls["SetTexture"][1] == "Interface\\Buttons\\UI-RefreshButton"
    )


def test_reset_icon_falls_back_without_c_texture(env):
    m, icon = _fallback_icon(env, lambda e: setattr(e.G, "C_Texture", None))
    assert (
        icon.atlas is None
        and icon.calls["SetTexture"][1] == "Interface\\Buttons\\UI-RefreshButton"
    )
    assert m.opt.category is not None


# ---------------------------------------------------------------- Reset all


def test_reset_all_asks_first_then_resets_on_accept(m):
    m.db.density, m.db.cap, m.db.style, m.db.glow, m.db.classColor = (
        300,
        10,
        "stream",
        False,
        True,
    )
    m.db.debug = True
    m.db.log = m.lua.table_from(["x"])
    show(m)
    m.stub.click(buttons(m)["Reset all to default"])
    assert list(m.stub.popups.values()) == ["XPORBS_RESET_ALL"]
    assert m.db.cap == 10  # nothing changed yet
    dlg = m.G.StaticPopupDialogs["XPORBS_RESET_ALL"]
    assert "Reset all" in dlg.text and dlg.button1 and dlg.button2
    dlg.OnAccept()
    assert (m.db.density, m.db.cap, m.db.style, m.db.glow, m.db.classColor) == (
        100,
        40,
        "popstream",
        True,
        False,
    )
    assert m.db.debug is True and m.db.log[1] == "x" and m.db.version == 4
    assert (
        ctl(m, "cap").value == 40
        and not reset_shown(m, "cap")
        and not reset_shown(m, "style")
    )
    assert "settings reset" in m.say()[-1]


def test_reset_all_without_the_popup_api_prints_a_hint_and_changes_nothing(env):
    m = build(env, pre=lambda e: setattr(e.G, "StaticPopup_Show", None))
    m.db.cap = 10
    m.stub.click(buttons(m)["Reset all to default"])
    assert m.db.cap == 10 and "/xporbs reset" in m.say()[-1]


# ---------------------------------------------------------------- Test burst button


def test_panel_test_burst_includes_rested_orbs_when_rested_tint_is_on(m):
    assert m.db.restedTint is True
    m.stub.click(buttons(m)["Test burst"])
    assert purple_of_last_test(m) > 0


def test_panel_test_burst_has_no_rested_orbs_when_rested_tint_is_off(m):
    m.db.restedTint = False
    m.stub.click(buttons(m)["Test burst"])
    assert purple_of_last_test(m) == 0


def test_slash_test_stays_explicit(m):
    m.slash("test 5")
    assert purple_of_last_test(m) == 0
    m.run(3)
    m.slash("test 5 rested")
    assert purple_of_last_test(m) > 0


# ---------------------------------------------------------------- value editing: logic


@pytest.mark.parametrize(
    "v,lo,hi,step,expect",
    [
        (130, 25, 400, 25, 125),
        (137, 25, 400, 25, 125),
        (140, 25, 400, 25, 150),
        (9999, 25, 400, 25, 400),
        (-5, 25, 400, 25, 25),
        (0, 5, 80, 1, 5),
        (33.4, 8, 32, 1, 32),
        (12.4, 8, 32, 1, 12),
        (0.77, 0.4, 1.5, 0.05, 0.75),
        (0.78, 0.4, 1.5, 0.05, 0.8),
        (0.15000000000000002 + 0.4, 0.4, 1.5, 0.05, 0.55),
        (2.0, 0.4, 1.5, 0.05, 1.5),
    ],
)
def test_snap_cases(m, v, lo, hi, step, expect):
    assert m.ns.OrbMath.Snap(v, lo, hi, step) == pytest.approx(expect, abs=1e-9)


def test_snap_rejects_non_numbers(m):
    snap = m.ns.OrbMath.Snap
    assert snap("abc", 0, 10, 1) is None and snap(None, 0, 10, 1) is None
    assert snap(float("nan"), 0, 10, 1) is None
    assert (
        snap(float("inf"), 0, 10, 1) is None and snap(float("-inf"), 0, 10, 1) is None
    )


@pytest.mark.parametrize(
    "s,expect",
    [
        ("150", 150),
        (" 150 ", 150),
        ("150%", 150),
        ("1.25", 1.25),
        ("1.25 s", 1.25),
        ("0.75s", 0.75),
        ("abc", None),
        ("", None),
        ("12abc", None),
        (None, None),
    ],
)
def test_parse_number(m, s, expect):
    assert m.ns.OrbMath.ParseNumber(s) == expect


def test_differs_rules(m):
    d = m.ns.OrbMath.Differs
    assert not d(1.0, 1.0 + 5e-5) and d(1.0, 1.0 + 5e-4)
    assert not d(True, True) and d(True, False) and d("a", "b")
    assert d("Foo", None) and not d(None, None)
    t = m.lua.table_from
    assert not d(t([0.2, 0.5, 1.0]), t([0.204, 0.5, 1.0])) and d(
        t([0.2, 0.5, 1.0]), t([0.206, 0.5, 1.0])
    )


# ---------------------------------------------------------------- value editing: panel


def right_click(m, key):
    m.stub.rightClick(m.opt.valueButtons[key])


def test_right_click_swaps_the_value_for_an_edit_box(m):
    show(m)
    eb, val = m.opt.editBoxes["density"], m.opt.valueTexts["density"]
    assert eb.template == "InputBoxTemplate" and not eb.shown
    right_click(m, "density")
    assert (
        eb.shown
        and eb.hasFocus
        and eb.highlighted
        and eb.text == "100"
        and not val.shown
    )
    assert (eb.width, eb.height) == (50, 20) and eb.points[1][4] == 477
    assert (
        m.opt.valueButtons["density"].width,
        m.opt.valueButtons["density"].height,
    ) == (56, 20)


def test_edit_box_shows_the_bare_number(m):
    m.db.flightTime = 0.75
    show(m)
    right_click(m, "flightTime")
    assert m.opt.editBoxes["flightTime"].text == "0.75"


def test_left_click_on_the_value_does_nothing(m):
    show(m)
    m.opt.valueButtons["density"].scripts.OnClick(
        m.opt.valueButtons["density"], "LeftButton"
    )
    assert not m.opt.editBoxes["density"].shown


def test_enter_applies_the_snapped_value(m):
    show(m)
    right_click(m, "density")
    m.stub.enterText(m.opt.editBoxes["density"], "130")
    assert m.db.density == 125 and ctl(m, "density").value == 125
    assert "125%" in panel_texts(m) and m.opt.valueTexts["density"].shown
    assert not m.opt.editBoxes["density"].shown and reset_shown(m, "density")


def test_edit_clamps_and_snaps_each_slider(m):
    show(m)
    for key, typed, expect in (
        ("density", "9999", 400),
        ("density", "1", 25),
        ("cap", "200", 80),
        ("size", "20.4", 20),
        ("flightTime", "0.77", 0.75),
        ("flightTime", "9", 1.5),
    ):
        right_click(m, key)
        m.stub.enterText(m.opt.editBoxes[key], typed)
        assert m.db[key] == pytest.approx(expect), (key, typed)


def test_edit_accepts_a_unit_suffix(m):
    show(m)
    right_click(m, "density")
    m.stub.enterText(m.opt.editBoxes["density"], "250%")
    assert m.db.density == 250


def test_losing_focus_applies(m):
    show(m)
    right_click(m, "cap")
    eb = m.opt.editBoxes["cap"]
    eb.SetText(eb, "12")
    eb.ClearFocus(eb)
    assert m.db.cap == 12 and not eb.shown


def test_escape_cancels(m):
    show(m)
    right_click(m, "density")
    m.stub.escapeText(m.opt.editBoxes["density"], "300")
    assert m.db.density == 100 and ctl(m, "density").value == 100
    assert not m.opt.editBoxes["density"].shown and "100%" in panel_texts(m)


@pytest.mark.parametrize("junk", ["abc", "", "   ", "12abc", "nan", "inf"])
def test_junk_input_is_ignored_without_an_error(m, junk):
    show(m)
    right_click(m, "size")
    m.stub.enterText(m.opt.editBoxes["size"], junk)
    assert m.db.size == 14 and "14" in panel_texts(m) and m.opt.valueTexts["size"].shown
    assert not m.opt.editBoxes["size"].shown


def test_enter_then_the_focus_loss_it_causes_applies_once(m):
    show(m)
    right_click(m, "cap")
    m.stub.enterText(m.opt.editBoxes["cap"], "20")
    assert m.db.cap == 20
    m.db.cap = 33  # a stray focus-lost afterwards must not re-apply the old text
    m.opt.editBoxes["cap"].scripts.OnEditFocusLost(m.opt.editBoxes["cap"])
    assert m.db.cap == 33


def test_value_hover_hint(m):
    show(m)
    hit, val = m.opt.valueButtons["density"], m.opt.valueTexts["density"]
    m.stub.hover(hit)
    assert [val.textColor[i] for i in (1, 2, 3)] == [1, 1, 1]
    assert (
        m.stub.tooltip.shown
        and m.stub.tooltip.text == f"Right-click to type a value (25{DASH}400%)"
    )
    m.stub.unhover(hit)
    assert not m.stub.tooltip.shown and val.textColor[3] == 0
    m.stub.hover(m.opt.valueButtons["flightTime"])
    assert m.stub.tooltip.text == f"Right-click to type a value (0.4{DASH}1.5 s)"
    m.stub.hover(m.opt.valueButtons["cap"])
    assert m.stub.tooltip.text == f"Right-click to type a value (5{DASH}80)"


def test_value_edit_is_skipped_when_the_input_template_is_missing(env):
    m = build(env, pre=no_template("InputBoxTemplate"))
    assert m.opt.category is not None
    show(m)
    m.stub.slide(ctl(m, "cap"), 10)  # the slider still works
    assert m.db.cap == 10


# ---------------------------------------------------------------- picker highlight


def tick(m, secs=0.1):
    m.stub.tick(secs)


def hl(m):
    return m.ns.Target.highlight


def test_no_highlight_and_no_updater_while_unarmed(m):
    assert hl(m) is None and m.ns.Target.pickFrame is None
    tick(m, 1)
    assert hl(m) is None


def test_highlight_follows_the_frame_that_would_be_picked(m):
    outer, _, leaf = chain(m, ["Holder", None, None])
    m.stub.focus = leaf
    m.slash("pick")
    assert not hl(m).shown  # nothing until the first update
    tick(m)
    assert hl(m).shown and raw(m)(hl(m).calls["SetAllPoints"][1], outer)
    other = m.stub.namedFrame("OtherBar")
    m.stub.focus = other
    tick(m)
    assert raw(m)(hl(m).calls["SetAllPoints"][1], other) and hl(m).shown


def test_highlight_label_shows_the_frame_name(m):
    m.stub.focus = chain(m, ["MyBarHolder", None])[-1]
    m.slash("pick")
    tick(m)
    labels = [
        f.text
        for f in m.stub.frames.values()
        if f.kind == "FontString" and f.text == "MyBarHolder"
    ]
    assert labels == ["MyBarHolder"]


def test_highlight_uses_the_picks_own_resolution(m):
    # the highlight shows what a click would store
    m.stub.focus = chain(m, ["Outer", "Mid", None])[-1]
    m.slash("pick")
    tick(m)
    shown = hl(m).calls["SetAllPoints"][1]
    m.stub.mouseDown("LeftButton")
    assert m.db.targetFrame == shown.name == "Mid"


def test_highlight_hides_when_nothing_is_pickable(m):
    m.stub.focus = chain(m, ["Holder"])[-1]
    m.slash("pick")
    tick(m)
    assert hl(m).shown
    m.stub.focus = chain(m, [None, None])[-1]  # unnamed all the way to UIParent
    tick(m)
    assert not hl(m).shown
    m.stub.focus = None
    tick(m)
    assert not hl(m).shown
    m.stub.focus = m.G.UIParent
    tick(m)
    assert not hl(m).shown


def test_highlight_never_covers_our_own_frames(m):
    m.slash("test 5")  # creates the overlay
    m.slash("pick")
    for f in (m.opt.panel, m.orbs.overlay, m.orbs.driver, hl(m)):
        m.stub.focus = f
        tick(m)
        assert not hl(m).shown


def test_highlight_never_takes_the_mouse(m):
    m.slash("pick")
    h = hl(m)
    assert h.calls["EnableMouse"][1] is False
    assert h.calls["SetFrameStrata"][1] == "TOOLTIP"
    assert m.ns.Target.PickName(h) is None
    assert m.ns.Target.PickName(m.lua.eval("CreateFrame")("Frame", None, h)) is None


@pytest.mark.parametrize("how", ["left", "right", "timeout", "clear"])
def test_highlight_hides_on_disarm(m, how):
    m.stub.focus = chain(m, ["Holder"])[-1]
    m.slash("pick")
    tick(m)
    assert hl(m).shown
    if how == "left":
        m.stub.mouseDown("LeftButton")
    elif how == "right":
        m.stub.mouseDown("RightButton")
    elif how == "timeout":
        m.stub.tick(15.5)
    else:
        m.slash("pick clear")
    assert not armed(m) and not hl(m).shown
    assert m.ns.Target.pickFrame.scripts.OnUpdate is None


def test_highlight_updates_are_throttled(m):
    m.stub.focus = chain(m, ["A"])[-1]
    m.slash("pick")
    tick(m, 0.1)
    first = m.stub.focus
    m.stub.focus = m.stub.namedFrame("B")
    tick(m, 0.01)  # under the 0.06 s step: still A
    assert raw(m)(hl(m).calls["SetAllPoints"][1], first)
    tick(m, 0.06)
    assert hl(m).calls["SetAllPoints"][1].name == "B"


def test_a_failing_anchor_just_means_no_highlight_for_that_frame(m):
    bad = m.stub.namedFrame("Restricted")
    m.slash("pick")
    h = hl(m)
    h.SetAllPoints = m.lua.eval(
        "function() error('SetPoint would result in anchor family connection') end"
    )
    m.stub.focus = bad
    tick(m)  # no error
    assert not h.shown
    tick(m)
    assert not h.shown
    m.stub.focus = chain(m, [None])[-1]
    tick(m)
    assert armed(m)  # the picker itself still works
    m.stub.focus = bad
    m.stub.mouseDown("LeftButton")
    assert m.db.targetFrame == "Restricted"


# ---------------------------------------------------------------- arrival glow


def test_glow_off_never_shows_the_flash(m):
    m.db.glow = False
    m.slash("test 5")
    fl = flash_tex(m)
    for _ in range(300):
        m.stub.tick(0.01)
        assert not fl.shown
    assert not m.orbs.Info(m.orbs)[0]  # the driver went idle without a flash lingering


def test_glow_on_still_flashes(m):
    m.slash("test 5")
    assert run_until_flash(m) is not None


def test_turning_glow_off_mid_flash_hides_it(m):
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl is not None
    m.db.glow = False
    m.stub.tick(0.01)
    assert not fl.shown


def test_bar_shape_is_the_horizontal_flash(m):
    m.slash("test 5")
    fl = run_until_flash(m)
    assert "media\\flash" in fl.calls["SetTexture"][1]
    assert fl.width == pytest.approx(14 * 12) and fl.height == pytest.approx(
        14 * 12 / 7
    )


def test_round_shape_is_a_circle_sized_from_the_destination_frame(m):
    m.stub.makeBar("Portrait", 100, 700, 90, 70, True)
    m.G.Portrait.name = "Portrait"
    m.db.targetFrame = "Portrait"
    m.db.glowShape = "round"
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl is not None
    assert "media\\orb" in fl.calls["SetTexture"][1]
    assert fl.width == fl.height == pytest.approx(70 * 1.3)
    cx, cy = 100 + 45, 700 + 35
    pt = fl.points[1]
    assert (pt[1], pt[4], pt[5]) == ("CENTER", pytest.approx(cx), pytest.approx(cy))


def test_round_diameter_is_clamped(m):
    for h, expect in ((10, 32), (200, 160)):
        m.stub.makeBar("Portrait", 100, 700, 300, h, True)
        m.G.Portrait.name = "Portrait"
        m.db.targetFrame = "Portrait"
        m.db.glowShape = "round"
        m.slash("test 5")
        fl = run_until_flash(m)
        assert fl.width == fl.height == pytest.approx(expect)
        m.run(2)


def test_round_without_a_frame_size_uses_six_times_the_orb_size(m):
    for n in (
        "MainStatusTrackingBarContainer",
        "StatusTrackingBarManager",
        "MainMenuExpBar",
    ):
        bar = m.G[n]
        if bar is not None:
            bar.shown = False
    m.db.glowShape = "round"
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl.width == fl.height == pytest.approx(14 * 6)
    assert fl.points[1][4] == pytest.approx(960)  # the bottom-centre fallback


def test_switching_shapes_swaps_the_texture_back(m):
    m.db.glowShape = "round"
    m.slash("test 5")
    fl = run_until_flash(m)
    assert "media\\orb" in fl.calls["SetTexture"][1]
    m.run(3)
    m.db.glowShape = "bar"
    m.slash("test 5")
    fl = run_until_flash(m)
    assert "media\\flash" in fl.calls["SetTexture"][1] and fl.width == pytest.approx(
        14 * 12
    )


def test_destination_centre_option(m):
    tg = m.ns.Target
    m.stub.xp, m.stub.xpMax = 250, 1000
    ex, ey, ok = tg.GetDestination(tg)
    assert ok and (ex, ey) == (pytest.approx(400 + 800 * 0.25), pytest.approx(25))
    cx, cy, ok = tg.GetDestination(tg, True)
    assert ok and (cx, cy) == (pytest.approx(800), pytest.approx(25))
    assert (tg.lastW, tg.lastH) == (800, 10)
    fx, fy, ok = tg.GetDestination(tg, False)
    assert (fx, fy) == (pytest.approx(ex), pytest.approx(ey))


def test_destination_centre_respects_scale_and_falls_back(m):
    tg = m.ns.Target
    m.G.MainStatusTrackingBarContainer.scale = 0.5
    cx, cy, ok = tg.GetDestination(tg, True)
    assert ok and (cx, cy) == (
        pytest.approx((400 + 400) * 0.5),
        pytest.approx((20 + 5) * 0.5),
    )
    assert (tg.lastW, tg.lastH) == (pytest.approx(400), pytest.approx(5))
    m.G.MainStatusTrackingBarContainer.shown = False
    x, y, ok = tg.GetDestination(tg, True)
    assert not ok and y == 20 and tg.lastW is None


def test_round_shape_aims_the_orbs_at_the_frame_centre(m):
    m.stub.makeBar("Portrait", 100, 700, 90, 90, True)
    m.G.Portrait.name = "Portrait"
    m.db.targetFrame = "Portrait"
    m.db.glowShape = "round"
    m.stub.xp, m.stub.xpMax = 900, 1000  # a fill edge would be at x = 181
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl.points[1][4] == pytest.approx(145) and fl.points[1][5] == pytest.approx(
        745
    )


def test_bar_shape_still_aims_at_the_fill_edge(m):
    m.stub.xp, m.stub.xpMax = 250, 1000
    m.slash("test 5")
    fl = run_until_flash(m)
    assert fl.points[1][4] == pytest.approx(600) and fl.points[1][5] == pytest.approx(
        25
    )


def test_glow_shape_aim_with_the_glow_off(m):
    # v0.14 reverses the v0.13 decision: the shape aims the orbs at the centre even with Show glow off (no flash drawn)
    m.stub.makeBar("Portrait", 100, 700, 90, 90, True)
    m.G.Portrait.name = "Portrait"
    m.db.targetFrame = "Portrait"
    m.db.glowShape, m.db.glow = "round", False
    m.stub.xp, m.stub.xpMax = 900, 1000
    m.slash("test 5")
    m.run(2)
    tg = m.ns.Target
    assert tg.lastName == "Portrait" and (tg.lastW, tg.lastH) == (90, 90)
    assert not flash_tex(m).shown


def test_glow_diameter_logic(m):
    g = m.ns.OrbMath.GlowDiameter
    assert g(100, 50, 14) == pytest.approx(65)
    assert g(10, 10, 14) == 32 and g(500, 500, 14) == 160
    assert g(None, None, 14) == 84 and g(0, 40, 10) == 60
