"""Per-shape look (size, quantity and opacity are remembered per orb shape), the opacity and pulsing settings, the shape
renames and their old-name aliases, Retro's one cell size per burst and its stepped pops, the Retro filter line in the
status, and the options preview box."""

import math

import pytest
from test_m5 import build, ctl, show
from test_p2_unknown import fire
from test_shapes import ART, BOLTS, PRE, SHAPES, flying, go, in_use, path_of, set_shape
from test_v09 import chat_lines, make, pop_textures
from test_v102 import load_db

DEFAULT_LOOK = {
    "starlight": (14, 100, 100),
    "retro": (2, 75, 100),
    "globe": (14, 100, 100),
    "crackle": (14, 100, 100),
}


def look_of(db, shape):
    entry = db.shapeLook[shape]
    return (entry.size, entry.density, entry.opacity)


def active(db):
    return (db.size, db.density, db.opacity)


def retro_cell(size):
    return max(2, math.floor(size * 24 / 14 / 8 + 0.5))


# ---------------------------------------------------------------- the renames and their old names


@pytest.mark.parametrize("old, new", [("power", "crackle"), ("wisp", "globe")])
def test_a_saved_old_shape_name_is_mapped(env, old, new):
    assert load_db(env, {"version": 7, "orbShape": old}).orbShape == new


def test_the_slash_command_still_takes_the_old_names(env):
    m = build(env)
    m.slash("shape power")
    assert m.db.orbShape == "crackle" and m.say()[-1].endswith("orb shape: Crackle")
    m.slash("shape wisp")
    assert m.db.orbShape == "globe" and m.say()[-1].endswith("orb shape: Globe")


def test_the_labels_and_order(env):
    m = build(env)
    assert [str(m.ns.SHAPE_ORDER[i]) for i in range(1, 5)] == SHAPES
    assert [str(m.ns.SHAPE_LABEL[s]) for s in SHAPES] == [
        "Starlight",
        "Retro",
        "Globe",
        "Crackle",
    ]
    assert m.ns.SHAPE_LABEL["power"] is None and m.ns.SHAPE_LABEL["wisp"] is None


def test_no_stale_texture_files_remain():
    from test_shapes import MEDIA

    for old in ("wisp", "wisp_under", "power_core"):
        assert not (MEDIA / f"{old}.tga").exists(), old


# ---------------------------------------------------------------- saved look per shape


def test_every_shape_starts_with_its_own_defaults(env):
    db = load_db(env, {})
    for shape, look in DEFAULT_LOOK.items():
        assert look_of(db, shape) == look
    assert (
        active(db) == DEFAULT_LOOK["starlight"]
        and db.opacity == 100
        and db.pulse is True
    )


def test_a_save_without_shapelook_keeps_its_size_and_density_for_the_current_shape(env):
    db = load_db(env, {"version": 7, "orbShape": "crackle", "size": 20, "density": 200})
    assert look_of(db, "crackle") == (20, 200, 100)
    assert [look_of(db, s) for s in ("starlight", "globe", "retro")] == [
        DEFAULT_LOOK[s] for s in ("starlight", "globe", "retro")
    ]
    assert active(db) == (20, 200, 100)


def test_the_migration_defaults_to_starlight_and_maps_old_names(env):
    db = load_db(env, {"version": 7, "size": 20, "density": 150})
    assert (
        look_of(db, "starlight") == (20, 150, 100)
        and look_of(db, "retro") == DEFAULT_LOOK["retro"]
    )
    env2_db = load_db(env, {"version": 7, "orbShape": "wisp", "size": 9})
    assert env2_db.orbShape == "globe" and look_of(env2_db, "globe") == (9, 100, 100)


def test_the_migration_clamps_what_it_copies(env):
    db = load_db(
        env, {"version": 7, "orbShape": "crackle", "size": 500, "density": "junk"}
    )
    assert look_of(db, "crackle") == (32, 100, 100)


def test_the_active_values_come_from_the_current_shapes_entry(env):
    db = load_db(
        env,
        {
            "version": 7,
            "orbShape": "retro",
            "size": 20,
            "lookRev": 2,
            "shapeLook": {"retro": {"size": 5}},
        },
    )
    assert active(db) == (
        5,
        75,
        100,
    )  # the entry wins; its missing keys get that shape's defaults


def test_partial_and_junk_entries_are_repaired_and_clamped(env):
    db = load_db(
        env,
        {
            "version": 7,
            "orbShape": "globe",
            "shapeLook": {
                "globe": {"size": 99, "density": "x"},
                "retro": "junk",
                "starlight": {"size": 10, "opacity": 33},
                "crackle": {"opacity": -5, "size": float("nan")},
            },
        },
    )
    assert look_of(db, "globe") == (32, 100, 100)
    assert look_of(db, "retro") == DEFAULT_LOOK["retro"]
    assert look_of(db, "starlight") == (10, 100, 35)  # opacity snaps to its step of 5
    assert look_of(db, "crackle") == (14, 100, 20)
    assert active(db) == (32, 100, 100)


@pytest.mark.parametrize("junk", ["text", 5, True, [], {}])
def test_a_junk_shapelook_gives_the_defaults(env, junk):
    db = load_db(env, {"version": 7, "orbShape": "globe", "shapeLook": junk})
    for shape, look in DEFAULT_LOOK.items():
        assert look_of(db, shape) == look
    assert active(db) == DEFAULT_LOOK["globe"]


def test_no_schema_bump_for_the_look(env):
    assert load_db(env, {"version": 7}).version == 7


@pytest.mark.parametrize("bad, expected", [(5, 20), (500, 100), (47, 45), ("x", 100)])
def test_opacity_is_clamped_and_snapped(env, bad, expected):
    db = load_db(env, {"version": 7, "shapeLook": {"starlight": {"opacity": bad}}})
    assert db.opacity == expected and look_of(db, "starlight")[2] == expected


# ---------------------------------------------------------------- switching shapes


def test_switching_stores_the_active_look_and_loads_the_new_shapes(env):
    g = make(env)
    ns, db = g.ns, g.db
    db.size = 20  # the Starlight tuning
    assert ns.SetOrbShape("retro") is True
    assert db.orbShape == "retro" and active(db) == (2, 75, 100)
    assert look_of(db, "starlight") == (20, 100, 100)
    db.size, db.density, db.opacity = 5, 150, 60
    assert ns.SetOrbShape("starlight") is True
    assert active(db) == (20, 100, 100) and look_of(db, "retro") == (5, 150, 60)
    ns.SetOrbShape("retro")
    assert active(db) == (5, 150, 60)


def test_switching_rejects_unknown_names_and_takes_old_ones(env):
    g = make(env)
    assert g.ns.SetOrbShape("bogus") is False and g.db.orbShape == "starlight"
    assert g.ns.SetOrbShape("power") is True and g.db.orbShape == "crackle"
    assert (
        g.ns.SetOrbShape("wisp") is True
        and g.db.orbShape == "globe"
        and g.db.size == 14
    )


def test_switching_to_the_same_shape_changes_nothing(env):
    g = make(env)
    g.db.size = 22
    g.ns.SetOrbShape("starlight")
    assert (
        g.db.size == 22 and look_of(g.db, "starlight")[0] == 14
    )  # not stored: nothing was switched


def test_the_slash_command_switches_and_the_sliders_follow(env):
    m = build(env)
    show(m)
    m.stub.slide(ctl(m, "size"), 20)
    m.slash("shape retro")
    assert active(m.db) == (2, 75, 100)
    # (the size slider still has the 8-32 range until the Options follow Retro's 1-7)
    assert (ctl(m, "density").value, ctl(m, "opacity").value) == (75, 100)
    m.slash("shape starlight")
    assert ctl(m, "size").value == 20 and ctl(m, "density").value == 100


def test_the_dropdown_switches_and_the_sliders_follow(env):
    m = build(env)
    show(m)
    m.stub.slide(ctl(m, "opacity"), 60)
    assert m.stub.pickMenu(m.opt.shapeDropdown, "Globe") is True
    assert active(m.db) == (14, 100, 100)
    assert ctl(m, "size").value == 14 and ctl(m, "opacity").value == 100
    m.stub.pickMenu(m.opt.shapeDropdown, "Starlight (default)")
    assert active(m.db) == (14, 100, 60) and ctl(m, "opacity").value == 60


def test_the_sliders_write_the_active_value_and_the_current_shapes_entry(env):
    m = build(env)
    show(m)
    m.stub.slide(ctl(m, "size"), 20)
    m.stub.slide(ctl(m, "density"), 250)
    m.stub.slide(ctl(m, "opacity"), 75)
    assert active(m.db) == (20, 250, 75) and look_of(m.db, "starlight") == (20, 250, 75)
    assert (
        look_of(m.db, "retro") == DEFAULT_LOOK["retro"]
    )  # nothing leaks into the others
    m.slash("shape retro")
    m.stub.slide(ctl(m, "size"), 9)
    assert look_of(m.db, "retro")[0] == 9 and look_of(m.db, "starlight") == (
        20,
        250,
        75,
    )


def test_a_typed_value_goes_through_the_same_write(env):
    m = build(env)
    show(m)
    m.slash("shape retro")
    m.stub.rightClick(m.opt.valueButtons["size"])
    m.stub.enterText(m.opt.editBoxes["size"], "18")
    assert m.db.size == 18 and look_of(m.db, "retro")[0] == 18


def test_the_opacity_slider_sits_right_after_size_with_its_range(env):
    m = build(env)
    show(m)
    rows = m.opt.rows

    def y(key):
        return -rows[key].points[1][5]

    assert y("size") < y("opacity") < y("flightTime") and y("opacity") - y("size") == 32
    slider = ctl(m, "opacity")
    assert (slider.minV, slider.maxV, slider.step) == (20, 100, 5)
    assert "Orb opacity" in [
        str(f.text) for f in m.stub.frames.values() if f.kind == "FontString" and f.text
    ]
    assert str(m.opt.valueTexts["opacity"].text) == "100%"


# ---------------------------------------------------------------- reset buttons


def test_the_reset_buttons_restore_the_current_shapes_default(env):
    m = build(env)
    show(m)
    m.slash("shape retro")
    size_btn, density_btn = m.opt.resets["size"], m.opt.resets["density"]
    assert (
        not size_btn.shown and not density_btn.shown
    )  # Retro's own defaults, though Starlight's differ
    m.stub.slide(ctl(m, "size"), 20)
    assert size_btn.shown
    m.stub.hover(size_btn)
    assert str(m.stub.tooltip.text) == "Reset to default: 2"
    m.stub.click(size_btn)
    assert m.db.size == 2 and look_of(m.db, "retro")[0] == 2 and not size_btn.shown
    m.stub.slide(ctl(m, "density"), 100)
    assert density_btn.shown
    m.stub.hover(density_btn)
    assert str(m.stub.tooltip.text) == "Reset to default: 75%"
    m.stub.click(density_btn)
    assert m.db.density == 75 and look_of(m.db, "retro")[1] == 75


def test_the_buttons_follow_a_shape_switch(env):
    m = build(env)
    show(m)
    m.stub.slide(
        ctl(m, "size"), 12
    )  # Starlight at Retro's default: differs from Starlight's
    assert m.opt.resets["size"].shown
    m.slash("shape retro")
    assert not m.opt.resets["size"].shown  # Retro's own value is its default
    m.stub.slide(ctl(m, "opacity"), 50)
    m.stub.click(m.opt.resets["opacity"])
    assert m.db.opacity == 100 and look_of(m.db, "retro")[2] == 100
    m.slash("shape starlight")
    assert m.db.size == 12 and m.opt.resets["size"].shown


def test_the_shape_reset_goes_back_to_starlight_and_swaps_the_look(env):
    m = build(env)
    show(m)
    m.stub.slide(ctl(m, "size"), 20)
    m.stub.pickMenu(m.opt.shapeDropdown, "Retro")
    m.stub.click(m.opt.resets["orbShape"])
    assert m.db.orbShape == "starlight" and active(m.db) == (20, 100, 100)
    assert look_of(m.db, "retro") == DEFAULT_LOOK["retro"]


def test_reset_all_restores_every_shapes_entry(env):
    m = build(env)
    for shape, size in (("starlight", 9), ("retro", 30), ("globe", 8), ("crackle", 25)):
        m.slash(f"shape {shape}")
        m.db.size, m.db.opacity = size, 40
        m.ns.SetLook("size", size)
        m.ns.SetLook("opacity", 40)
    m.slash("reset")
    assert m.db.orbShape == "starlight" and m.db.pulse is True
    for shape, look in DEFAULT_LOOK.items():
        assert look_of(m.db, shape) == look
    assert active(m.db) == DEFAULT_LOOK["starlight"]


def test_the_core_reset_of_a_look_matches_the_buttons(env):
    g = make(env)
    g.ns.SetOrbShape("globe")
    g.ns.SetLook("size", 9)
    assert g.db.size == 9 and look_of(g.db, "globe")[0] == 9
    assert (
        g.ns.ShapeDefault("globe", "size") == 14
        and g.ns.ShapeDefault("retro", "density") == 75
    )


# ---------------------------------------------------------------- status


def test_status_shows_the_active_shapes_look(env):
    m = build(env)
    m.slash("shape retro")
    m.stub.chat = m.lua.table() if False else m.stub.chat
    m.slash("status")
    assert any(
        "orb shape: Retro (size 2, quantity 75%, opacity 100%), pulsing on" in line
        for line in m.say()
    )
    m.slash("shape globe")
    m.slash("pulse off")
    m.slash("status")
    assert any(
        "orb shape: Globe (size 14, quantity 100%, opacity 100%), pulsing off" in line
        for line in m.say()
    )


def filter_lines(g):
    return [line for line in chat_lines(g) if "retro pixel filter" in line]


def test_status_has_no_filter_line_until_retro_matters(env):
    g = make(env)
    g.slash("status")
    assert filter_lines(g) == []


def test_status_says_the_filter_is_not_tried_yet_on_retro(env):
    g = make(env)
    g.ns.SetOrbShape("retro")
    g.slash("status")
    assert filter_lines(g)[-1].endswith("retro pixel filter: not tried yet")


def test_status_reports_nearest_after_a_retro_orb_was_drawn(env):
    g = make(env)
    go(g, "retro", n=2, trail=False, advance=0.1)
    set_shape(g, "starlight")  # the line stays once a retro orb has been drawn
    g.slash("status")
    assert filter_lines(g)[-1].endswith("retro pixel filter: nearest")


def test_status_reports_the_smoothed_fallback(env):
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
    go(g, "retro", n=2, trail=False, advance=0.1)
    g.slash("status")
    assert filter_lines(g)[-1].endswith(
        "retro pixel filter: smoothed (nearest unavailable)"
    )


# ---------------------------------------------------------------- pulsing


def test_pulse_defaults_on_and_is_a_boolean(env):
    assert load_db(env, {}).pulse is True
    # pulse is per shape now: a junk value in a shape's entry gets the default, a real boolean stays
    db = load_db(
        env,
        {"lookRev": 2, "orbShape": "globe", "shapeLook": {"globe": {"pulse": "yes"}}},
    )
    assert db.pulse is True and db.shapeLook.globe.pulse is True
    db = load_db(
        env, {"lookRev": 2, "orbShape": "globe", "shapeLook": {"globe": {"pulse": False}}}
    )
    assert db.pulse is False and db.shapeLook.globe.pulse is False


def test_the_pulse_slash_command(env):
    m = build(env)
    m.slash("shape globe")
    m.slash("pulse")
    assert m.say()[-1].endswith("pulsing: on")
    m.slash("pulse off")
    assert m.db.pulse is False and m.say()[-1].endswith("pulsing: off")
    assert m.db.shapeLook.globe.pulse is False and m.db.shapeLook.retro.pulse is True
    m.slash("pulse on")
    assert m.db.pulse is True and m.db.shapeLook.globe.pulse is True
    m.slash("pulse sideways")
    assert "pulse: use on or off (now on)" in m.say()[-1]
    m.slash("help")
    assert any("/xporbs pulse on|off" in line for line in m.say())


def test_the_pulse_command_off_globe_says_it_is_globe_only(env):
    m = build(env)
    m.slash("shape retro")
    m.slash("pulse off")
    assert m.say()[-1].endswith("pulsing: off (Globe only)")
    assert m.db.shapeLook.retro.pulse is False and m.db.shapeLook.globe.pulse is True


def test_the_pulsing_checkbox_follows_the_shape_dropdown(env):
    m = build(env)
    show(m)
    box = ctl(m, "pulse")
    assert box.checked is True and str(m.opt.rows["pulse"].points[1][5]) != ""
    assert -m.opt.rows["orbShape"].points[1][5] < -m.opt.rows["pulse"].points[1][5]
    assert -m.opt.rows["pulse"].points[1][5] < -m.opt.rows["color"].points[1][5]
    m.stub.hover(box)
    assert str(m.stub.tooltip.text) == "Globe orbs gently swell and shrink."
    m.stub.click(box)
    assert m.db.pulse is False and m.opt.resets["pulse"].shown
    m.slash("pulse on")
    assert box.checked is True and not m.opt.resets["pulse"].shown


# ---------------------------------------------------------------- opacity on every kind of orb

ROLES = ("under", "body", "spark", "ghost1", "ghost2", "ghost3", "ghost4")


def orb_alphas(rec):
    return {
        name: getattr(rec, name).alpha
        for name in ROLES
        if getattr(rec, name) is not None
    }


@pytest.mark.parametrize("shape", SHAPES)
def test_opacity_multiplies_every_texture_of_a_flying_orb(env, shape):
    g = make(env, trail=True)
    g.db.opacity = 100
    go(g, shape, n=1, advance=0.5)
    (o,) = flying(g)
    full = orb_alphas(o)
    assert full["body"] == 1 and len(full) >= 5
    g.tick(0.05, 60)
    g.db.opacity = 50
    go(g, shape, n=1, advance=0.5)
    (o,) = flying(g)
    half = orb_alphas(o)
    assert half.keys() == full.keys()
    for name in full:
        assert half[name] == pytest.approx(full[name] * 0.5), name


def alphas_of(textures):
    return [float(t.alpha or 0) for t in textures]


@pytest.mark.parametrize("shape", SHAPES)
def test_opacity_multiplies_a_nameplate_pop(env, shape):
    g = make(env, trail=True)
    g.db.opacity = 100
    go(g, shape, style="popstream", n=2, advance=0.2)
    full = alphas_of(pop_textures(g))
    assert max(full) > 0.3
    g.tick(0.05, 60)
    g.db.opacity = 50
    go(g, shape, style="popstream", n=2, advance=0.2)
    assert alphas_of(pop_textures(g)) == pytest.approx([a * 0.5 for a in full])


@pytest.mark.parametrize("shape", SHAPES)
def test_opacity_multiplies_the_crossfade_copies(env, shape):
    g = make(env, trail=True)
    snaps = []
    for opacity in (100, 50):
        g.db.opacity = opacity
        set_shape(g, shape)
        fire(g, "crossfade", n=2)
        g.tick(0.05, 5)  # copy A is up
        a = alphas_of(pop_textures(g))
        g.tick(0.05, 12)  # copy B is flying
        b = [o.body.alpha for o in flying(g)]
        snaps.append((a, b))
        g.tick(0.05, 80)
    (a100, b100), (a50, b50) = snaps
    assert max(a100) > 0.3 and b100 and max(b100) == 1
    assert a50 == pytest.approx([x * 0.5 for x in a100]) and b50 == pytest.approx(
        [x * 0.5 for x in b100]
    )


@pytest.mark.parametrize("shape", SHAPES)
def test_opacity_multiplies_a_direct_pop(env, shape):
    g = make(env, trail=True)
    snaps = []
    for opacity in (100, 50):
        g.db.opacity = opacity
        set_shape(g, shape)
        fire(g, "streampop", n=2)
        g.tick(0.05, 3)  # in the bloom
        snaps.append([orb_alphas(o) for o in flying(g)])
        g.tick(0.05, 80)
    full, half = snaps
    assert full and full[0]["body"] > 0.3
    for f, h in zip(full, half, strict=True):
        assert h == {k: pytest.approx(v * 0.5) for k, v in f.items()}


def test_opacity_leaves_the_arrival_flash_alone(env):
    g = make(env)
    g.db.opacity = 100
    go(g, "starlight", n=1, trail=False, advance=0.0)
    g.tick(0.05, 24)
    flash = [
        t
        for t in g.stub.frames.values()
        if t.kind == "Texture" and t.shown and not t.calls["SetDrawLayer"]
    ]
    assert flash
    g.tick(0.05, 80)
    g.db.opacity = 20
    go(g, "starlight", n=1, trail=False, advance=0.0)
    g.tick(0.05, 24)
    flash_low = [
        t
        for t in g.stub.frames.values()
        if t.kind == "Texture" and t.shown and not t.calls["SetDrawLayer"]
    ]
    assert flash_low and flash_low[0].alpha == pytest.approx(flash[0].alpha)


# ---------------------------------------------------------------- Crackle


def test_crackle_has_no_count_size_or_time_multiplier(env):
    g = make(env)
    shape = g.ns.OrbShapes.by.crackle
    assert shape.timeMul == 1 and tuple(shape.adjust(10, 4, 1.0)) == (
        10,
        4,
        1.0,
    )
    assert shape.needTrail == 5 and shape.needPlain == 3


def test_crackle_bolts_are_tighter_and_the_core_fuller(env):
    g = make(env, trail=True)
    go(g, "crackle", n=1, advance=0.0)
    (o,) = flying(g)
    for _ in range(10):
        g.tick(0.03, 1)
        if o.body.alpha == 1:
            body = o.size * 2.0
            assert o.body.width == pytest.approx(
                1.15 * body
            ) and o.spark.width == pytest.approx(1.30 * body)
            assert o.under.width == pytest.approx(1.6 * body)
            assert path_of(o.body) == PRE + "crackle_core"
            return
    pytest.fail("never reached full alpha")


# ---------------------------------------------------------------- Retro: one cell size per burst


@pytest.mark.parametrize("size", range(8, 33))
def test_retro_normal_and_rested_orbs_share_one_cell(env, size):
    g = make(env)
    g.db.size = size
    go(g, "retro", n=4, trail=False, advance=0.45, nPurple=2)
    recs = flying(g)
    assert sum(1 for o in recs if o.rested) == 2 and len(recs) == 4
    cell = retro_cell(size)
    assert {o.cell for o in recs} == {cell}
    assert {o.body.width for o in recs} == {8 * cell} and {
        o.under.width for o in recs
    } == {10 * cell}


def test_retro_size_eleven_is_two_pixel_cells_for_every_orb(env):
    g = make(env)
    g.db.size = 11
    go(g, "retro", n=4, trail=False, advance=0.45, nPurple=2)
    assert {o.cell for o in flying(g)} == {2}


def test_retro_keeps_its_cell_all_flight_long(env):
    g = make(env)
    go(g, "retro", n=3, trail=True, advance=0.0, nPurple=1)
    seen = set()
    for _ in range(25):
        g.tick(0.04, 1)
        for o in flying(g):
            if o.body.width:
                seen.add(o.body.width)
    assert seen == {24}  # no shrink near the bar, no rested or path-depth steps


def test_retro_uses_the_burst_scale_for_its_cell(env):
    g = make(env)
    go(g, "retro", n=2, trail=False, advance=0.45, scale=2.0, nPurple=1)
    assert {o.cell for o in flying(g)} == {retro_cell(14 * 2.0)}


def sample_cells(g, pick, steps=60, dt=0.01):
    """The body's cell (width / 8) after every tick while it is drawn."""
    cells = []
    for _ in range(steps):
        g.tick(dt, 1)
        for body in pick(g):
            if body.shown and body.width:
                cells.append(body.width / 8)
    return cells


def check_steps(cells, flight):
    assert cells and all(float(c).is_integer() for c in cells)
    assert max(cells) <= flight  # never bigger than in flight
    assert cells == sorted(cells)  # it only grows
    assert min(cells) <= 1 and set(cells) >= {
        1,
        2,
        flight,
    }  # 1 -> 2 -> 3 pixels at 3 px cells


def test_a_retro_nameplate_pop_grows_in_whole_cells_and_never_exceeds_the_flight_cell(
    env,
):
    g = make(env)
    set_shape(g, "retro")
    fire(g, "popstream", n=2)
    cells = sample_cells(g, lambda g: [pop_textures(g)[1]], steps=50)
    check_steps(cells, 3)


def test_a_retro_direct_pop_grows_in_whole_cells(env):
    g = make(env)
    set_shape(g, "retro")
    fire(g, "streampop", n=1)
    cells = sample_cells(g, lambda g: [o.body for o in flying(g)], steps=26)
    assert (
        cells
        and all(float(c).is_integer() for c in cells)
        and max(cells) <= 3
        and min(cells) <= 1
    )
    assert cells == sorted(cells) and 3 in cells


def test_a_retro_crossfade_copy_grows_in_whole_cells(env):
    g = make(env)
    set_shape(g, "retro")
    fire(g, "crossfade", n=1)
    cells = sample_cells(g, lambda g: [pop_textures(g)[1]], steps=23)
    assert (
        cells
        and all(float(c).is_integer() for c in cells)
        and max(cells) <= 3
        and min(cells) <= 1
    )
    assert cells == sorted(cells)


def test_retro_pops_keep_the_rested_cell_too(env):
    g = make(env)
    g.db.size = 11
    set_shape(g, "retro")
    fire(g, "popstream", n=2, nPurple=1)
    g.tick(0.05, 8)
    bodies = [pop_textures(g)[1], pop_textures(g)[4]]
    assert bodies[0].width == bodies[1].width


def test_the_other_shapes_pops_keep_their_sizes(env):
    g = make(env)
    g.ns.SetOrbShape("globe")
    g.ns.SetLook("pulse", False)
    for shape, factor in (("globe", 1.5), ("crackle", 2.0 * 1.15), ("starlight", 2.0)):
        set_shape(g, shape)
        fire(g, "popstream", n=1)
        g.tick(0.02, 3)  # progress well under the shrink, alpha 1
        body = pop_textures(g)[1]
        assert body.width == pytest.approx(14 * 1.2 * factor), shape
        g.tick(0.05, 40)


# ---------------------------------------------------------------- the pool still fits a full burst


@pytest.mark.parametrize("shape", SHAPES)
def test_a_full_burst_of_every_shape_fits_with_room_for_a_second(env, shape):
    g = make(env)
    set_shape(g, shape)
    g.db.trail = True
    cap = int(g.db.cap)
    fire(g, "stream", n=cap)
    fire(g, "stream", n=cap)
    assert len(flying(g)) == 2 * cap
    assert in_use(g) <= g.orbs.Info(g.orbs)[3] - 1
    assert all(o.ghost1 is not None for o in flying(g))  # nobody lost the trail


# ---------------------------------------------------------------- the options preview


def preview_orbs(m):
    box, same = m.ns.ShapePreview.box, m.lua.eval("rawequal")
    return [
        t
        for t in m.stub.frames.values()
        if t.kind == "Texture"
        and same(t.parentFrame, box)
        and t.calls
        and t.calls["SetTexture"]
    ]


def tick(m, n=2, dt=0.05):
    for _ in range(n):
        m.stub.tick(dt)


def bodies(m):
    return [t for t in preview_orbs(m) if t.calls["SetDrawLayer"][2] == 0]


def test_the_preview_only_exists_with_the_debug_log_on(env):
    m = build(env)
    show(m)
    assert m.ns.ShapePreview.box is None
    m.slash("debug on")
    assert m.ns.ShapePreview.box is not None and m.ns.ShapePreview.box.up
    m.slash("debug off")
    assert not m.ns.ShapePreview.box.up and not m.ns.ShapePreview.box.shown


def test_the_preview_box_is_titled_and_sits_above_the_footer(env):
    m = build(env)
    m.slash("debug on")
    box = m.ns.ShapePreview.box
    assert box.parentFrame is m.opt.panel or m.lua.eval("rawequal")(
        box.createdParent, m.opt.panel
    )
    point = box.points[1]
    assert (point[1], point[4], point[5]) == ("BOTTOMLEFT", 16 + 552 - 264, 44 + 4)
    assert "Preview" in [
        str(f.text) for f in m.stub.frames.values() if f.kind == "FontString" and f.text
    ]
    # the scroll body stops above the box while it is up, and goes back when it is gone
    assert m.opt.scroll.points[2][4] == -28 and m.opt.scroll.points[2][5] == 44 + 86 + 8
    m.slash("debug off")
    assert m.opt.scroll.points[2][5] == 44


def test_the_preview_shows_five_orbs_two_of_them_rested(env):
    m = build(env)
    m.slash("debug on")
    tick(m)
    assert len(preview_orbs(m)) == 15 and len(bodies(m)) == 5
    colours = [
        tuple(round(float(v), 3) for v in b.calls["SetVertexColor"].values())
        for b in bodies(m)
    ]
    normal, rested = (
        tuple(round(float(m.db.color[i]), 3) for i in (1, 2, 3)),
        tuple(round(float(m.db.restedColor[i]), 3) for i in (1, 2, 3)),
    )
    assert colours == [normal] * 3 + [rested] * 2
    assert all(b.shown for b in bodies(m))
    m.db.restedTint = False
    m.opt.Refresh(m.opt)
    tick(m)
    assert {
        tuple(round(float(v), 3) for v in b.calls["SetVertexColor"].values())
        for b in bodies(m)
    } == {normal}


@pytest.mark.parametrize("shape", SHAPES)
def test_the_preview_follows_the_shape(env, shape):
    m = build(env)
    m.slash("debug on")
    m.slash(f"shape {shape}")
    tick(m)
    under, body, spark = ART[shape]
    assert {path_of(t) for t in bodies(m)} == {body}
    assert {
        path_of(t) for t in preview_orbs(m) if t.calls["SetDrawLayer"][2] == -1
    } == {under}
    if shape == "crackle":
        assert {
            path_of(t) for t in preview_orbs(m) if t.calls["SetDrawLayer"][2] == 1
        } <= set(BOLTS)
    if shape == "retro":
        assert all(str(t.calls["SetTexture"][4]) == "NEAREST" for t in preview_orbs(m))


def test_the_preview_uses_the_same_sizes_as_real_orbs(env):
    m = build(env)
    m.slash("debug on")
    m.slash("shape globe")
    m.ns.SetLook("pulse", False)
    tick(m)
    widths = [t.width for t in bodies(m)]
    assert widths[:3] == pytest.approx([14 * 1.5] * 3) and widths[3:] == pytest.approx(
        [14 * 1.15 * 1.5] * 2
    )
    m.slash("shape retro")
    m.ns.SetLook("size", 12)  # (a 3 px cell: the old size scale, kept while Retro's rendering is unchanged)
    m.ns.ShapePreview.Sync(m.ns.ShapePreview)
    tick(m)
    assert {t.width for t in bodies(m)} == {
        24
    }  # 12 -> 3 px cells for every orb, rested too
    m.slash("shape crackle")
    tick(m)
    assert bodies(m)[0].width == pytest.approx(14 * 2.0 * 1.15)
    m.slash("shape starlight")
    tick(m)
    assert bodies(m)[0].width == pytest.approx(14 * 2.0)


def test_the_preview_updates_with_size_opacity_pulse_and_colours(env):
    m = build(env)
    show(m)
    m.slash("debug on")
    tick(m)
    assert bodies(m)[0].width == 28 and bodies(m)[0].alpha == 1
    m.stub.slide(ctl(m, "size"), 20)
    tick(m)
    assert bodies(m)[0].width == 40
    m.stub.slide(ctl(m, "opacity"), 50)
    tick(m)
    assert all(t.alpha == pytest.approx(0.5) for t in bodies(m))
    m.slash("shape globe")
    tick(m, 8)
    assert len({round(float(bodies(m)[0].width), 3) for _ in range(1)}) == 1
    widths = []
    for _ in range(10):
        tick(m, 1, 0.03)
        widths.append(bodies(m)[0].width)
    assert max(widths) - min(widths) > 0.5  # breathing
    m.stub.click(ctl(m, "pulse"))
    widths = []
    for _ in range(10):
        tick(m, 1, 0.03)
        widths.append(bodies(m)[0].width)
    assert max(widths) - min(widths) < 1e-6
    m.db.color = m.lua.table_from([0.1, 0.9, 0.2])
    m.opt.Refresh(m.opt)
    tick(m)
    assert [round(float(v), 3) for v in bodies(m)[0].calls["SetVertexColor"].values()][
        :3
    ] == [0.1, 0.9, 0.2]


def test_the_previews_animations_run(env):
    m = build(env)
    m.slash("debug on")
    m.slash("shape starlight")
    tick(m, 1)
    spark = [t for t in preview_orbs(m) if t.calls["SetDrawLayer"][2] == 1][0]
    first = spark.calls["SetRotation"][1]
    tick(m, 3)
    assert spark.calls["SetRotation"][1] != first  # the sparkle spins
    m.slash("shape retro")
    states = set()
    for _ in range(14):
        tick(m, 1)
        states.add(
            bool(
                [t for t in preview_orbs(m) if t.calls["SetDrawLayer"][2] == 1][0].shown
            )
        )
    assert states == {True, False}  # the twinkle blinks
    m.slash("shape crackle")
    seen = set()
    for _ in range(40):
        tick(m, 1, 0.02)
        seen.add(
            path_of([t for t in preview_orbs(m) if t.calls["SetDrawLayer"][2] == 1][0])
        )
    assert len(seen) >= 2


def test_the_previews_ticks_run_only_while_the_panel_is_shown(env):
    m = build(env)
    show(m)
    m.slash("debug on")
    box = m.ns.ShapePreview.box
    assert box.scripts.OnUpdate is not None
    m.opt.panel.scripts.OnHide(m.opt.panel)
    assert box.scripts.OnUpdate is None
    m.slash(
        "shape globe"
    )  # a slash command refreshes the panel even while hidden: the ticks start again
    show(m)
    assert box.scripts.OnUpdate is not None
    m.slash("debug off")
    assert box.scripts.OnUpdate is None


def test_the_preview_draws_with_its_own_textures_not_the_pool(env):
    m = build(env)
    m.slash("debug on")
    tick(m)
    box_textures = {id(t) for t in preview_orbs(m)}
    assert len(box_textures) == 15
    assert m.orbs.Info(m.orbs)[1] == 0  # nothing taken from the orb pool


def test_the_preview_never_errors_before_orbs_or_shapes_are_ready(env):
    m = build(env)
    m.ns.OrbShapes = None
    m.slash("debug on")
    assert m.ns.ShapePreview.box is None
    m.ns.OrbShapes = None
    m.ns.Orbs = None
    m.opt.Refresh(m.opt)
    m.opt.panel.scripts.OnShow(m.opt.panel)
    m.opt.panel.scripts.OnHide(m.opt.panel)
    assert m.ns.ShapePreview.box is None


def test_a_draw_error_is_logged_once_and_never_thrown(env):
    m = build(env)
    m.slash("debug on")
    tick(m)
    m.ns.OrbShapes.by.globe.draw = m.lua.eval("function() error('boom') end")
    m.slash("shape globe")
    tick(m, 5)
    assert (
        sum(
            "PREVIEW_ERR" in str(line)
            for line in (m.db.log.values() if m.db.log else [])
        )
        == 1
    )


# ---------------------------------------------------------------- per-shape blend, pulse and sparkle


def reload_db(env):
    """A /reload: the addon is loaded again over the SavedVariables table that is already there."""
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    return env.G.XPOrbsDB


def test_shape_range_gives_retro_its_own_size_range(env):
    g = make(env)
    retro = g.ns.ShapeRange("retro", "size")
    assert tuple(retro.values()) == (1, 7, 1)
    assert tuple(g.ns.RETRO_SIZE_RANGE.values()) == (1, 7, 1)
    assert tuple(g.ns.ShapeRange("globe", "size").values()) == (8, 32, 1)
    assert tuple(g.ns.ShapeRange("retro", "density").values()) == (25, 400, 25)
    assert tuple(g.ns.ShapeRange("starlight", "opacity").values()) == (20, 100, 5)
    assert g.ns.ShapeRange("retro", "blend") is None
    assert g.ns.ShapeRange("globe", "pulse") is None


def test_every_shape_defaults_carry_all_six_keys(env):
    g = make(env)
    for shape in SHAPES:
        look = g.ns.defaults.shapeLook[shape]
        assert [str(look[k]) for k in ("blend",)] == ["natural"]
        assert look.pulse is True and look.sparkle is True
    assert g.db.blend == "natural" and g.db.sparkle is True and g.db.pulse is True


def test_sanitize_snaps_sizes_per_shape(env):
    db = load_db(
        env,
        {
            "lookRev": 2,
            "shapeLook": {
                "retro": {"size": 50},
                "globe": {"size": 3},
                "starlight": {"size": 2},
                "crackle": {"size": 0},
            },
        },
    )
    assert db.shapeLook.retro.size == 7
    assert db.shapeLook.globe.size == 8
    assert db.shapeLook.starlight.size == 8
    assert db.shapeLook.crackle.size == 8
    db = load_db(env, {"lookRev": 2, "shapeLook": {"retro": {"size": -4}}})
    assert db.shapeLook.retro.size == 1
    db = load_db(env, {"lookRev": 2, "shapeLook": {"retro": {"size": "x"}}})
    assert db.shapeLook.retro.size == 2


def test_the_active_size_of_retro_is_not_snapped_to_the_global_range(env):
    db = load_db(env, {"lookRev": 2, "orbShape": "retro", "shapeLook": {"retro": {"size": 3}}})
    assert db.size == 3 and db.shapeLook.retro.size == 3


def test_bad_blend_pulse_and_sparkle_fall_back_to_the_shape_default(env):
    db = load_db(
        env,
        {
            "lookRev": 2,
            "orbShape": "retro",
            "shapeLook": {
                "retro": {"blend": "glowy", "pulse": "no", "sparkle": 1},
                "globe": {"blend": "solid", "pulse": False, "sparkle": False},
                "crackle": {"blend": 5},
            },
        },
    )
    retro, globe, crackle = (db.shapeLook[s] for s in ("retro", "globe", "crackle"))
    assert (retro.blend, retro.pulse, retro.sparkle) == ("natural", True, True)
    assert (globe.blend, globe.pulse, globe.sparkle) == ("solid", False, False)
    assert crackle.blend == "natural"
    assert (db.blend, db.pulse, db.sparkle) == ("natural", True, True)  # retro's, active


def test_the_active_blend_pulse_and_sparkle_follow_the_current_shape(env):
    db = load_db(
        env,
        {
            "lookRev": 2,
            "orbShape": "globe",
            "pulse": True,
            "shapeLook": {"globe": {"blend": "solid", "pulse": False, "sparkle": False}},
        },
    )
    assert (db.blend, db.pulse, db.sparkle) == ("solid", False, False)


def test_a_global_pulse_flag_that_is_not_a_boolean_is_ignored(env):
    db = load_db(env, {"pulse": "yes"})
    assert db.pulse is True and db.shapeLook.globe.pulse is True


def test_switching_shapes_swaps_blend_pulse_and_sparkle(env):
    g = make(env)
    ns, db = g.ns, g.db
    ns.SetOrbShape("retro")
    ns.SetLook("blend", "solid")
    ns.SetLook("sparkle", False)
    ns.SetOrbShape("globe")
    assert (db.blend, db.pulse, db.sparkle) == ("natural", True, True)
    ns.SetLook("pulse", False)
    ns.SetOrbShape("retro")
    assert (db.blend, db.pulse, db.sparkle) == ("solid", True, False)
    assert db.shapeLook.globe.blend == "natural" and db.shapeLook.globe.pulse is False
    ns.SetOrbShape("globe")
    assert (db.blend, db.pulse, db.sparkle) == ("natural", False, True)


def test_set_look_blend_on_retro_leaves_globe_alone(env):
    g = make(env)
    g.ns.SetOrbShape("retro")
    g.ns.SetLook("blend", "solid")
    assert g.db.blend == "solid" and g.db.shapeLook.retro.blend == "solid"
    assert g.db.shapeLook.globe.blend == "natural"
    assert g.db.shapeLook.starlight.blend == "natural"


def test_look_values_survive_a_reload(env):
    g = make(env)
    g.ns.SetOrbShape("retro")
    g.ns.SetLook("blend", "solid")
    g.ns.SetLook("size", 5)
    db = reload_db(env)
    assert db.orbShape == "retro" and (db.blend, db.size) == ("solid", 5)


# ---------------------------------------------------------------- the one-time look migration


def test_migration_resets_the_unreleased_round_two_values(env):
    db = load_db(
        env,
        {
            "version": 7,
            "orbShape": "retro",
            "shapeLook": {"retro": {"size": 12}, "globe": {"size": 17}},
        },
    )
    assert db.lookRev == 2
    assert db.shapeLook.retro.size == 2 and db.shapeLook.globe.size == 14
    assert db.size == 2


def test_migration_keeps_values_that_are_already_valid(env):
    db = load_db(
        env,
        {"version": 7, "shapeLook": {"retro": {"size": 5}, "globe": {"size": 20}}},
    )
    assert db.shapeLook.retro.size == 5 and db.shapeLook.globe.size == 20


@pytest.mark.parametrize("value", [False, True])
def test_migration_moves_the_global_pulse_to_globe(env, value):
    db = load_db(env, {"version": 7, "pulse": value})
    assert db.shapeLook.globe.pulse is value
    for other in ("starlight", "retro", "crackle"):
        assert db.shapeLook[other].pulse is True


def test_migration_does_not_overwrite_a_globe_pulse_that_is_already_there(env):
    db = load_db(
        env, {"version": 7, "pulse": False, "shapeLook": {"globe": {"pulse": True}}}
    )
    assert db.shapeLook.globe.pulse is True


def test_a_fresh_save_gets_lookrev_and_the_defaults(env):
    db = load_db(env, {})
    assert db.lookRev == 2
    for shape, look in DEFAULT_LOOK.items():
        assert look_of(db, shape) == look


def test_the_migration_runs_once(env):
    db = load_db(env, {"version": 7, "shapeLook": {"globe": {"size": 17}}})
    assert db.shapeLook.globe.size == 14
    db.shapeLook.globe.size = 17  # the player picks 17 on purpose
    db = reload_db(env)
    assert db.shapeLook.globe.size == 17
    db.shapeLook.retro.size = 6
    db = reload_db(env)
    assert db.shapeLook.retro.size == 6 and db.lookRev == 2


def test_reset_keeps_lookrev_so_the_migration_does_not_return(env):
    m = build(env)
    m.slash("reset")
    assert m.db.lookRev == 2
    m.db.shapeLook.globe.size = 17
    db = reload_db(env)
    assert db.shapeLook.globe.size == 17


def test_pulse_off_on_globe_is_globes_alone(env):
    m = build(env)
    m.slash("shape globe")
    m.slash("pulse off")
    assert m.db.shapeLook.globe.pulse is False and m.db.shapeLook.retro.pulse is True
    m.slash("shape retro")
    assert m.db.pulse is True
    m.slash("shape globe")
    assert m.db.pulse is False
