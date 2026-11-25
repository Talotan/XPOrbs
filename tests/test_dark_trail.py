"""Dark orbs keep a trail: ghosts of a black or very dark orb are drawn BLEND (additive ghosts add nothing over black),
bright ones stay ADD. Decided per orb at spawn from the orb's own colour (normal or rested), every shape."""

import pytest
from test_shapes import SHAPES, flying, ghosts_of, go, in_use, mode_of
from test_v09 import make

BLACK = [0.0, 0.0, 0.0]
NAVY = [0.05, 0.05, 0.25]  # luminance 0.0415
PURPLE = [0.72, 0.28, 1.0]
LUM = (0.2126, 0.7152, 0.0722)


def set_colours(g, normal, rested=None):
    g.db.color = g.env.lua.table_from(normal)
    if rested is not None:
        g.db.restedColor = g.env.lua.table_from(rested)


def blends(o):
    return {mode_of(t) for t in ghosts_of(o)}


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize(
    ("colour", "want"), [(BLACK, "BLEND"), (NAVY, "BLEND"), (PURPLE, "ADD")]
)
def test_ghosts_follow_the_orb_colour(env, shape, colour, want):
    g = make(env, trail=True)
    set_colours(g, colour)
    go(g, shape)
    recs = flying(g)
    assert recs
    for o in recs:
        assert ghosts_of(o) and blends(o) == {want}


@pytest.mark.parametrize("shape", SHAPES)
def test_rested_colour_is_decided_apart_from_the_normal_one(env, shape):
    g = make(env, trail=True)
    set_colours(g, PURPLE, BLACK)
    go(g, shape, n=6, nPurple=2)
    recs = flying(g)
    assert sum(1 for o in recs if o.rested) == 2
    for o in recs:
        assert blends(o) == ({"BLEND"} if o.rested else {"ADD"})
    # and the other way round
    g = make(env, trail=True)
    set_colours(g, BLACK, PURPLE)
    go(g, shape, n=6, nPurple=2)
    for o in flying(g):
        assert blends(o) == ({"ADD"} if o.rested else {"BLEND"})


@pytest.mark.parametrize("shape", SHAPES)
def test_a_pooled_ghost_is_additive_again_for_a_bright_orb(env, shape):
    g = make(env, trail=True)
    set_colours(g, BLACK)
    go(g, shape)
    dark = [t for o in flying(g) for t in ghosts_of(o)]
    assert dark and all(mode_of(t) == "BLEND" for t in dark)
    for o in flying(
        g
    ):  # every texture of the dark orbs (the pool is LIFO, so a ghost may come back as a body)
        for t in [o.under, o.body, o.spark, *ghosts_of(o)]:
            t.wasDark = True  # a mark on the Lua table, to recognise the texture when the pool hands it out again
    g.tick(0.05, 100)  # every orb lands, its textures go back to the pool
    assert in_use(g) == 0
    set_colours(g, PURPLE)
    go(g, shape)
    bright = [t for o in flying(g) for t in ghosts_of(o)]
    assert any(t.wasDark for t in bright), (
        "the pool should hand the dark orbs' textures out again"
    )
    assert all(mode_of(t) == "ADD" for t in bright)


def lum(c):
    return sum(w * v for w, v in zip(LUM, c, strict=True))


def test_threshold_boundary(env):
    g = make(env, trail=True)
    limit = float(g.ns.OrbShapes.k.darkTrailLum)
    assert limit == pytest.approx(0.25)
    blend = g.ns.OrbShapes.trailBlend
    # grey of luminance just under / at / over the limit (the weights sum to 1)
    assert str(blend(limit - 0.001, limit - 0.001, limit - 0.001)) == "BLEND"
    assert str(blend(limit, limit, limit)) == "ADD"
    assert str(blend(limit + 0.001, limit + 0.001, limit + 0.001)) == "ADD"
    # pure channels: blue alone is dark (0.0722), green alone is not (0.7152)
    assert str(blend(0, 0, 1)) == "BLEND"
    assert str(blend(0, 1, 0)) == "ADD"
    assert lum([0, 0.34, 0]) < limit < lum([0, 0.35, 0])
    assert str(blend(0, 0.34, 0)) == "BLEND" and str(blend(0, 0.35, 0)) == "ADD"
    assert str(blend(1, 0, 0)) == "BLEND"  # pure red is dark by luminance (0.2126)


def test_dark_ghosts_keep_the_same_alphas(env):
    """BLEND only changes the mode: the ghosts keep the same alpha (x trail opacity) as bright ones."""
    g = make(env, trail=True)
    set_colours(g, PURPLE, BLACK)
    go(g, "starlight", n=2, nPurple=1)
    dark, bright = sorted(flying(g), key=lambda o: not o.rested)
    assert dark.rested and not bright.rested
    got = [[t.alpha / o.body.alpha for t in ghosts_of(o)] for o in (dark, bright)]
    assert all(a > 0 for a in got[0])
    # (a rested orb draws 1.15x bigger and a little behind the other, so compare the ghost-to-body alpha ratios)
    assert got[0] == pytest.approx(got[1], rel=0.05)
