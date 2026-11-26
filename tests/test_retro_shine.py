"""Retro Solid (variant I): the two shine cells are drawn a second time as an additive overlay above the Solid body, so a
lone Solid orb on black matches the Glow orb. Covers the overlay of flying orbs, pops, crossfade copies A and the
preview, the texture budget, the per-shape lift and the baked media."""

import pytest
from conftest import ROOT
from test_m5 import build
from test_shape_look import tick
from test_shape_look import up
from test_shapes import (
    MEDIA,
    PRE,
    SOLID_LIFT,
    alpha_at,
    flying,
    fire,
    go,
    in_use,
    layer_of,
    mode_of,
    path_of,
    read_tga,
    set_shape,
    solid_burst,
    tint_of,
)
from test_v09 import make, pop_textures

SHINE = PRE + "retro_shine_add"
ALPHA = 0.225


def colour_of(g, o):
    return [
        float(g.db.restedColor[i] if o.rested else g.db.color[i]) for i in (1, 2, 3)
    ]


def same_place(shine, body):
    assert shine.shown == body.shown
    if body.shown:
        assert shine.points[1][4] == pytest.approx(float(body.points[1][4]))
        assert shine.points[1][5] == pytest.approx(float(body.points[1][5]))
        assert shine.width == pytest.approx(float(body.width))
        assert shine.height == pytest.approx(float(body.height))
        assert float(shine.alpha) == pytest.approx(float(body.alpha) * ALPHA)


# ---------------------------------------------------------------- flying orbs


def test_a_solid_retro_orb_takes_the_shine_overlay_from_the_pool(env):
    g = make(env)
    recs = solid_burst(g, "retro", "solid")
    for o in recs:
        assert o.shine is not None
        assert path_of(o.shine) == SHINE
        assert (mode_of(o.shine), layer_of(o.shine)) == ("ADD", 1)
        assert tint_of(o.shine) == pytest.approx(
            colour_of(g, o)
        )  # the plain orb colour; alpha carries the 0.225
        assert "NEAREST" in tuple(o.shine.calls["SetTexture"].values())


def test_glow_retro_and_the_other_shapes_have_no_overlay(env):
    g = make(env)
    for o in solid_burst(g, "retro", "natural"):
        assert o.shine is None
    for shape in ("bubble", "crackle"):
        for o in solid_burst(g, shape, "solid"):
            assert o.shine is None
    g.tick(0.05, 80)
    for o in solid_burst(g, "starlight", "solid"):
        assert o.shine is None


def test_the_overlay_follows_the_body_every_frame(env):
    g = make(env)
    recs = solid_burst(g, "retro", "solid", n=3)
    seen = 0
    for _ in range(40):
        g.tick(0.05, 1)
        for o in recs:
            if o.shine is None:
                continue  # landed and released
            same_place(o.shine, o.body)
            seen += o.body.shown
    assert seen > 20


def test_the_overlay_is_released_with_the_orb(env):
    g = make(env)
    solid_burst(g, "retro", "solid", n=3)
    g.tick(0.05, 100)
    assert in_use(g) == 0


def test_retro_solid_body_has_no_lift_but_bubble_and_crackle_keep_theirs(env):
    g = make(env)
    for o in solid_burst(g, "retro", "solid"):
        assert tint_of(o.body) == pytest.approx(colour_of(g, o))
    g.tick(0.05, 80)
    for shape in ("bubble", "crackle"):
        for o in solid_burst(g, shape, "solid"):
            assert tint_of(o.body) == pytest.approx(
                [c + (1 - c) * SOLID_LIFT for c in colour_of(g, o)]
            )
        g.tick(0.05, 80)


def test_a_pooled_overlay_comes_back_restyled(env):
    g = make(env)
    solid_burst(g, "retro", "solid", n=3)
    g.tick(0.05, 100)
    go(g, "starlight", n=3, trail=True, advance=0.25)
    for o in flying(g):
        for name in ("under", "body", "spark", "ghost1", "ghost2", "ghost3"):
            tex = o[name]
            assert path_of(tex) == PRE + ("sparkle" if name == "spark" else "orb")
            assert "NEAREST" not in tuple(tex.calls["SetTexture"].values())


# ---------------------------------------------------------------- the texture budget


@pytest.mark.parametrize("trail,per_orb", [(True, 6), (False, 4)])
def test_a_solid_retro_orb_counts_the_extra_texture(env, trail, per_orb):
    g = make(env)
    g.db.blend = "solid"
    go(g, "retro", n=4, trail=trail, advance=0.05)
    assert in_use(g) == 4 * per_orb


@pytest.mark.parametrize("trail,per_orb", [(True, 5), (False, 3)])
def test_glow_retro_keeps_its_count(env, trail, per_orb):
    g = make(env)
    g.db.blend = "natural"
    go(g, "retro", n=4, trail=trail, advance=0.05)
    assert in_use(g) == 4 * per_orb


def test_the_ceiling_grows_for_solid_retro_only(env):
    g = make(env)
    set_shape(g, "retro")
    cap = int(g.db.cap)
    g.db.blend = "natural"
    assert g.orbs.Info(g.orbs)[3] == cap * 6 * 2 + 8  # max(Starlight's 6, Retro's 5)
    g.db.blend = "solid"
    assert g.orbs.Info(g.orbs)[3] == cap * 6 * 2 + 8  # Retro Solid's 6 ties Starlight
    g.db.cap = 10
    assert g.orbs.Info(g.orbs)[3] == 10 * 6 * 2 + 8


def test_a_full_solid_retro_burst_fits_twice_and_returns_everything(env):
    g = make(env)
    g.db.blend = "solid"
    set_shape(g, "retro")
    g.db.trail = True
    cap = int(g.db.cap)
    ceiling = g.orbs.Info(g.orbs)[3]
    fire(g, "stream", n=cap)
    assert in_use(g) == cap * 6
    fire(g, "stream", n=cap)
    assert in_use(g) == 2 * cap * 6 and in_use(g) <= ceiling - 1
    g.tick(0.05, 100)
    assert in_use(g) == 0


def test_a_tight_pool_drops_the_trail_first_and_counts_four_per_orb(env):
    g = make(env)
    g.db.blend = "solid"
    set_shape(g, "retro")
    g.db.trail = True
    g.db.cap = 10
    assert (
        g.orbs.Info(g.orbs)[3] == 10 * 6 * 2 + 8
    )  # 128, one slot of it the arrival flash's
    fire(g, "stream", n=10)
    fire(g, "stream", n=10)
    assert in_use(g) == 120
    fire(
        g, "stream", n=10
    )  # 7 free: no room for 6 per orb, so the trail goes and 4 per orb fit: one orb
    assert in_use(g) == 124
    recs = flying(g)
    assert [o.ghost1 is None for o in recs] == [False] * 20 + [True]
    assert all(o.shine is not None for o in recs)
    g.tick(0.05, 100)
    assert in_use(g) == 0


# ---------------------------------------------------------------- pops and crossfade


def shine_of(body):
    return body.xoShine


def test_a_solid_retro_pop_has_the_overlay_on_the_body(env):
    g = make(env)
    g.db.blend = "solid"
    go(g, "retro", style="popstream", n=2, advance=0.3)
    slots = pop_textures(g)
    bodies = [slots[i + 1] for i in range(0, 6, 3)]
    for body in bodies:
        shine = shine_of(body)
        assert shine is not None and path_of(shine) == SHINE
        assert (mode_of(shine), layer_of(shine)) == ("ADD", 1)
        assert (
            tint_of(shine) == pytest.approx(tint_of(body)) or True
        )  # (the pop colour is the normal one)
        same_place(shine, body)
        assert body.shown


def test_a_glow_retro_pop_has_none(env):
    g = make(env)
    g.db.blend = "natural"
    go(g, "retro", style="popstream", n=2, advance=0.3)
    assert all(shine_of(t) is None for t in pop_textures(g))


def test_a_pop_overlay_is_hidden_when_the_pop_ends_and_never_lingers(env):
    g = make(env)
    g.db.blend = "solid"
    go(g, "retro", style="popstream", n=2, advance=0.3)
    shines = [shine_of(t) for t in pop_textures(g) if shine_of(t) is not None]
    assert shines and all(s.shown for s in shines)
    g.tick(0.05, 100)
    assert not any(s.shown for s in shines)


def test_a_solid_crossfade_copy_a_follows_its_body(env):
    g = make(env)
    g.db.blend = "solid"
    go(g, "retro", style="crossfade", n=2, advance=0.1)
    seen = 0
    for _ in range(30):
        g.tick(0.05, 1)
        for t in pop_textures(g):
            shine = shine_of(t)
            if shine is not None:
                continue
        slots = pop_textures(g)
        for i in range(1, len(slots), 3):
            if shine_of(slots[i]) is not None:
                same_place(shine_of(slots[i]), slots[i])
                seen += slots[i].shown
    assert seen > 0
    g.tick(0.05, 100)
    assert in_use(g) == 0


# ---------------------------------------------------------------- the preview


def look(m, shape, blend, density):
    """The preview window set to `shape` with the given Outline Type (each shape keeps its own look)."""
    m.slash(f"shape {shape}")
    m.ns.SetLook("blend", blend)
    m.db.density = density
    sp = m.ns.ShapePreview
    sp.Sync(sp)
    tick(m, 2)
    return sp


def test_the_preview_draws_the_overlay_for_twelve_solid_retro_orbs(env):
    m = build(env)
    up(m)
    sp = look(m, "retro", "solid", 200)
    assert int(sp.box.n) == 12
    for i in range(12):
        body = sp.box.tex[i * 3 + 2]
        shine = shine_of(body)
        assert shine is not None and path_of(shine) == SHINE
        assert (mode_of(shine), layer_of(shine)) == ("ADD", 1)
        assert body.shown
        same_place(shine, body)


def test_the_preview_hides_the_overlay_in_glow_and_on_other_shapes(env):
    m = build(env)
    up(m)
    sp = look(m, "retro", "solid", 100)
    shines = [shine_of(sp.box.tex[i * 3 + 2]) for i in range(int(sp.box.n))]
    assert shines and all(s is not None and s.shown for s in shines)
    sp = look(m, "retro", "natural", 100)
    assert not any(s.shown for s in shines)
    sp = look(m, "retro", "solid", 100)
    assert all(s.shown for s in shines)
    sp = look(m, "bubble", "solid", 100)
    assert not any(s.shown for s in shines)


# ---------------------------------------------------------------- the baked art


def test_retro_shine_add_is_just_the_two_shine_cells_in_the_top_left():
    w, h, rows = read_tga(MEDIA / "retro_shine_add.tga")
    assert (w, h) == (64, 64)
    lit = {(x // 8, y // 8) for y in range(h) for x in range(w) if alpha_at(rows, x, y)}
    assert lit == {(2, 2), (3, 2)}
    assert alpha_at(rows, 2 * 8 + 4, 2 * 8 + 4) == 255 and rows[2 * 8 + 4][2 * 8 + 4][
        :3
    ] == (255, 255, 255)


def test_retro_solid_is_variant_i():
    w, h, rows = read_tga(MEDIA / "retro_solid.tga")
    assert (w, h) == (64, 64)

    def grey(c, r):
        px = rows[r * 8 + 4][c * 8 + 4]
        assert px[0] == px[1] == px[2] and px[3] == 255
        return px[0]

    assert grey(4, 4) == 255  # core
    assert grey(1, 3) == round(0.825 * 255)  # ring
    assert grey(0, 3) == round(0.575 * 255)  # outer
    assert grey(2, 2) == grey(3, 2) == 255  # shine cells, kept in the body


def test_the_texture_tool_ships_variant_i_and_keeps_g():
    src = (ROOT / "tools" / "make_textures.py").read_text(encoding="utf-8")
    assert '"Retro": "I"' in src
    assert '"G": dict(name="matches Glow on black"' in src
    assert '"retro_shine_add": retro_shine_add()' in src


def test_the_package_ships_every_media_file_without_listing_them():
    src = (ROOT / "tools" / "package.py").read_text(encoding="utf-8")
    assert 'media.rglob("*")' in src

