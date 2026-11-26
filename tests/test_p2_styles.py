"""Schema 6: three kill styles. Popstream (sub-choice Nameplate = the 1.1 popstream, Direct = the P2 "streampop"),
Crossfade, Direct Stream ("stream"). The P2 wide burst is gone: a save holding it becomes Popstream (Nameplate) with
Zoom-scaled spread on. That tickbox is db.zoomSpread (/xporbs wide on|off): the spawn spread of located orbs scales
with camera zoom. The unknown-position oval (db.unknownOrigin, /xporbs unknown) is separate and never follows it."""

import math

import pytest
from test_m5 import build, ctl, show
from test_migration import load
from test_v09 import (
    OWN,
    burst,
    chat_lines,
    kill_with_secret_pos_plate,
    make,
    pop_textures,
    restricted_plate,
    stream_textures,
)


def a_orbs(g):
    return [t for t in pop_textures(g) if t.calls["SetDrawLayer"][2] == 0 and t.shown]


def b_orbs(g):
    return [t for t in stream_textures(g) if t.calls["SetDrawLayer"][2] == 0]


def recs(g):
    from test_p2_unknown import live_recs

    return live_recs(g)


def seeded(env):
    """Install the deterministic math.random BEFORE make(): the addon captures math.random when it loads."""
    from test_p2_unknown import LCG

    env.lua.execute(LCG)


# ---------------------------------------------------------------- migration (schema 5 -> 6)


@pytest.mark.parametrize(
    "saved, style, mode",
    [
        ("popstream", "popstream", "nameplate"),
        ("streampop", "popstream", "direct"),
        ("wide", "popstream", "nameplate"),
        ("mob", "popstream", "nameplate"),
        ("crossfade", "crossfade", "nameplate"),
        ("stream", "stream", "nameplate"),
        ("bogus", "popstream", "nameplate"),
        (None, "popstream", "nameplate"),
    ],
)
def test_v5_styles_map_to_the_three_style_scheme(env, saved, style, mode):
    old = {"version": 5, "unknownOrigin": "off"}
    if saved is not None:
        old["style"] = saved
    db = load(env, old)
    assert (db.version, db.style, db.popMode) == (7, style, mode)
    assert db.unknownOrigin == "off"  # the migration never touches the unknown-position setting
    assert db.zoomSpread is True  # new key, on by default (and the old wide burst maps to it on)


def test_the_migration_turns_zoom_spread_on_for_the_old_wide_burst(env):
    db = load(env, {"version": 6, "style": "popstream", "zoomSpread": False})
    assert db.zoomSpread is False  # a v6 save keeps its choice
    db = load(env, {"version": 6, "style": "wide", "zoomSpread": False})
    assert (db.style, db.zoomSpread) == ("popstream", True)
    db = load(env, {"version": 6, "zoomSpread": "yes"})
    assert db.zoomSpread is True  # junk -> the default


def test_a_v6_save_keeps_its_choices_and_old_names_are_still_mapped(env):
    db = load(
        env,
        {
            "version": 6,
            "style": "popstream",
            "popMode": "direct",
            "unknownOrigin": "off",
        },
    )
    assert (db.style, db.popMode, db.unknownOrigin) == ("popstream", "direct", "off")
    db = load(env, {"version": 6, "style": "streampop", "popMode": "nameplate"})
    assert (db.style, db.popMode) == (
        "popstream",
        "direct",
    )  # a hand-edited old name maps like the migration
    db = load(env, {"version": 6, "popMode": "sideways"})
    assert db.popMode == "nameplate"


def test_defaults(env):
    db = load(env, {})
    assert (db.style, db.popMode, db.unknownOrigin, db.zoomSpread, db.version) == (
        "popstream",
        "nameplate",
        "wide",
        True,
        7,
    )


def test_render_style_resolves_every_name(env):
    db = load(env, {})
    rs = env.ns.RenderStyle
    assert (
        db
        and rs("popstream", "nameplate") == "popstream"
        and rs("popstream", "direct") == "streampop"
    )
    assert (
        rs("streampop", "nameplate") == "streampop"
        and rs("wide", "direct") == "popstream"
    )
    assert (
        rs("crossfade", "direct"),
        rs("stream", "direct"),
        rs("bogus", "direct"),
    ) == (
        "crossfade",
        "stream",
        "streampop",  # unknown -> the default style, which honours the popMode
    )


# ---------------------------------------------------------------- slash commands


@pytest.mark.parametrize(
    "cmd, style, mode, label",
    [
        (
            "style popstream nameplate",
            "popstream",
            "nameplate",
            "Popstream (Nameplate)",
        ),
        ("style popstream direct", "popstream", "direct", "Popstream (Direct)"),
        ("style crossfade", "crossfade", "nameplate", "Crossfade"),
        ("style stream", "stream", "nameplate", "Direct Stream"),
        ("style directstream", "stream", "nameplate", "Direct Stream"),
        ("style wide", "popstream", "nameplate", "Popstream (Nameplate)"),
        ("style mob", "popstream", "nameplate", "Popstream (Nameplate)"),
    ],
)
def test_style_command_and_its_aliases(env, cmd, style, mode, label):
    m5 = build(env)
    m5.db.unknownOrigin, m5.db.zoomSpread = "off", False
    m5.slash(cmd)
    assert (m5.db.style, m5.db.popMode) == (style, mode)
    assert m5.say()[-1].endswith("kill style: " + label)
    assert m5.db.zoomSpread is (cmd in ("style wide", "style mob"))
    assert m5.db.unknownOrigin == "off"


def test_style_popstream_alone_keeps_the_sub_choice_and_bad_combinations_change_nothing(
    env,
):
    m5 = build(env)
    m5.slash("style popstream direct")
    m5.slash("style stream")
    m5.slash("style popstream")
    assert (m5.db.style, m5.db.popMode) == ("popstream", "direct")
    for bad in ("style crossfade direct", "style popstream sideways", "style bogus"):
        m5.slash(bad)
        assert (m5.db.style, m5.db.popMode) == ("popstream", "direct")
        assert "use popstream [nameplate|direct], crossfade or stream" in m5.say()[-1]


def test_wide_command_writes_zoom_spread_and_never_the_unknown_setting(env):
    m5 = build(env)
    show(m5)
    m5.db.unknownOrigin = "wide"
    m5.slash("wide off")
    assert m5.db.zoomSpread is False and m5.say()[-1].endswith("zoom-scaled spread: off")
    assert ctl(m5, "zoomSpread").checked is False and m5.db.unknownOrigin == "wide"
    m5.slash("wide on")
    assert m5.db.zoomSpread is True and ctl(m5, "zoomSpread").checked is True
    m5.slash("wide sideways")
    assert m5.db.zoomSpread is True and "use on or off" in m5.say()[-1]
    m5.slash("unknown off")
    assert m5.db.unknownOrigin == "off" and m5.db.zoomSpread is True
    assert m5.say()[-1].endswith("unknown origin: off")
    assert ctl(m5, "zoomSpread").checked is True


def test_help_describes_each_style(env):
    m5 = build(env)
    m5.slash("help")
    text = "\n".join(m5.say())
    assert "/xporbs style popstream [nameplate|direct] | crossfade | stream" in text
    assert (
        "Popstream (Nameplate): a pop on the nameplate, then a stream from the estimated mob position (pop needs the nameplate)"
        in text
    )
    assert (
        "Popstream (Direct): a pop at the estimated mob position that flows into the stream (no nameplate)"
        in text
    )
    assert "Crossfade: a pop on the nameplate" in text
    assert (
        "Direct Stream: a plain stream from the estimated mob position (no pop, no nameplate)"
        in text
    )
    assert "/xporbs wide on|off - zoom-scaled spread" in text
    assert "/xporbs unknown wide|off - where orbs start when the mob's position is unknown" in text


def test_status_names_the_style_and_wide(env):
    g = make(env)
    g.slash("style popstream direct")
    g.slash("wide off")
    g.slash("status")
    lines = chat_lines(g)
    assert any(line.endswith("kill style: Popstream (Direct), zoom-scaled spread: off") for line in lines)
    assert any(line.endswith("unknown origin: off") for line in lines)  # make() pins "off"
    assert any("orbs: driver=" in line and "style=streampop" in line for line in lines)


def test_test_command_tokens(env):
    g = make(env)
    g.stub.plates["target"] = restricted_plate(g)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "isTarget": True})
    g.stub.setTargetFrame(250, 900, True)
    for tok, end in (
        ("popstream nameplate", "pop=yes stream=estimate style=popstream/nameplate"),
        ("nameplate", "pop=yes stream=estimate style=popstream/nameplate"),
        ("popstream direct", "pop=no stream=estimate style=popstream/direct"),
        ("wide", "pop=yes stream=estimate style=popstream/nameplate"),
        ("crossfade", "pop=no stream=estimated style=crossfade"),
        ("stream", "pop=no stream=estimate style=stream"),
    ):
        g.slash("test 5 " + tok)
        assert chat_lines(g)[-1].endswith(end), tok
        g.tick(0.05, 80)
    g.db.popMode = "direct"
    g.slash("test 5 popstream")
    assert chat_lines(g)[-1].endswith(
        "style=popstream/direct"
    )  # popstream alone follows the saved sub-choice
    assert (
        g.db.style == "popstream" and g.db.popMode == "direct"
    )  # the test never writes the settings


# ---------------------------------------------------------------- kills: which styles get the nameplate


@pytest.mark.parametrize(
    "style, mode, plate",
    [
        ("popstream", "nameplate", True),
        ("popstream", "direct", False),
        ("crossfade", "nameplate", True),
        ("stream", "nameplate", False),
    ],
)
def test_a_kill_passes_the_plate_only_to_the_nameplate_styles(env, style, mode, plate):
    g = make(env)
    g.fake_orbs_on()
    g.db.style, g.db.popMode = style, mode
    p = kill_with_secret_pos_plate(g)
    (b,) = g.bursts()
    assert OWN(g, b["plate"], p) if plate else b["plate"] is None
    assert g.has_log("origin=estimate plate=" + ("yes" if plate else "no"))


# ---------------------------------------------------------------- the options panel


def test_style_section_rows_and_sub_radios(env):
    m5 = build(env)
    show(m5)
    o = m5.opt
    assert [
        o.rows[k].points[1][5]
        for k in ("style_popstream", "popMode_nameplate", "popMode_direct")
    ] == [
        -144,
        -186,
        -228,  # per-tab y: the Flight tab's first row is 8
    ]
    for pm, x in (("nameplate", 70), ("direct", 70)):
        rb = ctl(m5, "popMode_" + pm)
        assert (
            rb.template == "UIRadioButtonTemplate" and rb.points[1][4] == x
        )  # indented one step under Kill style (LABEL_X + 16 + 24 - 2)
        assert o.descs[pm].points[1][4] == 96 - 32 and o.descs[pm].width == 450
    assert (
        o.descs["direct"].text
        == "Pop and stream from the estimated position. No nameplate needed."
    )
    assert ctl(m5, "style_popstream").checked and ctl(m5, "popMode_nameplate").checked
    assert not ctl(m5, "popMode_direct").checked
    m5.stub.click(ctl(m5, "popMode_direct"))
    assert (
        m5.db.popMode == "direct"
        and ctl(m5, "popMode_direct").checked
        and not ctl(m5, "popMode_nameplate").checked
    )


def test_sub_radios_dim_unless_popstream_and_the_spread_never_dims(env):
    m5 = build(env)
    show(m5)
    rows, o = m5.opt.rows, m5.opt
    assert rows["popMode_direct"].alpha == 1 and ctl(m5, "popMode_direct").IsEnabled(ctl(m5, "popMode_direct"))
    m5.stub.click(ctl(m5, "style_crossfade"))
    assert rows["popMode_direct"].alpha == pytest.approx(0.4)
    assert o.descs["direct"].alpha == pytest.approx(0.55)  # dimmed descriptions stay readable
    # dimmed but clickable: picking a sub-choice also picks Popstream
    assert ctl(m5, "popMode_direct").IsEnabled(ctl(m5, "popMode_direct"))
    assert rows["zoomSpread"].alpha in (None, 1) and ctl(m5, "zoomSpread").IsEnabled(ctl(m5, "zoomSpread"))
    m5.stub.click(ctl(m5, "style_stream"))
    assert rows["popMode_nameplate"].alpha == pytest.approx(0.4) and rows["zoomSpread"].alpha in (None, 1)
    m5.stub.click(ctl(m5, "popMode_direct"))
    assert (m5.db.style, m5.db.popMode) == ("popstream", "direct")
    assert ctl(m5, "style_popstream").checked and not ctl(m5, "style_stream").checked
    assert rows["popMode_nameplate"].alpha == 1


def test_spread_checkbox_label_position_and_reset(env):
    from test_m5 import panel_texts

    m5 = build(env)
    show(m5)
    texts = panel_texts(m5)
    assert "Zoom-scaled spread" in texts and "Wide start" not in texts
    assert m5.opt.descs["zoomSpread"].text == "Wider when zoomed in, tighter when zoomed out."
    cb = ctl(m5, "zoomSpread")
    assert cb.checked is True and m5.opt.rows["zoomSpread"].points[1][5] == -380
    assert m5.opt.descs["zoomSpread"].points[1][5] == -(380 - 134 + 28)  # box-relative
    m5.stub.click(cb)
    assert m5.db.zoomSpread is False and cb.checked is False
    btn = m5.opt.resets["zoomSpread"]
    assert btn.shown
    m5.stub.click(btn)
    assert m5.db.zoomSpread is True and cb.checked is True and not btn.shown
    assert "unknownOrigin" not in [k for k in m5.opt.controls]  # no Options control for the unknown oval


# ---------------------------------------------------------------- zoom-scaled spread vs the unknown-position oval

ORIGIN = (960, 626)


def fire_known(g, style, n, **kw):
    from test_v09 import burst as _burst

    opts = {
        "plate": restricted_plate(g, cx=700, cy=400),
        "n": n,
        "x": ORIGIN[0],
        "y": ORIGIN[1],
        "ex": ORIGIN[0],
        "ey": ORIGIN[1],
        "est": "mouseover",  # a located mob
        "kind": "kill",
        "style": style,
    }
    opts.update(kw)
    return _burst(g, **opts)


def max_dist(recs, ax="x0", ay="y0"):
    return max(math.hypot(getattr(o, ax) - ORIGIN[0], getattr(o, ay) - ORIGIN[1]) for o in recs)


@pytest.mark.parametrize("zoom, f", [(15, 1.0), (5, 2.0), (35, 0.5), (10, 4 / 3)])
def test_direct_stream_start_disc_scales_with_zoom(env, zoom, f):
    seeded(env)
    g = make(env, fixed_random=False)
    g.stub.zoom = zoom
    g.db.zoomSpread = True
    assert fire_known(g, "stream", 40, plate=None) == "stream"
    d = max_dist(recs(g))
    assert 6 * f * 0.85 < d <= 6 * f + 1e-9  # START_RADIUS 6 x the zoom factor
    g.tick(0.05, 80)
    g.db.zoomSpread = False
    fire_known(g, "stream", 40, plate=None)
    d = max_dist(recs(g))
    assert 6 * 0.85 < d <= 6 + 1e-9  # off: the fixed spread
    g.tick(0.05, 80)


@pytest.mark.parametrize("zoom, f", [(15, 1.0), (5, 2.0), (35, 0.5)])
def test_direct_pop_ring_scales_with_zoom(env, zoom, f):
    seeded(env)
    g = make(env, fixed_random=False)
    g.stub.zoom = zoom
    for on, k in ((True, f), (False, 1.0)):
        g.db.zoomSpread = on
        assert fire_known(g, "streampop", 30) == "streampop"
        ds = [math.hypot(o.ringX - ORIGIN[0], o.ringY - ORIGIN[1]) for o in recs(g)]
        assert min(ds) >= 25 * k - 1e-6 and max(ds) <= 46 * k + 1e-6  # ring 25-46 px x the factor
        g.tick(0.05, 80)


@pytest.mark.parametrize("zoom, f", [(15, 1.0), (5, 2.0), (35, 0.5)])
def test_crossfade_plate_ring_scales_with_zoom(env, zoom, f):
    seeded(env)
    g = make(env, fixed_random=False)
    g.stub.zoom = zoom
    for on, k in ((True, f), (False, 1.0)):
        g.db.zoomSpread = on
        assert fire_known(g, "crossfade", 30) == "crossfade"
        ds = [math.hypot(o.ringX - ORIGIN[0], o.ringY - ORIGIN[1]) for o in recs(g)]
        assert min(ds) >= (24 - 8) * k - 1e-6 and max(ds) <= (36 + 8) * k + 1e-6  # ring 24-36 + drift 0-8
        assert max(ds) > 30 * k  # really spread to the scaled size, not stuck at the fixed one
        g.tick(0.05, 80)


@pytest.mark.parametrize("zoom, f", [(5, 2.0), (35, 0.5), (10, 4 / 3)])
def test_nameplate_pop_scales_with_zoom_and_is_identity_at_15(env, zoom, f):
    from test_v010 import pop_orb_offset

    g = make(env)  # math.random fixed at 0.5: the same ring point every burst

    def offset(z, on):
        g.stub.zoom, g.db.zoomSpread = z, on
        burst(g, plate=restricted_plate(g), n=1, x=300, y=300, ex=300, ey=300, kind="kill", est="mouseover")
        g.stub.tick(0.1)  # mid-bloom, before the exit launch: the offset is ring + drift, both scaled
        out = pop_orb_offset(g)
        g.tick(0.05, 80)  # play it out so the next burst starts clean
        return out

    base = offset(15, True)
    assert offset(15, False) == pytest.approx(base)  # zoom 15 = today's size
    assert offset(zoom, False) == pytest.approx(base)  # off: fixed whatever the zoom
    scaled = offset(zoom, True)
    assert scaled == pytest.approx((base[0] * f, base[1] * f))


@pytest.mark.parametrize("spread", [True, False])
def test_unknown_position_stays_wide_whatever_the_tickbox_says(env, spread):
    from test_p2_unknown import RX, RY

    seeded(env)
    g = make(env, fixed_random=False)
    g.stub.zoom = 5  # factor 2
    g.db.zoomSpread = spread
    g.db.unknownOrigin = "wide"
    for style in ("stream", "popstream"):
        fire_known(g, style, 60, est="default")
        norms = [math.hypot((o.x0 - ORIGIN[0]) / RX, (o.y0 - ORIGIN[1]) / RY) for o in recs(g)]
        assert max(norms) <= 2.0 + 1e-9 and max(norms) > 1.7  # the zoom-scaled oval, as before
        assert g.orbs.lastUnknown == "wide"
        g.tick(0.05, 80)


def test_the_style_reset_restores_style_and_sub_choice(env):
    m5 = build(env)
    show(m5)
    m5.stub.click(ctl(m5, "popMode_direct"))
    btn = m5.opt.resets["style"]
    assert btn.shown
    m5.stub.click(btn)
    assert (m5.db.style, m5.db.popMode) == ("popstream", "nameplate") and not btn.shown


# ---------------------------------------------------------------- crossfade keeps its own timings (from the old file)


def test_crossfade_keeps_its_own_timings(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    assert (
        burst(
            g,
            plate=plate,
            n=1,
            x=300,
            y=300,
            ex=700,
            ey=500,
            kind="kill",
            style="crossfade",
        )
        == "crossfade"
    )
    g.stub.tick(0.02 + 0.24 - 0.001)  # delay 0.5 * 0.04 birth window, XF_HOLD
    (a,) = a_orbs(g)
    assert math.hypot(a.points[1][4], a.points[1][5]) == pytest.approx(
        32.5126, abs=0.01
    )  # ring 30 + 4 px drift


def test_crossfade_orbs_have_no_drift_and_narrow_jitter(env):
    seeded(env)
    g = make(env, fixed_random=False)
    plate = restricted_plate(g, cx=700, cy=400)
    assert (
        burst(
            g,
            plate=plate,
            n=10,
            x=300,
            y=300,
            ex=700,
            ey=500,
            kind="kill",
            style="crossfade",
        )
        == "crossfade"
    )
    for o in recs(g):
        # bloom 0.24 + leave start 0..0.15 + leave 0.26 + gap 0.10; B flies flightTime * 0.40 * (0.94..1.06)
        assert (
            o.profile is not None
            and 0.60 <= o.hold <= 0.75
            and o.hold == pytest.approx(0.60 + o.leaveStart)
        )
        assert (
            0.94 * 0.40 * g.db.flightTime - 1e-9
            <= o.dur
            <= 1.06 * 0.40 * g.db.flightTime + 1e-9
        )


def test_other_kind_is_a_plain_stream(env):
    g = make(env)
    opts = dict(
        n=3, x=300, y=300, kind="other", style="crossfade", plate=restricted_plate(g)
    )
    assert burst(g, **opts) == "stream"


def test_no_plate_is_a_screen_anchored_crossfade(env):
    g = make(env)
    assert burst(g, n=3, x=300, y=300, kind="kill", style="crossfade") == "crossfade"
