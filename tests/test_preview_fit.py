"""The orb preview window grows taller so the orbs get their spacing and nothing is clipped: the header row (title top
left, Cluster top right), the orb area's height from the layout, and Retro's neighbour distance."""

import math

import pytest
from test_m5 import build
from test_shape_look import tick, up

SIZES = {
    "starlight": (8, 14, 20, 26, 32),
    "bubble": (8, 14, 20, 26, 32),
    "crackle": (8, 14, 20, 26, 32),
    "retro": (1, 2, 3, 4, 5),
}
DENSITIES = (50, 100, 150, 200, 300)
TITLE_H, PAD, MIN_H, MAX_H = 28, 8, 120, 400


def look(m, shape, size, density, cluster, rested):
    m.slash(f"shape {shape}")
    m.ns.SetLook("size", size)
    m.db.density, m.db.previewCluster, m.db.restedTint = density, cluster, rested
    m.db.pulse = False
    sp = m.ns.ShapePreview
    sp.Sync(sp)
    tick(m, 2)
    return sp


def drawn(sp, shape):
    """(x, y, width) of every orb texture that counts as visible art (the faint underlay is not, except Retro's)."""
    box = sp.box
    out = []
    for i in range(1, 3 * int(box.n) + 1):
        t = box.tex[i]
        if not (t.shown and t.calls and t.calls["SetTexture"]):
            continue
        if shape != "retro" and t.calls["SetDrawLayer"][2] < 0:
            continue
        pt = t.points[1]
        out.append((float(pt[4]), float(pt[5]), float(t.width)))
    return out


def area_of(sp):
    return float(sp.window.height) - TITLE_H - PAD, float(sp.window.width) - 2 * PAD


def combos(shape):
    for size in SIZES[shape]:
        for density in DENSITIES:
            for cluster in (False, True):
                for rested in (False, True):
                    yield size, density, cluster, rested


@pytest.mark.parametrize("shape", list(SIZES))
def test_nothing_is_clipped(env, shape):
    m = build(env)
    up(m)
    for size, density, cluster, rested in combos(shape):
        sp = look(m, shape, size, density, cluster, rested)
        area_h, area_w = area_of(sp)
        assert area_h >= 84 and float(sp.window.height) >= MIN_H
        for x, y, w in drawn(sp, shape):
            where = (shape, size, density, cluster, rested)
            assert abs(y) + w / 2 <= area_h / 2 + 0.01, where
            assert abs(x) + w / 2 <= area_w / 2 + 0.01, where


@pytest.mark.parametrize("shape", list(SIZES))
def test_the_window_grows_with_size(env, shape):
    m = build(env)
    up(m)
    for density in DENSITIES:
        for cluster in (False, True):
            heights = []
            for size in SIZES[shape]:
                sp = look(m, shape, size, density, cluster, False)
                heights.append(float(sp.window.height))
            assert min(heights) >= MIN_H
            if cluster:  # (the tidy layout changes its row count with the size: the star, then fewer per row)
                assert heights == sorted(heights)
            if (
                density >= 100
            ):  # (two or three orbs sit in a row and never need the height)
                assert (
                    heights[-1] > heights[0]
                )  # grows until the cap (MAX_H), then plateaus there
            assert max(heights) <= MAX_H


@pytest.mark.parametrize("shape", list(SIZES))
def test_the_window_never_gets_taller_than_the_cap(env, shape):
    m = build(env)
    up(m)
    for size, density, cluster, rested in combos(shape):
        sp = look(m, shape, size, density, cluster, rested)
        assert float(sp.window.height) <= MAX_H, (shape, size, density, cluster, rested)


def test_retro_at_its_biggest_size_fits_the_cap_without_the_squeeze(env):
    m = build(env)
    up(m)
    for cluster in (False, True):
        sp = look(m, "retro", 5, 300, cluster, False)
        assert float(sp.window.height) <= MAX_H, cluster


def test_retro_neighbours_stay_a_cell_apart_after_the_snap_in_the_tidy_layout(env):
    m = build(env)
    up(m)
    for size in SIZES["retro"]:
        for density in DENSITIES:
            sp = look(m, "retro", size, density, False, False)
            assert float(sp.RadiusFor(sp.box.pattern, m.db, False)) >= 9 * size
            discs = [
                (x, y) for x, y, w in drawn(sp, "retro") if abs(w - 8 * size) < 1e-6
            ]
            assert len(discs) == int(sp.box.n)
            for i, p in enumerate(discs):
                for q in discs[i + 1 :]:
                    # after the whole-cell snap: the 8 cell disc plus a cell of gap, honeycomb diagonals included
                    assert math.hypot(p[0] - q[0], p[1] - q[1]) >= 9 * size - 1e-6, (
                        size,
                        density,
                    )


def test_the_title_is_top_left_and_cluster_top_right(env):
    m = build(env)
    up(m)
    sp = m.ns.ShapePreview
    title = next(
        f
        for f in m.stub.frames.values()
        if f.kind == "FontString" and f.text == "Preview"
    )
    pt = title.points[1]
    assert (pt[1], pt[3]) == ("TOPLEFT", "TOPLEFT") and pt[4] > 0 and pt[5] < 0
    pt = sp.check.points[1]
    assert (pt[1], pt[3]) == ("TOPRIGHT", "TOPRIGHT") and pt[4] <= 0 and pt[5] <= 0
    label = next(
        f
        for f in m.stub.frames.values()
        if f.kind == "FontString" and f.text == "Cluster"
    )
    assert label.points[1][1] == "RIGHT"  # still left of the tickbox
    # the label's centre lines up with the title's: the title is ~12 px tall from y -10 (centre -16); the 20 px
    # tickbox from y -7 has its centre at -17 and the label sits 1 px above that
    assert sp.check.points[1][5] == -7
    title_mid = title.points[1][5] - 6
    label_mid = sp.check.points[1][5] - 10 + label.points[1][5]
    assert abs(label_mid - title_mid) <= 1
    box = sp.box.points
    assert (box[1][1], box[1][4], box[1][5]) == ("TOPLEFT", 8, -28) and (
        box[2][1],
        box[2][4],
        box[2][5],
    ) == ("BOTTOMRIGHT", -8, 8)


def test_the_window_resizes_live_and_the_test_target_follows_its_bottom(env):
    m = build(env)
    up(m)
    sp = m.ns.ShapePreview
    small = float(sp.window.height)
    assert small == 128  # the default star of 8 orbs, a little over the least
    look(m, "crackle", 32, 200, False, True)
    tall = float(sp.window.height)
    assert tall > small
    pt = m.ns.Preview.window.points[1]
    assert (pt[1], pt[3]) == ("TOP", "BOTTOM") and m.lua.eval("rawequal")(
        pt[2], sp.window
    )
    look(m, "starlight", 14, 100, False, True)  # the defaults again
    assert float(sp.window.height) == small
