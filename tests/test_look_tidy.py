"""The Look tab tidy: the Outline option (was Blend), the one-row Rested orb colour, Crackle speed and Trail opacity."""

import pytest
from test_look_panel import PICK, pick, row_y, same
from test_m5 import build, ctl, show
from test_p2_unknown import live_recs
from test_shapes import go, make
from test_v102 import load_db


@pytest.fixture
def m(env):
    m = build(env)
    show(m)
    return m


def all_texts(m):
    return [
        str(f.text) for f in m.stub.frames.values() if f.kind == "FontString" and f.text
    ]


def reset_shown(m, key):
    return bool(m.opt.resets[key].shown)


# ---------------------------------------------------------------- Outline (was Blend)


def test_the_blend_option_is_called_outline(m):
    pick(m, "retro")
    texts = all_texts(m)
    assert "Outline" in texts and "Blend" not in texts
    assert not any("blend or extras" in t for t in texts)
    assert any(t.startswith("No outline or extras") for t in texts)
    # the radios: Glow (internal "natural") and Solid
    assert {"Glow", "Solid"} <= set(texts)
    assert "Natural" not in texts


def test_outline_tooltips_and_reset_text(m):
    pick(m, "globe")
    c = m.opt.controls
    m.stub.hover(c.blend_natural)
    assert "Soft glowing edge" in " ".join(str(x) for x in m.stub.tooltip.lines.values())
    m.stub.hover(c.blend_solid)
    assert "outline" in " ".join(str(x) for x in m.stub.tooltip.lines.values())
    m.stub.click(c.blend_solid)
    m.stub.hover(m.opt.resets["blend"])
    assert str(m.stub.tooltip.text) == "Reset to default: Outline glow"


# ---------------------------------------------------------------- Rested orb colour


def test_one_row_holds_the_rested_tickbox_and_swatch(m):
    assert "Rested tint" not in all_texts(m) and "Rested colour" not in all_texts(m)
    row = m.opt.rows["restedTint"]
    assert same(m, row, m.opt.rows["restedColor"])
    assert any(
        f.text == "Rested orb colour" and same(m, f.parentFrame, row)
        for f in m.stub.frames.values()
        if f.kind == "FontString"
    )
    tick, swatch = ctl(m, "restedTint"), ctl(m, "restedColor")
    assert same(m, tick.createdParent, row) and same(m, swatch.createdParent, row)
    # the tickbox first, on the standard checkbox column; the swatch to its right, centred under Class colour's tickbox
    assert tick.points[1][4] == 257
    assert swatch.points[1][4] == 298 and tick.points[1][4] + 24 < swatch.points[1][4]
    assert swatch.points[1][4] + 11 == ctl(m, "classColor").points[1][4] + 12


def test_the_rested_swatch_dims_with_its_tickbox_but_the_row_stays_bright(m):
    swatch, tick = ctl(m, "restedColor"), ctl(m, "restedTint")
    assert swatch.alpha == 1 and swatch.IsEnabled(swatch)
    m.stub.click(tick)
    assert m.db.restedTint is False
    assert swatch.alpha == pytest.approx(0.35) and not swatch.IsEnabled(swatch)
    assert m.opt.rows["restedTint"].alpha in (None, 1) and tick.IsEnabled(tick)
    m.stub.click(tick)
    assert swatch.alpha == 1 and swatch.IsEnabled(swatch)


def test_one_reset_restores_the_rested_tickbox_and_colour(m):
    assert not reset_shown(m, "restedTint")
    m.stub.click(ctl(m, "restedTint"))
    m.db.restedColor = m.lua.table_from([0.9, 0.1, 0.1])
    show(m)
    assert reset_shown(m, "restedTint") and same(
        m, m.opt.resets["restedTint"], m.opt.resets["restedColor"]
    )
    m.stub.click(m.opt.resets["restedTint"])
    assert m.db.restedTint is True
    assert [round(float(m.db.restedColor[i]), 2) for i in (1, 2, 3)] == [
        0.15,
        0.38,
        1.0,
    ]
    assert not reset_shown(m, "restedTint") and ctl(m, "restedTint").checked is True


# ---------------------------------------------------------------- Crackle speed


def test_crackle_speed_is_only_shown_for_crackle(m):
    row = m.opt.rows["crackleSpeed"]
    for shape in ("starlight", "retro", "globe"):
        pick(m, shape)
        assert not row.shown, shape
    pick(m, "crackle")
    assert row.shown
    # it takes the second option row's slot, centred on the same line
    assert row_y(m, "crackleSpeed") + 16 == row_y(m, "shapeExtra") + 14
    assert "Crackle speed" in all_texts(m)


def test_crackle_speed_default_range_and_typed_values(m):
    pick(m, "crackle")
    s = ctl(m, "crackleSpeed")
    assert (
        m.db.crackleSpeed == 100
        and (s.minV, s.maxV, s.step) == (50, 200, 10)
        and s.value == 100
    )
    assert str(m.opt.valueTexts["crackleSpeed"].text) == "100%"
    for typed, expect in (("999", 200), ("3", 50), ("73", 70)):
        m.stub.rightClick(m.opt.valueButtons["crackleSpeed"])
        m.stub.enterText(m.opt.editBoxes["crackleSpeed"], typed)
        assert m.db.crackleSpeed == expect, typed


def test_crackle_speed_is_saved_per_shape_and_has_its_own_reset(m):
    pick(m, "crackle")
    reset = m.opt.resets["crackleSpeed"]
    assert not reset.shown
    m.stub.slide(ctl(m, "crackleSpeed"), 150)
    assert m.db.crackleSpeed == 150 and m.db.shapeLook.crackle.crackleSpeed == 150
    assert (
        reset.shown
        and not m.opt.resets["shapeExtra"].shown
        and not m.opt.resets["blend"].shown
    )
    pick(m, "globe")
    assert m.db.crackleSpeed == 100 and m.db.shapeLook.globe.crackleSpeed == 100
    pick(m, "crackle")
    assert m.db.crackleSpeed == 150 and ctl(m, "crackleSpeed").value == 150
    m.stub.hover(reset)
    assert str(m.stub.tooltip.text) == "Reset to default: 100%"
    m.stub.click(reset)
    assert (
        m.db.crackleSpeed == 100
        and m.db.shapeLook.crackle.crackleSpeed == 100
        and not reset.shown
    )


def test_crackle_speed_loads_snapped_and_defaults_when_missing(env):
    db = load_db(
        env,
        {
            "version": 7,
            "orbShape": "crackle",
            "shapeLook": {"crackle": {"crackleSpeed": 133}},
        },
    )
    assert db.crackleSpeed == 130 and db.shapeLook.crackle.crackleSpeed == 130
    assert db.shapeLook.retro.crackleSpeed == 100
    db = load_db(
        env,
        {
            "version": 7,
            "orbShape": "crackle",
            "shapeLook": {"crackle": {"crackleSpeed": 9000}},
        },
    )
    assert db.crackleSpeed == 200
    db = load_db(
        env,
        {"version": 7, "orbShape": "crackle", "shapeLook": {"crackle": {"size": 20}}},
    )
    assert db.crackleSpeed == 100 and db.shapeLook.crackle.size == 20
    db = load_db(env, {"version": 7})  # an old save without the key at all
    assert db.crackleSpeed == 100 and all(
        db.shapeLook[s].crackleSpeed == 100 for s in PICK
    )


@pytest.mark.parametrize(
    "speed, every", [(100, 0.08), (200, 0.04), (50, 0.16), (150, 0.08 / 1.5)]
)
def test_crackle_speed_scales_the_bolt_interval(env, speed, every):
    g = make(
        env
    )  # math.random is fixed at 0.5: the interval is 70 + 0.5 * 20 = 80 ms at 100 %
    g.db.crackleSpeed = speed
    go(g, "crackle", n=1, trail=False, advance=0.05)
    (o,) = live_recs(g)
    assert o.boltEvery == pytest.approx(every)


def test_other_shapes_ignore_the_crackle_speed(env):
    g = make(env)
    g.db.crackleSpeed = 200
    go(g, "globe", n=1, trail=False, advance=0.05)
    (o,) = live_recs(g)
    assert o.boltEvery is None


# ---------------------------------------------------------------- Trail opacity


def test_trail_opacity_sits_under_trail_with_defaults(m):
    assert m.db.trailOpacity == 100 and m.ns.defaults.trailOpacity == 100
    s = ctl(m, "trailOpacity")
    assert (s.minV, s.maxV, s.step) == (0, 100, 5) and s.value == 100
    assert str(m.opt.valueTexts["trailOpacity"].text) == "100%"
    assert row_y(m, "trailOpacity") == row_y(m, "trail") + 28
    assert not reset_shown(m, "trailOpacity")
    m.stub.slide(s, 40)
    assert m.db.trailOpacity == 40 and reset_shown(m, "trailOpacity")
    m.stub.click(m.opt.resets["trailOpacity"])
    assert m.db.trailOpacity == 100 and s.value == 100


def test_trail_opacity_snaps_on_load(env):
    assert load_db(env, {"version": 7, "trailOpacity": 77}).trailOpacity == 75
    assert load_db(env, {"version": 7, "trailOpacity": 500}).trailOpacity == 100
    assert load_db(env, {"version": 7, "trailOpacity": -9}).trailOpacity == 0
    assert load_db(env, {"version": 7, "trailOpacity": "x"}).trailOpacity == 100
    assert load_db(env, {"version": 7}).trailOpacity == 100  # a save without the key


def test_trail_opacity_dims_with_the_trail_tickbox(m):
    row, slider = m.opt.rows["trailOpacity"], ctl(m, "trailOpacity")
    assert row.alpha == 1 and slider.IsEnabled(slider)
    m.stub.click(ctl(m, "trail"))
    assert m.db.trail is False
    assert row.alpha == pytest.approx(0.4) and not slider.IsEnabled(slider)
    m.stub.click(ctl(m, "trail"))
    assert row.alpha == 1 and slider.IsEnabled(slider)


BASE = {
    "starlight": [0.55, 0.30, 0.15],
    "retro": [0.70, 0.40],
    "globe": [0.52, 0.36, 0.22, 0.12],
    "crackle": [0.55, 0.30, 0.15],
}


def ghost_ratios(g, shape, opacity):
    g.db.trailOpacity = opacity
    go(g, shape, n=1, trail=True, advance=0.5)
    (o,) = live_recs(g)
    ghosts = [t for t in (o.ghost1, o.ghost2, o.ghost3, o.ghost4) if t is not None]
    assert ghosts and all(t.shown for t in ghosts)
    return [t.alpha / o.body.alpha for t in ghosts]


@pytest.mark.parametrize("shape", list(BASE))
def test_trail_opacity_scales_every_shapes_ghosts(env, shape):
    assert ghost_ratios(make(env, trail=True), shape, 100) == pytest.approx(
        BASE[shape], abs=1e-6
    )
    half = ghost_ratios(make(env, trail=True), shape, 50)
    assert half == pytest.approx([a * 0.5 for a in BASE[shape]], abs=1e-6)


@pytest.mark.parametrize("shape", list(BASE))
def test_zero_trail_opacity_draws_no_ghosts(env, shape):
    g = make(env, trail=True)
    g.db.trailOpacity = 0
    go(g, shape, n=2, trail=True, advance=0.5)
    assert all(o.ghost1 is None and o.ghost2 is None for o in live_recs(g))
