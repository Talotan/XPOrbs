"""db.unknownOrigin: a temporary A/B setting for the "mob position unknown" case (est == "default").

"off" is the single-point start. "wide" (the default) spreads the stream's start over an ellipse that scales with
camera zoom. Only popstream, crossfade and wide bursts with est "default" and kind
other than "other" are affected; mouseover/cursor estimates, other XP and the plain stream never are."""

import math

import pytest
from test_migration import load
from test_p2_wide import a_orbs
from test_v09 import burst, chat_lines, make, restricted_plate, stream_textures

# (seconds before the flight starts, flight-time multiplier) with math.random fixed at 0.5 and flightTime 1.0
TIMELINE = {"popstream": (0.34, 1.0), "crossfade": (0.26, 1.2), "wide": (0.215, 1.1)}
PLATE_STYLES = ["popstream", "crossfade", "wide"]
ORIGIN = (960, 626)
W, H = 1920, 1080
RX, RY = 0.064 * W, 0.04 * H  # at camera zoom 15 (the stub's default)

# Park-Miller: deterministic but spread out, for the tests that look at where a whole burst of orbs starts
LCG = """local s = 12345
math.random = function(a, b)
    s = (s * 16807) % 2147483647
    local r = s / 2147483647
    if a == nil then return r elseif b == nil then return math.floor(r * a) + 1 end
    return a + math.floor(r * (b - a + 1))
end"""


def fire(g, style, setting="off", n=1, **kw):
    g.db.unknownOrigin = setting
    g.db.flightTime = 1.0
    plate = kw.pop("plate", None) or restricted_plate(g, cx=700, cy=400)
    opts = dict(
        plate=plate,
        n=n,
        x=ORIGIN[0],
        y=ORIGIN[1],
        ex=ORIGIN[0],
        ey=ORIGIN[1],
        est="default",
        kind="kill",
        style=style,
    )
    opts.update(kw)
    return burst(g, **opts)


class Clock:
    """Plays a burst forward to absolute times; at_p() goes to a flight position p of orb timeline `style`."""

    def __init__(self, g, style):
        self.g, self.style, self.t = g, style, 0.0

    def to(self, t):
        self.g.stub.tick(t - self.t)
        self.t = t

    def at_p(self, p):
        start, mult = TIMELINE[self.style]
        self.to(start + p * self.g.db.flightTime * mult)


def b_orbs(g):
    """Shown screen-space orb textures (the arrival flash never has a draw layer, so it is skipped)."""
    return [t for t in stream_textures(g) if t.calls["SetDrawLayer"] and t.calls["SetDrawLayer"][2] == 0]


def pos(t):
    return t.points[1][4], t.points[1][5]


def settle(g):
    g.tick(0.05, 80)


def live_recs(g):
    """The driver's live orb records (test-only peek through the upvalues of the OnUpdate script)."""
    return list(
        g.env.lua.eval(
            """function(fn)
                local function up(f, name)
                    local i = 1
                    while true do
                        local n, v = debug.getupvalue(f, i)
                        if not n then return nil end
                        if n == name then return v end
                        i = i + 1
                    end
                end
                local drive = up(fn, "drive")
                local live, n = up(drive, "live"), up(drive, "nLive")
                local out = {}
                for i = 1, n do out[i] = live[i] end
                return out
            end"""
        )(g.orbs.driver.scripts.OnUpdate).values()
    )


def snapshot(g, style, setting, times, **kw):
    """Flat sorted numbers of every shown plate copy and screen copy at each time; the burst then plays out."""
    assert fire(g, style, setting, **kw) in ("pop+stream", "crossfade", "wide", "stream")
    clock, out = Clock(g, style), []
    for t in times:
        clock.to(t)
        rows = sorted((0, t_.alpha, *pos(t_)) for t_ in a_orbs(g)) + sorted(
            (1, t_.alpha, *pos(t_)) for t_ in b_orbs(g)
        )
        out.append([v for row in rows for v in row])
    settle(g)
    return out


def assert_same(a, b):
    assert len(a) == len(b)
    for ra, rb in zip(a, b):
        assert ra == pytest.approx(rb, abs=1e-6)


# ---------------------------------------------------------------- setting, commands, status, report


def test_command_sets_prints_and_rejects_junk(env):
    g = make(env)
    assert g.ns.defaults.unknownOrigin == "wide"
    g.db.unknownOrigin = "wide"  # make() pins "off" on the live db
    g.slash("unknown")
    assert chat_lines(g)[-1].endswith("unknown origin: wide")
    for w in ("off", "wide"):
        g.slash("unknown " + w)
        assert g.db.unknownOrigin == w and chat_lines(g)[-1].endswith(
            "unknown origin: " + w
        )
    g.slash("unknown wide")
    g.slash("unknown sideways")
    assert g.db.unknownOrigin == "wide"
    assert "use off or wide" in chat_lines(g)[-1]


def test_help_mentions_the_command(env):
    g = make(env)
    g.slash("help")
    assert any(
        "/xporbs unknown wide|off" in line for line in chat_lines(g)
    )


@pytest.mark.parametrize("saved", ["wide", "off"])
def test_initdb_keeps_valid_values(env, saved):
    assert load(env, {"version": 5, "unknownOrigin": saved}).unknownOrigin == saved


@pytest.mark.parametrize("junk", ["late", "inplace", "widee", "", 3, True])
def test_initdb_resets_old_variants_and_junk_to_wide(env, junk):
    assert load(env, {"version": 5, "unknownOrigin": junk}).unknownOrigin == "wide"


def test_initdb_defaults_to_wide_when_missing(env):
    assert load(env, {"version": 5}).unknownOrigin == "wide"


def test_removed_variants_are_rejected_by_the_command(env):
    g = make(env)
    g.db.unknownOrigin = "wide"
    for w in ("late", "inplace"):
        g.slash("unknown " + w)
        assert g.db.unknownOrigin == "wide" and "use off or wide" in chat_lines(g)[-1]


def test_reset_restores_wide(env):
    g = make(env)
    g.slash("unknown off")
    g.slash("reset")
    assert g.db.unknownOrigin == "wide"


def test_status_has_its_own_line_and_the_orbs_line_is_unchanged(env):
    g = make(env)
    g.slash("unknown off")
    g.slash("status")
    lines = chat_lines(g)
    assert any(line.endswith("unknown origin: off") for line in lines)
    assert any("orbs: driver=" in line and "unknown" not in line for line in lines)


def test_test_command_reports_the_variant_only_when_applied(env):
    g = make(env)
    g.stub.plates["target"] = restricted_plate(g)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "isTarget": True})
    g.stub.setTargetFrame(250, 900, True)
    g.slash("unknown off")
    g.slash("test 5 wide")
    assert "est=default" in chat_lines(g)[-1] and "unknown=" not in chat_lines(g)[-1]
    settle(g)
    g.slash("unknown wide")
    g.slash("test 5 wide")
    assert chat_lines(g)[-1].endswith("style=wide unknown=wide")
    settle(g)
    g.slash("test 5 stream")  # the plain stream starts at P-hat too, so the spread applies to it
    assert chat_lines(g)[-1].endswith("style=stream unknown=wide")
    settle(g)
    g.slash("test 5 popstream")
    assert chat_lines(g)[-1].endswith("style=popstream unknown=wide")
    assert g.orbs.lastUnknown == "wide"


# ---------------------------------------------------------------- off is today's behaviour


def test_off_keeps_the_small_start_disc_and_the_profile_windows(env):
    g = make(env)
    fire(g, "popstream")
    (o,) = live_recs(g)
    assert math.hypot(o.x0 - ORIGIN[0], o.y0 - ORIGIN[1]) <= 6  # START_RADIUS
    assert (o.sx, o.sy, o.s0, o.s1) == (0, 0, 0, 0)
    settle(g)
    for style, window in (("crossfade", (0, 0)), ("wide", (0.04, 0.20))):  # crossfade has no A -> B window now
        fire(g, style)
        (o,) = live_recs(g)
        assert (o.sx, o.sy, o.s0, o.s1) == (0, 0, window[0], window[1])
        if style == "crossfade":
            assert math.hypot(o.ax - ORIGIN[0], o.ay - ORIGIN[1]) == pytest.approx(32.5126, abs=1e-3)
        settle(g)


@pytest.mark.parametrize("style", PLATE_STYLES)
@pytest.mark.parametrize(
    "kw",
    [{"est": "mouseover"}, {"est": "cursor"}, {"est": None}],
    ids=["mouseover", "cursor", "none"],
)
def test_other_estimates_ignore_the_setting(env, style, kw):
    g = make(env)
    kw = {k: v for k, v in kw.items() if v is not None}
    if "est" not in kw:
        kw["est"] = "other-source"
    times = [0.1, 0.3, 0.5, 0.7, 1.0, 1.4]
    base = snapshot(g, style, "off", times, **kw)
    for setting in ("wide",):
        assert_same(snapshot(g, style, setting, times, **kw), base)
        assert g.orbs.lastUnknown is None


@pytest.mark.parametrize("setting", ["wide"])
def test_kind_other_ignores_the_setting(env, setting):
    g = make(env)
    times = [0.1, 0.4, 0.8, 1.2]
    for style, kw in (("wide", {"kind": "other"}), ("stream", {"kind": "other"})):
        base = snapshot(g, style, "off", times, **kw)
        assert_same(snapshot(g, style, setting, times, **kw), base)
        assert g.orbs.lastUnknown is None


# ---------------------------------------------------------------- wide


@pytest.mark.parametrize("style", ["popstream", "wide"])  # crossfade is exempt: see test_p2_crossfade.py
@pytest.mark.parametrize("setting", ["wide"])
def test_stream_starts_spread_over_the_ellipse(env, style, setting):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    assert fire(g, style, setting, n=40) != "stream"
    recs = live_recs(g)
    assert len(recs) == 40
    norms = [math.hypot((o.x0 - ORIGIN[0]) / RX, (o.y0 - ORIGIN[1]) / RY) for o in recs]
    assert max(norms) <= 1.0 + 1e-9
    assert (
        max(math.hypot(o.x0 - ORIGIN[0], o.y0 - ORIGIN[1]) for o in recs) > 3 * 6
    )  # well past START_RADIUS
    assert (
        0.5 < sum(norms) / len(norms) < 0.85
    )  # uniform over the area: mean radius 2/3, not clustered in the middle
    assert {round(o.x0) for o in recs} != {round(recs[0].x0)}
    assert g.orbs.lastUnknown == setting
    settle(g)


@pytest.mark.parametrize("style", ["wide"])
def test_wide_plate_copy_starts_on_its_normal_ring_and_travels_parallel(env, style):
    g = make(env)
    fire(g, style, "wide")
    (o,) = live_recs(g)
    ring = (o.x0 - o.sx, o.y0 - o.sy)
    assert (o.sx, o.sy) != (0, 0) and math.hypot(o.sx, o.sy) > 50
    # the same ring a non-variant burst gets
    assert math.hypot(ring[0] - ORIGIN[0], ring[1] - ORIGIN[1]) >= 18 - 1e-6
    clock = Clock(g, style)
    start, _ = TIMELINE[style]
    clock.to(start - 0.002)  # the hold has ended: A rests on its ring point
    (a,) = a_orbs(g)
    hold_end = pos(a)
    assert hold_end == pytest.approx(
        (ring[0] - ORIGIN[0], ring[1] - ORIGIN[1]), abs=0.5
    )
    clock.to(start + 0.002)  # flight p = 0+: no jump
    assert pos(a_orbs(g)[0]) == pytest.approx(hold_end, abs=3)
    clock.at_p(0.22 if style == "crossfade" else 0.15)  # both copies visible
    assert b_orbs(g)
    (a,), (b,) = a_orbs(g), b_orbs(g)
    # A is B shifted back by (sx, sy), plus the offset of P-hat the frame subtracts
    assert pos(b)[0] - (pos(a)[0] + ORIGIN[0]) == pytest.approx(o.sx, abs=0.5)
    assert pos(b)[1] - (pos(a)[1] + ORIGIN[1]) == pytest.approx(o.sy, abs=0.5)


@pytest.mark.parametrize("style", ["wide"])
def test_wide_keeps_the_crossfade_window(env, style):
    g = make(env)
    fire(g, style, "wide")
    (o,) = live_recs(g)
    assert (o.s0, o.s1) == ({"wide": (0.04, 0.20)}[style])


@pytest.mark.parametrize("zoom,factor", [(15, 1.0), (5, 2.0), (1, 2.0), (35, 0.5), (50, 0.5), (10, 4 / 3), (25, 2 / 3)])
def test_ellipse_scales_with_camera_zoom(env, zoom, factor):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    g.stub.zoom = zoom
    fire(g, "popstream", "wide", n=60)
    norms = [math.hypot((o.x0 - ORIGIN[0]) / RX, (o.y0 - ORIGIN[1]) / RY) for o in live_recs(g)]
    assert max(norms) <= factor + 1e-9 and max(norms) > factor * 0.85
    settle(g)


def test_unreadable_zoom_leaves_the_ellipse_unscaled(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    g.stub.zoom = g.stub.SECRET
    fire(g, "popstream", "wide", n=60)
    norms = [math.hypot((o.x0 - ORIGIN[0]) / RX, (o.y0 - ORIGIN[1]) / RY) for o in live_recs(g)]
    assert max(norms) <= 1.0 + 1e-9 and max(norms) > 0.85
    settle(g)


def test_plain_stream_spreads_over_the_scaled_ellipse_or_starts_at_one_point(env):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False)
    g.stub.zoom = 5  # factor 2
    assert fire(g, "stream", "wide", n=60,) == "stream"
    recs = live_recs(g)
    norms = [math.hypot((o.x0 - ORIGIN[0]) / RX, (o.y0 - ORIGIN[1]) / RY) for o in recs]
    assert max(norms) <= 2.0 + 1e-9 and max(norms) > 1.7 and g.orbs.lastUnknown == "wide"
    settle(g)
    fire(g, "stream", "off", n=20)
    assert max(math.hypot(o.x0 - ORIGIN[0], o.y0 - ORIGIN[1]) for o in live_recs(g)) <= 6
    assert g.orbs.lastUnknown is None
    settle(g)
    fire(g, "stream", "wide", n=20, est="mouseover")  # a located mob: no spread
    assert g.orbs.lastUnknown is None
    settle(g)


# ---------------------------------------------------------------- pools and the driver


@pytest.mark.parametrize("setting", ["wide"])
@pytest.mark.parametrize("style", PLATE_STYLES)
def test_everything_is_idle_after_a_variant_burst(env, style, setting):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False, trail=True)
    fire(g, style, setting, n=12)
    settle(g)
    assert g.orbs.Info(g.orbs)[1] == 0
    free, created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert free == created and alive == 0 and xf == 0
    assert g.stub.updaters() == 0
    assert g.stub.restrictedHits == 0


def test_pooled_records_do_not_leak_a_variant_into_the_next_burst(env):
    g = make(env)
    fire(g, "wide", "wide")
    settle(g)
    fire(g, "popstream", "off")
    (o,) = live_recs(g)
    assert (o.sx, o.sy, o.s0, o.s1) == (0, 0, 0, 0)
    settle(g)


@pytest.mark.parametrize("style", ["popstream", "wide", "crossfade"])
def test_driver_allocates_nothing_per_frame_in_a_variant_burst(env, style):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False, trail=True)
    g.db.flightTime = 1.5
    g.db.unknownOrigin = "wide"
    fire(g, style, "wide", n=20)
    g.db.flightTime = 1.5
    g.tick(0.016, 3)
    assert g.orbs.Info(g.orbs)[1] > 15
    grown = g.env.lua.eval(
        """function(driver, frames, dt)
            local fm = getmetatable(UIParent).__index
            local noop = function() end
            for _, n in ipairs({ "SetPoint", "ClearAllPoints", "SetSize", "SetRotation", "SetVertexColor", "SetTexture",
                "SetBlendMode", "SetDrawLayer" }) do
                fm[n] = noop
            end
            local fn = driver.scripts.OnUpdate
            fn(driver, dt)
            collectgarbage("collect")
            collectgarbage("stop")
            local c0 = collectgarbage("count")
            for _ = 1, frames do
                fn(driver, dt)
            end
            local c1 = collectgarbage("count")
            collectgarbage("restart")
            return c1 - c0
        end"""
    )(g.orbs.driver, 300, 0.002)
    assert g.orbs.Info(g.orbs)[1] > 0
    assert grown < 4.0, grown
