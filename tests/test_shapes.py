"""Selectable orb shapes (db.orbShape): Starlight (the original), Retro, Bubble and Crackle. Settings, the slash command,
the Options dropdown, the art every shape puts on its textures (flying orbs, corpse pops, crossfade copies A and B),
the texture budget, each shape's behaviour (Bubble glint and pulse, Retro grid snapping and twinkle, Crackle bolt ticks), the
per-burst snapshot and the media files."""

import math
import re
import struct
from itertools import pairwise

import pytest
from conftest import ROOT
from test_m5 import build, ctl, show
from test_p2_styles import a_orbs
from test_p2_unknown import LCG, b_orbs, fire, live_recs
from test_ui_v130 import menu, selection, texts
from test_v09 import make, pop_textures
from test_v102 import load_db

MEDIA = ROOT / "media"
PRE = "Interface\\AddOns\\XPOrbs\\media\\"
SHAPES = ["starlight", "retro", "bubble", "crackle"]
BOLTS = [PRE + f"bolt{i}" for i in range(1, 5)]
TWO_PI = 2 * math.pi

# the art each shape puts on (under, body, spark) of a flying orb or a pop slot
ART = {
    "starlight": (PRE + "orb", PRE + "orb", PRE + "sparkle"),
    "retro": (PRE + "retro_under", PRE + "retro", PRE + "retro_twinkle"),
    "bubble": (PRE + "bubble_under", PRE + "bubble", PRE + "bubble_glint"),
    "crackle": (PRE + "orb", PRE + "crackle_core", BOLTS),
}
GHOST_ART = {
    "starlight": PRE + "orb",
    "bubble": PRE + "bubble",
    "crackle": PRE + "crackle_core",
}
# pool textures per flying orb: (with the trail, without)
NEED = {"starlight": (6, 3), "retro": (5, 3), "bubble": (7, 3), "crackle": (6, 3)}


def path_of(tex):
    return str(tex.calls["SetTexture"][1])


def art_ok(tex, expected):
    got = path_of(tex)
    return got in expected if isinstance(expected, list) else got == expected


def set_shape(g, shape):
    g.db.orbShape = shape
    if shape == "retro" and g.db.size > 5:  # Retro's size is px per art pixel (1..5), not an orb size
        g.db.size = 2


def flying(g):
    """The live orb records of the current burst."""
    return live_recs(g)


def go(g, shape, style="stream", n=3, trail=True, advance=0.25, **kw):
    set_shape(g, shape)
    g.db.trail = trail
    fire(g, style, n=n, **kw)
    g.tick(0.05, round(advance / 0.05))


def in_use(g):
    return g.orbs.Info(g.orbs)[1]


# ---------------------------------------------------------------- settings


def test_default_is_starlight(env):
    assert load_db(env, {}).orbShape == "starlight"


@pytest.mark.parametrize("shape", SHAPES)
def test_saved_shapes_survive(env, shape):
    assert load_db(env, {"version": 7, "orbShape": shape}).orbShape == shape


@pytest.mark.parametrize("bad", ["junk", "", "Retro", "build", "by", 5, True, 0.5])
def test_unknown_values_become_starlight(env, bad):
    assert load_db(env, {"version": 7, "orbShape": bad}).orbShape == "starlight"


def test_no_schema_bump(env):
    db = load_db(env, {"version": 7})
    assert db.version == 7 and db.orbShape == "starlight"


# ---------------------------------------------------------------- slash command


def test_slash_shape_sets_prints_and_rejects(env):
    m = build(env)
    m.slash("shape")
    assert m.say()[-1].endswith("orb shape: Starlight")
    for word, label in (
        ("retro", "Retro"),
        ("bubble", "Bubble"),
        ("crackle", "Crackle"),
        ("starlight", "Starlight"),
    ):
        m.slash(f"shape {word}")
        assert m.db.orbShape == word and m.say()[-1].endswith(f"orb shape: {label}")
    m.slash("shape retro")
    m.slash("shape bogus")
    assert (
        m.db.orbShape == "retro"
        and "shape: use starlight, retro, bubble or crackle" in m.say()[-1]
    )


def test_help_and_status_mention_the_shape(env):
    m = build(env)
    m.slash("help")
    assert any(
        "/xporbs shape" in line and "starlight|retro|bubble|crackle" in line
        for line in m.say()
    )
    m.db.orbShape = "bubble"
    m.slash("status")
    assert any("orb shape: Bubble" in line for line in m.say())


def test_slash_refreshes_the_dropdown(env):
    m = build(env)
    show(m)
    m.slash("shape crackle")
    assert [s for _, s in selection(m.opt.shapeDropdown)] == [False, False, False, True]


# ---------------------------------------------------------------- Options


def test_orb_shape_dropdown_in_the_look_section(env):
    m = build(env)
    dropdown = m.opt.shapeDropdown
    assert (
        dropdown.kind == "DropdownButton"
        and dropdown.template == "WowStyle2DropdownTemplate"
        and dropdown.xpHost.template == "XPOrbsDropdownWithSteppersTemplate"
    )
    assert m.lua.eval("rawequal")(m.opt.controls["orbShape"], dropdown)
    assert "Orb shape" in texts(m)
    assert selection(dropdown) == [
        ("Starlight (default)", True),
        ("Retro", False),
        ("Bubble", False),
        ("Crackle", False),
    ]
    def y(key):
        return -m.opt.rows[key].points[1][5]

    assert y("orbShape") < y("pulse") < y("trail") < y("color")
    # the Look and Style sections are separate tabs now (Look first): the dropdown lives on Look's child
    assert m.lua.eval("rawequal")(m.opt.rows["orbShape"].createdParent, m.opt.tabChildren.Look)


def test_picking_a_shape_saves_it_and_shows_the_reset(env):
    m = build(env)
    show(m)
    btn = m.opt.resets["orbShape"]
    assert not btn.shown
    assert m.stub.pickMenu(m.opt.shapeDropdown, "Bubble") is True
    assert m.db.orbShape == "bubble" and btn.shown
    assert [s for _, s in selection(m.opt.shapeDropdown)] == [False, False, True, False]
    m.stub.click(btn)
    assert m.db.orbShape == "starlight" and not btn.shown
    assert selection(m.opt.shapeDropdown)[0][1] is True


def test_each_shape_has_its_own_menu_tooltip(env):
    m = build(env)
    bodies = []
    for entry in menu(m.opt.shapeDropdown):
        seen = []
        tooltip = m.lua.table_from(
            {
                "SetText": lambda _self, t, *a, seen=seen: seen.append(("title", t)),
                "AddLine": lambda _self, t, *a, seen=seen: seen.append(("body", t)),
            }
        )
        entry["tooltipFn"](tooltip, entry)
        assert (
            seen[0] == ("title", str(entry["text"]))
            and seen[1][0] == "body"
            and seen[1][1]
        )
        bodies.append(seen[1][1])
    assert len(set(bodies)) == 4


def test_the_button_shows_the_current_shapes_tooltip(env):
    m = build(env)
    dropdown = m.opt.shapeDropdown
    m.stub.hover(dropdown)
    assert str(m.stub.tooltip.text) == "Starlight" and m.stub.tooltip.shown
    m.stub.unhover(dropdown)
    m.db.orbShape = "crackle"
    m.stub.hover(dropdown)
    assert str(m.stub.tooltip.text) == "Crackle"


def test_radios_replace_the_shape_dropdown_without_the_template(env):
    def pre(e):
        e.lua.execute(
            """
            local make = CreateFrame
            function CreateFrame(kind, name, parent, template)
                if kind == "DropdownButton" then error("no dropdown") end
                return make(kind, name, parent, template)
            end
            """
        )

    m = build(env, pre=pre)
    assert m.opt.shapeDropdown is None
    show(m)
    assert ctl(m, "orbShape_starlight").checked
    m.stub.click(ctl(m, "orbShape_retro"))
    assert m.db.orbShape == "retro" and ctl(m, "orbShape_retro").checked
    assert not ctl(m, "orbShape_starlight").checked


# ---------------------------------------------------------------- the art on every kind of orb


@pytest.mark.parametrize("shape", SHAPES)
def test_flying_orbs_wear_their_shapes_art(env, shape):
    g = make(env, trail=True)
    go(g, shape)
    under, body, spark = ART[shape]
    recs = flying(g)
    assert len(recs) == 3
    for o in recs:
        assert art_ok(o.under, under) and art_ok(o.body, body) and art_ok(o.spark, spark)
        if shape == "retro":
            assert (
                o.ghost1.calls["SetColorTexture"] and o.ghost2.calls["SetColorTexture"]
            )
        else:
            ghosts = [o.ghost1, o.ghost2] + (
                [o.ghost3, o.ghost4] if shape == "bubble" else []
            )
            assert all(path_of(t) == GHOST_ART[shape] for t in ghosts)
    assert [o.shape is None for o in recs] == [shape == "starlight"] * len(recs)


@pytest.mark.parametrize("shape", SHAPES)
def test_pops_wear_their_shapes_art(env, shape):
    g = make(env, trail=True)
    go(g, shape, style="popstream", n=2, advance=0.1)
    under, body, spark = ART[shape]
    slots = pop_textures(g)
    assert len(slots) == 6
    for i in range(2):
        u, b, s = slots[3 * i : 3 * i + 3]
        assert art_ok(u, under) and art_ok(b, body) and art_ok(s, spark)


@pytest.mark.parametrize("shape", SHAPES)
def test_crossfade_copies_a_and_b_wear_their_shapes_art(env, shape):
    g = make(env, trail=True)
    set_shape(g, shape)
    fire(g, "crossfade", n=2)
    under, body, _ = ART[shape]
    g.tick(0.05, 5)  # inside the bloom: copy A is up
    a = [t for t in pop_textures(g) if t.shown]
    assert any(art_ok(t, body) for t in a) and any(art_ok(t, under) for t in a)
    g.tick(0.05, 12)  # A has left; copy B is flying
    b = [t for t in b_orbs(g) if t.calls["SetTexture"]]  # (Retro's trail squares have no art)
    assert b and all(art_ok(t, body) for t in b)
    assert [o.shape is None for o in flying(g)] == [shape == "starlight"] * len(
        flying(g)
    )


def test_a_pool_texture_never_keeps_another_shapes_coords(env):
    g = make(env)
    go(g, "retro", n=2, trail=False, advance=0.1)
    g.tick(
        0.05, 40
    )  # all gone; the textures return to the pool with their texcoord windows
    reused = [t for t in g.stub.frames.values() if t.kind == "Texture"]
    assert any(t.xoDirty for t in reused)
    go(g, "starlight", n=2, trail=False, advance=0.1)
    assert all(not t.xoDirty for t in reused if t.shown and path_of(t) == PRE + "orb")
    assert any(
        t.calls["SetTexCoord"]
        and tuple(t.calls["SetTexCoord"].values()) == (0, 1, 0, 1)
        for t in reused
    )


def test_calib_marker_keeps_the_orb_art():
    src = (ROOT / "Calib.lua").read_text(encoding="utf-8")
    assert "ns.Orbs.ORB_TEX" in src and "orbShape" not in src


# ---------------------------------------------------------------- the texture budget


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("trail", [True, False])
def test_each_shape_needs_its_texture_count(env, shape, trail):
    g = make(env)
    go(g, shape, n=4, trail=trail, advance=0.05)
    assert in_use(g) == 4 * NEED[shape][0 if trail else 1]


@pytest.mark.parametrize("shape", SHAPES)
def test_the_ceiling_fits_a_full_burst_of_every_shape(env, shape):
    g = make(env)
    set_shape(g, shape)
    g.db.trail = True
    cap = int(g.db.cap)
    ceiling = g.orbs.Info(g.orbs)[3]
    per_orb = max(6, NEED[shape][0])
    assert ceiling == cap * per_orb * 2 + 8
    count = cap
    fire(g, "stream", n=cap)
    assert in_use(g) == count * NEED[shape][0]  # a full burst keeps its trail
    fire(g, "stream", n=cap)  # room for a second full burst
    assert in_use(g) == 2 * count * NEED[shape][0] and in_use(g) <= ceiling - 1
    g.tick(0.05, 80)
    assert in_use(g) == 0


def test_starlights_ceiling_is_unchanged(env):
    g = make(env)
    assert g.orbs.Info(g.orbs)[3] == 40 * 6 * 2 + 8


def test_a_tight_pool_drops_the_trail_per_shapes_plain_need(env):
    g = make(env)
    set_shape(g, "bubble")
    g.db.trail = True
    g.db.cap = 10
    assert g.orbs.Info(g.orbs)[3] == 10 * 7 * 2 + 8  # 148, one slot of it the arrival flash's
    fire(g, "stream", n=10)  # 10 orbs, 7 textures each
    fire(g, "stream", n=10)
    assert in_use(g) == 140
    fire(g, "stream", n=10)  # 7 free: no room for 7 per orb, so the trail goes and 3 per orb fit
    assert in_use(g) == 146
    assert [o.ghost1 is None for o in flying(g)] == [False] * 20 + [True] * 2
    g.tick(0.05, 80)
    assert in_use(g) == 0


# ---------------------------------------------------------------- Bubble


def test_bubble_has_no_count_size_or_time_multiplier(env):
    g = make(env)
    set_shape(g, "bubble")
    g.db.flightTime = 1.0
    saved = {k: g.db[k] for k in ("size", "density", "flightTime", "cap")}
    shape = g.ns.OrbShapes.by.bubble
    assert shape.timeMul == 1
    n, n_purple, scale = shape.adjust(10, 4, 1.0)
    assert (n, n_purple, scale) == (10, 4, 1.0)
    fire(g, "stream", n=10, nPurple=4)
    recs = flying(g)
    assert len(recs) == 10 and sum(1 for o in recs if o.rested) == 4
    size = float(g.db.size)
    assert sorted({round(o.size, 6) for o in recs}) == pytest.approx(sorted({size, size * 1.15}))
    assert all(o.dur == pytest.approx(1.0) for o in recs)  # fixed random: jitter 1.0
    assert {k: g.db[k] for k in saved} == saved


@pytest.mark.parametrize("n", [1, 2, 3, 7, 40])
def test_bubble_draws_every_orb_asked_for(env, n):
    g = make(env)
    set_shape(g, "bubble")
    fire(g, "stream", n=n)
    assert len(flying(g)) == n


def test_bubble_default_size_draws_a_21_px_ball(env):
    g = make(env)
    g.ns.SetOrbShape("bubble")
    g.ns.SetLook("pulse", False)
    assert g.db.size == 14
    go(g, "bubble", n=1, trail=False, advance=0.3)
    (o,) = flying(g)
    assert o.body.width == pytest.approx(21)


def test_bubble_breathes_and_draws_at_one_and_a_half_times_the_size(env):
    g = make(env)
    g.ns.SetLook("pulse", True)  # Pulsing starts off
    go(g, "bubble", n=2, trail=False, advance=0.0)
    (o, _) = flying(g)[:2]
    sizes = []
    for _ in range(30):
        g.tick(0.02, 1)
        if o.body.width:  # (nothing is drawn during the start delay)
            sizes.append(o.body.width)
    base = o.size * 1.5
    assert min(sizes) < base < max(sizes)
    assert all(base * 0.94 - 1e-6 <= s <= base * 1.06 + 1e-6 for s in sizes)  # +-6 %
    assert o.under.width == pytest.approx(o.body.width)  # the dark disc is the body's size


def test_pulse_off_keeps_the_bubble_at_a_constant_size(env):
    g = make(env)
    g.ns.SetOrbShape("bubble")
    g.ns.SetLook("pulse", False)
    go(g, "bubble", n=1, trail=False, advance=0.0)
    (o,) = flying(g)
    sizes = []
    for _ in range(30):
        g.tick(0.02, 1)
        if o.body.width:
            sizes.append(o.body.width)
    assert len(sizes) > 10 and all(s == pytest.approx(o.size * 1.5) for s in sizes)
    g.db.pulse = True  # an orb already flying keeps the look it was set up with (a shape switch changes db.pulse)
    g.tick(0.02, 12)
    assert o.body.width == pytest.approx(o.size * 1.5)
    g.tick(5)  # the burst lands; the next one is set up with pulsing on and breathes
    go(g, "bubble", n=1, trail=False, advance=0.0)
    (o,) = flying(g)
    sizes = set()
    for _ in range(12):
        g.tick(0.02, 1)
        if o.body.width:
            sizes.add(round(float(o.body.width), 3))
    assert len(sizes) > 3


def test_retro_sparkle_is_fixed_when_the_orb_is_set_up(env):
    g = make(env)
    g.db.sparkle = False
    go(g, "retro", n=1, trail=False, advance=0.05)
    (o,) = flying(g)
    g.db.sparkle = True  # e.g. the shape was switched mid-flight: this orb is not affected
    for _ in range(14):
        g.tick(0.05, 1)
        assert not o.spark.shown


def test_bubble_glint_sits_up_and_left_and_breathes_with_the_body(env):
    g = make(env)
    go(g, "bubble", n=1, trail=False, advance=0.3)
    (o,) = flying(g)
    for _ in range(6):
        g.tick(0.03, 1)
        body = o.body.width
        spark = o.spark
        assert path_of(spark) == PRE + "bubble_glint" and spark.shown
        assert spark.width == pytest.approx(0.30 * body)
        assert spark.points[1][4] - o.body.points[1][4] == pytest.approx(-0.20 * body)
        assert spark.points[1][5] - o.body.points[1][5] == pytest.approx(0.20 * body)
        assert spark.alpha == pytest.approx(0.55 * o.body.alpha)
    assert str(spark.calls["SetBlendMode"][1]) == "ADD"
    colour = [float(g.db.color[i]) for i in (1, 2, 3)]
    tint = [float(v) for v in spark.calls["SetVertexColor"].values()][:3]
    assert tint == pytest.approx([c + (1 - c) * 0.75 for c in colour])


def test_bubble_pop_has_the_glint_too(env):
    g = make(env)
    go(g, "bubble", style="popstream", n=1, advance=0.2)
    under, body, glint = pop_textures(g)[:3]
    assert path_of(glint) == PRE + "bubble_glint" and glint.shown
    assert glint.points[1][4] - body.points[1][4] == pytest.approx(-0.20 * body.width)
    assert glint.points[1][5] - body.points[1][5] == pytest.approx(0.20 * body.width)


def test_bubble_trail_has_four_ghosts_fainter_and_smaller(env):
    g = make(env)
    go(g, "bubble", n=2, trail=True, advance=0.45)
    (o, _) = flying(g)[:2]
    ghosts = [o.ghost1, o.ghost2, o.ghost3, o.ghost4]
    assert all(t.shown for t in ghosts)
    alphas = [t.alpha / o.body.alpha for t in ghosts]
    assert alphas == pytest.approx([0.52, 0.36, 0.22, 0.12], abs=1e-6)
    sizes = [t.width / o.body.width for t in ghosts]
    assert sizes == pytest.approx([0.87, 0.75, 0.65, 0.55], abs=1e-6)
    xs = [o.body.points[1][4]] + [t.points[1][4] for t in ghosts]
    ys = [o.body.points[1][5]] + [t.points[1][5] for t in ghosts]
    gaps = [math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(4)]
    assert all(5 < gap < 20 for gap in gaps)  # about 10 px apart on this flight


# ---------------------------------------------------------------- Retro


def snapped(value, cell):
    return abs(round(value / cell) * cell - value) < 1e-6


def test_retro_cell_size_and_grid(env):
    g = make(env, trail=True)
    go(g, "retro", n=3, advance=0.0)
    for _ in range(14):
        g.tick(0.05, 1)
        for o in flying(g):
            cell = o.cell
            if cell is None:  # still in its start delay
                continue
            assert cell >= 1
            assert o.body.width == pytest.approx(
                8 * cell
            ) and o.under.width == pytest.approx(10 * cell)
            for tex in (o.body, o.under):
                assert snapped(tex.points[1][4], cell) and snapped(
                    tex.points[1][5], cell
                )


def test_retro_default_size_is_two_px_cells_a_16_px_orb(env):
    g = make(env)
    go(g, "retro", n=1, trail=False, advance=0.1)
    (o,) = flying(g)
    assert o.cell == 2 and o.body.width == 16 and o.under.width == 20


def test_retro_cell_can_be_one_pixel(env):
    g = make(env)
    g.db.size = 1
    go(g, "retro", n=1, trail=False, advance=0.1)
    (o,) = flying(g)
    assert o.cell == 1 and o.body.width == 8


def test_retro_sparkle_off_never_shows_the_twinkle(env):
    g = make(env)
    g.db.sparkle = False
    go(g, "retro", n=1, trail=False, advance=0.05)
    (o,) = flying(g)
    for _ in range(14):
        g.tick(0.05, 1)
        assert not o.spark.shown


def test_retro_sparkle_on_blinks(env):
    g = make(env)
    g.db.sparkle = True
    go(g, "retro", n=1, trail=False, advance=0.05)
    (o,) = flying(g)
    states = set()
    for _ in range(14):
        g.tick(0.05, 1)
        states.add(bool(o.spark.shown))
    assert states == {True, False}


def test_retro_twinkle_is_three_cells_on_the_top_left_and_blinks(env):
    g = make(env)
    go(g, "retro", n=1, trail=False, advance=0.05)
    (o,) = flying(g)
    states, sizes = [], []
    for _ in range(18):
        g.tick(0.05, 1)
        spark = o.spark
        states.append(bool(spark.shown))
        if spark.shown:
            cell = o.cell
            sizes.append(spark.width)
            bx, by = o.body.points[1][4], o.body.points[1][5]
            assert spark.points[1][4] == pytest.approx(bx - 2.5 * cell)
            assert spark.points[1][5] == pytest.approx(by + 2.5 * cell)
    assert set(states) == {True, False} and set(sizes) == {3 * o.cell}
    runs = re.findall(r"T+|F+", "".join("T" if s else "F" for s in states))
    assert all(
        len(r) in (4, 5, 6) for r in runs[1:-1]
    )  # 0.25 s on, 0.25 s off in 0.05 s ticks


def test_retro_twinkle_art_is_cropped_with_texcoords(env):
    g = make(env)
    go(g, "retro", n=1, trail=False, advance=0.05)
    (o,) = flying(g)
    assert tuple(o.spark.calls["SetTexCoord"].values()) == (0, 0.75, 0, 0.75)
    assert tuple(o.under.calls["SetTexCoord"].values()) == (0, 0.625, 0, 0.625)
    assert "SetTexCoord" not in (o.body.calls or {})
    assert (
        str(o.body.calls["SetTexture"][4]) == "NEAREST"
        and str(o.under.calls["SetTexture"][4]) == "NEAREST"
    )
    assert "SetRotation" not in (o.body.calls or {}) and "SetRotation" not in (
        o.spark.calls or {}
    )


def test_retro_trail_is_two_squares_on_the_grid(env):
    g = make(env, trail=True)
    go(g, "retro", n=1, advance=0.5)
    (o,) = flying(g)
    cell = o.cell
    big, small = o.ghost1, o.ghost2
    assert big.shown and small.shown
    assert big.width == 2 * cell and small.width == cell
    assert big.alpha / o.body.alpha == pytest.approx(
        0.70
    ) and small.alpha / o.body.alpha == pytest.approx(0.40)
    assert snapped(big.points[1][4], cell) and snapped(
        big.points[1][5], cell
    )  # even: centred on a grid line
    assert snapped(small.points[1][4] - cell / 2, cell)  # odd: centred in a cell
    assert (
        str(big.calls["SetBlendMode"][1]) == "ADD"
        and str(small.calls["SetBlendMode"][1]) == "ADD"
    )
    bx, by = o.body.points[1][4], o.body.points[1][5]
    d_big = math.hypot(big.points[1][4] - bx, big.points[1][5] - by) / cell
    d_small = math.hypot(small.points[1][4] - bx, small.points[1][5] - by) / cell
    assert 5 <= d_big <= 7.5 and 8 <= d_small <= 10.5  # about 6 and 9 cells behind (the big one touches the rim)
    assert tuple(big.calls["SetColorTexture"].values())[:3] == pytest.approx(
        tuple(g.db.color.values())[:3], abs=1
    )


def test_retro_without_trail_has_no_squares(env):
    g = make(env)
    go(g, "retro", n=2, trail=False, advance=0.3)
    assert all(o.ghost1 is None and o.ghost2 is None for o in flying(g))
    assert in_use(g) == 6


def test_retro_pops_are_snapped_too(env):
    g = make(env)
    go(g, "retro", style="popstream", n=2, advance=0.3)
    slots = pop_textures(g)
    assert slots
    for i in range(0, len(slots), 3):
        under, body = slots[i], slots[i + 1]
        cell = body.width / 8
        assert (
            cell >= 2
            and snapped(body.points[1][4], cell)
            and snapped(body.points[1][5], cell)
        )
        assert under.width == pytest.approx(10 * cell)
        assert "SetRotation" not in (body.calls or {})


def test_retro_falls_back_to_the_plain_filter_and_logs_once(env):
    g = make(env)
    g.env.lua.execute(
        """
        local fm = getmetatable(UIParent).__index
        local base = fm.SetTexture
        function fm:SetTexture(path, a, b, filter)
            if filter ~= nil then error("no filter argument") end
            return base(self, path)
        end
        """
    )
    go(g, "retro", n=3, trail=False, advance=0.1)
    for o in flying(g):
        assert path_of(o.body) == PRE + "retro" and len(o.body.calls["SetTexture"]) == 1
    assert g.ns.OrbShapes.nearestOk() is False
    assert sum("SHAPE nearest filter" in line for line in g.log()) == 1


def test_retro_logs_that_nearest_worked_once(env):
    g = make(env)
    go(g, "retro", n=3, trail=False, advance=0.1)
    assert g.ns.OrbShapes.nearestOk() is True
    assert sum("SHAPE nearest filter ok" in line for line in g.log()) == 1


# ---------------------------------------------------------------- Crackle


def collect_ticks(g, until=1.2, dt=0.004):
    (o,) = flying(g)
    changes, last = [], None
    t0 = g.stub.time
    while g.stub.time - t0 < until and o.spark is not None:
        g.tick(dt, 1)
        if o.spark is None:
            break
        key = (path_of(o.spark), o.spark.calls["SetRotation"][1])
        if key != last:
            if last is not None:
                changes.append(
                    (
                        g.stub.time,
                        BOLTS.index(key[0]),
                        key[1],
                        o.spark.alpha / o.body.alpha,
                    )
                )
            last = key
    return changes


def test_crackle_bolt_ticks_every_70_to_90_ms_and_never_repeats_a_frame(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    go(g, "crackle", n=1, trail=False, advance=0.2)
    changes = collect_ticks(g)
    assert len(changes) >= 6
    gaps = [b[0] - a[0] for a, b in pairwise(changes)]
    assert all(0.07 - 1e-6 <= gap <= 0.09 + 0.004 + 1e-6 for gap in gaps), gaps
    frames = [c[1] for c in changes]
    assert all(a != b for a, b in pairwise(frames))
    assert len(set(frames)) >= 3


def test_crackle_bolt_turns_at_least_60_degrees_and_varies_in_brightness(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    go(g, "crackle", n=1, trail=False, advance=0.2)
    changes = collect_ticks(g)
    turns = [(b[2] - a[2]) % TWO_PI for a, b in pairwise(changes)]
    assert all(min(t, TWO_PI - t) >= math.pi / 3 - 1e-6 for t in turns), turns
    alphas = [c[3] for c in changes]
    assert (
        all(0.7 - 1e-6 <= a <= 1.0 + 1e-6 for a in alphas)
        and max(alphas) - min(alphas) > 0.05
    )


def test_crackle_core_is_steady_and_sized_from_the_body(env):
    g = make(env, trail=True)
    go(g, "crackle", n=1, advance=0.0)
    (o,) = flying(g)
    ratios = []
    for _ in range(10):
        g.tick(0.03, 1)
        body = o.size * 2.0
        if o.body.alpha == 1:  # after the fade-in
            ratios.append(
                (o.body.width / body, o.spark.width / body, o.under.width / body)
            )
    assert ratios
    for core, bolt, under in ratios:
        assert core == pytest.approx(1.15, rel=0.02) and bolt == pytest.approx(
            1.30, rel=0.02
        )
        assert under == pytest.approx(1.6, rel=0.02)
    assert (
        str(o.under.calls["SetBlendMode"][1]) == "BLEND"
        and str(o.spark.calls["SetBlendMode"][1]) == "ADD"
    )


def test_crackle_ghosts_follow_the_starlight_rules(env):
    g = make(env, trail=True)
    go(g, "crackle", n=1, advance=0.5)
    (o,) = flying(g)
    assert o.ghost1.alpha / o.body.alpha == pytest.approx(
        0.55
    ) and o.ghost2.alpha / o.body.alpha == pytest.approx(0.30)
    assert o.ghost1.width / o.body.width == pytest.approx(0.85 / 1.15)


def test_crackle_pop_bolts_tick_too(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    go(g, "crackle", style="popstream", n=1, advance=0.0)
    seen = set()
    for _ in range(60):
        g.tick(0.005, 1)
        slots = pop_textures(g)
        if slots:
            seen.add(path_of(slots[2]))
    assert len(seen) >= 2 and seen <= set(BOLTS)


# ---------------------------------------------------------------- snapshot per burst


@pytest.mark.parametrize(
    "first, second", [("starlight", "retro"), ("bubble", "crackle"), ("crackle", "starlight")]
)
def test_the_shape_is_fixed_for_the_burst(env, first, second):
    g = make(env, trail=True)
    go(g, first, n=2, advance=0.1)
    before = [(path_of(o.under), path_of(o.body), o.shape is None) for o in flying(g)]
    set_shape(g, second)  # changed mid-flight
    g.tick(0.05, 4)
    assert [
        (path_of(o.under), path_of(o.body), o.shape is None) for o in flying(g)
    ] == before
    fire(g, "stream", n=2)  # the next burst takes the new shape
    new = [o for o in flying(g) if path_of(o.body) == ART[second][1]]
    assert new


def test_the_shape_is_fixed_for_a_pop_and_a_crossfade(env):
    g = make(env, trail=True)
    go(g, "retro", style="popstream", n=2, advance=0.1)
    set_shape(g, "crackle")
    g.tick(0.05, 4)
    assert all(
        path_of(t) in (ART["retro"][0], ART["retro"][1], ART["retro"][2])
        for t in pop_textures(g)
    )
    g.tick(0.05, 40)
    go(g, "starlight", style="crossfade", n=2, advance=0.1)
    set_shape(g, "bubble")
    g.tick(0.05, 3)
    shown = [t for t in a_orbs(g)]
    assert shown and all(path_of(t) == PRE + "orb" for t in shown)
    g.tick(0.05, 30)
    assert all(path_of(t) == PRE + "orb" for t in b_orbs(g))


def test_a_recycled_record_never_keeps_the_old_shape(env):
    g = make(env, trail=True)
    go(g, "bubble", n=2, advance=0.1)
    g.tick(0.05, 60)
    go(g, "starlight", n=2, advance=0.1)
    for o in flying(g):
        assert o.shape is None and o.ghost4 is None and o.spark is not None


# ---------------------------------------------------------------- Test burst, portrait bursts, textures all returned


@pytest.mark.parametrize("shape", ["retro", "bubble", "crackle"])
def test_the_test_burst_uses_the_shape(env, shape):
    g = make(env, trail=True)
    set_shape(g, shape)
    g.slash("test 5")
    g.tick(0.05, 6)
    arts = {
        path_of(t)
        for t in g.stub.frames.values()
        if t.kind == "Texture" and t.shown and t.calls and t.calls["SetTexture"]
    }
    assert ART[shape][1] in arts


@pytest.mark.parametrize("shape", SHAPES)
def test_everything_returns_to_the_pool(env, shape):
    g = make(env, trail=True)
    set_shape(g, shape)
    for style in ("stream", "popstream", "crossfade"):
        fire(g, style, n=6)
        g.tick(0.05, 60)
    assert in_use(g) == 0 and g.stub.shownTextures() == 0


# ---------------------------------------------------------------- media


def read_tga(path):
    """(width, height, rows) with rows[0] the visual top row, each row a list of (r, g, b, a)."""
    data = path.read_bytes()
    id_len, cmap, kind = data[0], data[1], data[2]
    width, height = struct.unpack("<HH", data[12:16])
    bpp, desc = data[16], data[17]
    assert (cmap, kind, bpp) == (0, 2, 32)
    start = 18 + id_len
    rows = []
    for r in range(height):
        raw = data[start + r * width * 4 : start + (r + 1) * width * 4]
        rows.append(
            [
                (raw[c * 4 + 2], raw[c * 4 + 1], raw[c * 4], raw[c * 4 + 3])
                for c in range(width)
            ]
        )
    if not desc & 0x20:  # bottom-left origin: the first stored row is the bottom one
        rows.reverse()
    return width, height, rows


def alpha_at(rows, x, y):
    return rows[y][x][3]


def lua_media_names():
    names = set()
    for path in ROOT.glob("*.lua"):
        names |= set(
            re.findall(r'media\\\\([A-Za-z0-9_\-]+)"', path.read_text(encoding="utf-8"))
        )
    return names


def test_every_media_texture_the_lua_names_exists():
    names = lua_media_names()
    assert {
        "orb",
        "sparkle",
        "retro",
        "retro_under",
        "retro_twinkle",
        "bubble",
        "bubble_under",
        "bubble_glint",
        "crackle_core",
    } <= names
    assert {f"bolt{i}" for i in range(1, 5)} <= names
    for name in names:
        assert (MEDIA / f"{name}.tga").is_file(), name


NEW = [
    "retro",
    "retro_under",
    "retro_twinkle",
    "bubble",
    "bubble_under",
    "bubble_glint",
    "crackle_core",
    "bolt1",
    "bolt2",
    "bolt3",
    "bolt4",
]


@pytest.mark.parametrize("name", NEW)
def test_new_textures_are_power_of_two(name):
    width, height, _ = read_tga(MEDIA / f"{name}.tga")
    assert width & (width - 1) == 0 and height & (height - 1) == 0, (width, height)


def test_retro_art_sits_in_the_top_left_corner_of_its_texture():
    w, h, rows = read_tga(MEDIA / "retro_under.tga")
    assert (w, h) == (128, 128)
    lit = [(x, y) for y in range(h) for x in range(w) if alpha_at(rows, x, y)]
    assert (
        max(x for x, _ in lit) == 79
        and max(y for _, y in lit) == 79
        and min(x for x, _ in lit) == 0
    )
    assert (
        alpha_at(rows, 40, 40) == 255
        and alpha_at(rows, 100, 100) == 0
        and alpha_at(rows, 100, 10) == 0
    )
    assert alpha_at(rows, 10, 100) == 0
    assert (
        alpha_at(rows, 0, 0) == 0 and alpha_at(rows, 79, 79) == 0
    )  # the corners are cut
    w, h, rows = read_tga(MEDIA / "retro_twinkle.tga")
    assert (w, h) == (32, 32)
    assert (
        alpha_at(rows, 12, 12) == 255
        and alpha_at(rows, 12, 4) == 140
        and alpha_at(rows, 4, 4) == 0
    )
    assert all(
        alpha_at(rows, x, y) == 0
        for y in range(32)
        for x in range(32)
        if x >= 24 or y >= 24
    )


def test_retro_octagon_has_the_specified_alphas():
    w, h, rows = read_tga(MEDIA / "retro.tga")
    assert (w, h) == (64, 64)
    assert alpha_at(rows, 2, 2) == 0 and alpha_at(rows, 61, 61) == 0  # cut corners
    def cell(c, r):
        return alpha_at(rows, c * 8 + 4, r * 8 + 4)

    assert cell(2, 2) == cell(3, 2) == 255  # shine
    assert cell(4, 4) == round(0.80 * 255) and cell(0, 3) == round(0.35 * 255)
    assert cell(1, 3) == round(0.60 * 255)
    assert cell(2, 0) == round(0.35 * 255)


@pytest.mark.parametrize("name", ["bolt1", "bolt2", "bolt3", "bolt4"])
def test_bolts_stay_inside_the_texture_and_leave_the_centre_clear(name):
    w, h, rows = read_tga(MEDIA / f"{name}.tga")
    assert (w, h) == (64, 64)
    outside = max(
        alpha_at(rows, x, y)
        for y in range(h)
        for x in range(w)
        if math.hypot((x + 0.5) / w * 2 - 1, (y + 0.5) / h * 2 - 1) >= 0.92
    )
    centre = max(
        alpha_at(rows, x, y)
        for y in range(h)
        for x in range(w)
        if math.hypot((x + 0.5) / w * 2 - 1, (y + 0.5) / h * 2 - 1) < 0.2
    )
    assert outside <= 2 and centre <= 8  # nothing radiates from the middle
    assert sum(1 for row in rows for px in row if px[3] > 128) > 100


def test_the_generators_keep_the_original_textures_byte_identical():
    import subprocess

    for name in (
        "orb",
        "sparkle",
        "flash",
        "flash_v",
        "retro",
        "retro_under",
        "retro_twinkle",
    ):
        committed = subprocess.run(
            ["git", "show", f"HEAD:media/{name}.tga"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        assert (MEDIA / f"{name}.tga").read_bytes() == committed, name



def test_bubble_glint_is_a_soft_blob_that_fades_well_inside_the_quad():
    w, h, rows = read_tga(MEDIA / "bubble_glint.tga")
    assert (w, h) == (64, 64)
    assert alpha_at(rows, 31, 31) == 255 and alpha_at(rows, 32, 32) == 255  # peak alpha 1.0 in the middle
    ring = [
        alpha_at(rows, x, y)
        for y in range(h)
        for x in range(w)
        if math.hypot((x + 0.5) / 32 - 1, (y + 0.5) / 32 - 1) > 0.95
    ]
    assert max(ring) == 0 and alpha_at(rows, 0, 0) == 0
    # slightly elongated (along the diagonal running up and to the right), smooth with no hard edge
    assert alpha_at(rows, 40, 24) > alpha_at(rows, 40, 40)
    steps = [alpha_at(rows, 32 + i, 32) for i in range(0, 30)]
    assert all(a >= b for a, b in pairwise(steps)) and max(a - b for a, b in pairwise(steps)) < 60


def test_the_crackle_core_is_fuller_with_a_clear_edge():
    w, h, rows = read_tga(MEDIA / "crackle_core.tga")
    assert (w, h) == (64, 64)
    assert alpha_at(rows, 32, 32) == 255
    assert alpha_at(rows, round(32 + 0.4 * 32), 32) >= 64  # the halo reaches further than the old 0.55 / 0.62
    assert alpha_at(rows, round(32 + 0.72 * 32), 32) == 0  # and ends at 0.70


@pytest.mark.parametrize("name", ["bolt1", "bolt2", "bolt3", "bolt4"])
def test_the_bolts_hug_the_cores_rim(name):
    w, h, rows = read_tga(MEDIA / f"{name}.tga")
    radii = [
        math.hypot((x + 0.5) / 32 - 1, (y + 0.5) / 32 - 1)
        for y in range(h)
        for x in range(w)
        if alpha_at(rows, x, y) > 128
    ]
    assert 0.40 <= sum(radii) / len(radii) <= 0.55  # arcs at 0.40-0.50 of the half quad (was 0.44-0.58)
    assert max(radii) < 0.75  # the spike is shorter too


# ---------------------------------------------------------------- Solid blend (Retro, Bubble, Crackle)

SOLID_ART = {
    "retro": PRE + "retro_solid",
    "bubble": PRE + "bubble_solid",
    "crackle": PRE + "crackle_core_solid",
}
SOLID_LIFT = 0.06


def mode_of(tex):
    return str(tex.calls["SetBlendMode"][1])


def layer_of(tex):
    return int(tex.calls["SetDrawLayer"][2])


def tint_of(tex):
    return [float(v) for v in tex.calls["SetVertexColor"].values()][:3]


def ghosts_of(o):
    return [o[k] for k in ("ghost1", "ghost2", "ghost3", "ghost4") if o[k] is not None]


def solid_burst(g, shape, blend, **kw):
    g.db.blend = blend
    kw.setdefault("n", 2)
    go(g, shape, trail=True, advance=0.25, **kw)
    recs = flying(g)
    assert recs
    return recs


@pytest.mark.parametrize("shape", ["retro", "bubble", "crackle"])
def test_solid_body_is_the_solid_texture_blended_in_a_lifted_colour(env, shape):
    g = make(env)
    for o in solid_burst(g, shape, "solid"):
        assert path_of(o.body) == SOLID_ART[shape]
        assert mode_of(o.body) == "BLEND" and layer_of(o.body) == 0
        colour = [float(g.db.color[i]) for i in (1, 2, 3)]
        rested = [float(g.db.restedColor[i]) for i in (1, 2, 3)]
        want = rested if o.rested else colour
        lift = 0.0 if shape == "retro" else SOLID_LIFT  # Retro's Solid is cut for the plain orb colour
        assert tint_of(o.body) == pytest.approx([c + (1 - c) * lift for c in want])


@pytest.mark.parametrize("shape", ["retro", "bubble", "crackle"])
def test_solid_layers_underlay_minus_two_trail_minus_one_top_plus_one(env, shape):
    g = make(env)
    for o in solid_burst(g, shape, "solid"):
        assert layer_of(o.under) == -2 and mode_of(o.under) == "BLEND"
        assert layer_of(o.spark) == 1 and mode_of(o.spark) == "ADD"
        ghosts = ghosts_of(o)
        assert len(ghosts) == {"retro": 2, "bubble": 4, "crackle": 3}[shape]
        assert all(layer_of(t) == -1 and mode_of(t) == "ADD" for t in ghosts)


@pytest.mark.parametrize("shape", ["retro", "bubble", "crackle"])
def test_natural_keeps_todays_sublayers_and_modes(env, shape):
    g = make(env)
    for o in solid_burst(g, shape, "natural"):
        assert path_of(o.body) == ART[shape][1]
        assert (mode_of(o.under), layer_of(o.under)) == ("BLEND", -1)
        assert (mode_of(o.body), layer_of(o.body)) == ("ADD", 0)
        assert (mode_of(o.spark), layer_of(o.spark)) == ("ADD", 1)
        assert all((mode_of(t), layer_of(t)) == ("ADD", 0) for t in ghosts_of(o))
        colour = [float(g.db.color[i]) for i in (1, 2, 3)]
        if not o.rested:
            assert tint_of(o.body) == pytest.approx(colour)


def test_solid_retro_body_keeps_the_nearest_filter_and_the_twinkle_obeys_sparkle(env):
    g = make(env)
    g.db.sparkle = False
    (o, *_) = solid_burst(g, "retro", "solid", n=1)
    assert tuple(o.body.calls["SetTexture"].values())[-1] == "NEAREST"
    for _ in range(14):
        g.tick(0.05, 1)
        assert not o.spark.shown


def test_solid_crackle_underlay_is_lighter_and_tighter(env):
    g = make(env)
    for o in solid_burst(g, "crackle", "solid"):
        assert o.under.width == pytest.approx(1.25 * o.body.width / 1.15)
        assert o.under.alpha == pytest.approx(0.40 * o.body.alpha)
    g2 = make(env)
    for o in solid_burst(g2, "crackle", "natural"):
        assert o.under.width == pytest.approx(1.6 * o.body.width / 1.15)
        assert o.under.alpha == pytest.approx(0.58 * o.body.alpha)


def art_state(o):
    return [
        (path_of(t), mode_of(t), layer_of(t), tuple(round(v, 6) for v in tint_of(t)))
        for t in (o.under, o.body, o.spark, *ghosts_of(o))
    ]


def test_starlight_ignores_blend(env):
    states = []
    for blend in ("natural", "solid"):
        g = make(env)
        recs = solid_burst(g, "starlight", blend)
        states.append([art_state(o) for o in recs])
    assert len(states[0]) == len(states[1])
    assert all(a[:3] == b[:3] for a, b in zip(sorted(states[0]), sorted(states[1])))
    assert all(layer_of(o.body) == 0 for o in recs) and mode_of(recs[0].body) == "ADD"


def test_solid_pops_use_the_solid_art_too(env):
    g = make(env)
    g.db.blend = "solid"
    go(g, "bubble", style="popstream", n=1, advance=0.2)
    under, body, glint = pop_textures(g)[:3]
    assert path_of(body) == SOLID_ART["bubble"] and mode_of(body) == "BLEND"
    assert layer_of(under) == -2 and layer_of(glint) == 1


def test_a_solid_orb_leaves_nothing_behind_in_the_pool(env):
    """Pool textures from a Solid Retro orb come back to a Starlight orb, then a Natural Retro orb, fully restyled."""
    g = make(env)
    solid_burst(g, "retro", "solid", n=3)
    for _ in range(80):  # let the burst land and release its textures
        g.tick(0.05, 1)
    g.db.blend = "solid"  # Starlight ignores it
    go(g, "starlight", n=3, trail=True, advance=0.25)
    star = flying(g)
    assert star
    for o in star:
        assert (path_of(o.under), mode_of(o.under), layer_of(o.under)) == (PRE + "orb", "BLEND", -1)
        assert (path_of(o.body), mode_of(o.body), layer_of(o.body)) == (PRE + "orb", "ADD", 0)
        assert (path_of(o.spark), mode_of(o.spark), layer_of(o.spark)) == (PRE + "sparkle", "ADD", 1)
        assert all((path_of(t), mode_of(t), layer_of(t)) == (PRE + "orb", "ADD", 0) for t in ghosts_of(o))
        assert "NEAREST" not in tuple(o.body.calls["SetTexture"].values())  # the filter went with the Retro art
    for _ in range(80):
        g.tick(0.05, 1)
    g.db.blend = "natural"
    go(g, "retro", n=3, trail=True, advance=0.25)
    for o in flying(g):
        assert (path_of(o.body), mode_of(o.body), layer_of(o.body)) == (PRE + "retro", "ADD", 0)
        assert layer_of(o.under) == -1 and all(layer_of(t) == 0 for t in ghosts_of(o))
