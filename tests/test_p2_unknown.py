"""db.unknownOrigin: a temporary A/B setting for the "mob position unknown" case (est == "default").

"off" is today's behaviour. "wide" spreads the stream's start over an ellipse, "late" also reveals the screen copy late,
"inplace" also fades the plate copy where it is. Only popstream, crossfade and mob bursts with est "default" and kind
other than "other" are affected; mouseover/cursor estimates, other XP and the plain stream never are."""

import math

import pytest
from test_migration import load
from test_p2_mob import a_orbs
from test_v09 import burst, chat_lines, make, restricted_plate, stream_textures

# (seconds before the flight starts, flight-time multiplier) with math.random fixed at 0.5 and flightTime 1.0
TIMELINE = {"popstream": (0.34, 1.0), "crossfade": (0.26, 1.2), "mob": (0.335, 1.1)}
PLATE_STYLES = ["popstream", "crossfade", "mob"]
ORIGIN = (960, 626)
W, H = 1920, 1080
RX, RY = 0.08 * W, 0.05 * H
FROM, TO = 0.25, 0.40

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
    assert fire(g, style, setting, **kw) in ("pop+stream", "crossfade", "mob", "stream")
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
    assert g.db.unknownOrigin == "off"
    g.slash("unknown")
    assert chat_lines(g)[-1].endswith("unknown origin: off")
    for w in ("wide", "late", "inplace", "off"):
        g.slash("unknown " + w)
        assert g.db.unknownOrigin == w and chat_lines(g)[-1].endswith(
            "unknown origin: " + w
        )
    g.slash("unknown wide")
    g.slash("unknown sideways")
    assert g.db.unknownOrigin == "wide"
    assert "use off, wide, late or inplace" in chat_lines(g)[-1]


def test_help_mentions_the_command(env):
    g = make(env)
    g.slash("help")
    assert any(
        "/xporbs unknown off|wide|late|inplace" in line for line in chat_lines(g)
    )


@pytest.mark.parametrize("saved", ["wide", "late", "inplace", "off"])
def test_initdb_keeps_valid_values(env, saved):
    assert load(env, {"version": 5, "unknownOrigin": saved}).unknownOrigin == saved


@pytest.mark.parametrize("junk", ["widee", "", 3, True])
def test_initdb_resets_junk_to_off(env, junk):
    assert load(env, {"version": 5, "unknownOrigin": junk}).unknownOrigin == "off"


def test_initdb_defaults_to_off_when_missing(env):
    assert load(env, {"version": 5}).unknownOrigin == "off"


def test_reset_restores_off(env):
    g = make(env)
    g.slash("unknown late")
    g.slash("reset")
    assert g.db.unknownOrigin == "off"


def test_status_has_its_own_line_and_the_orbs_line_is_unchanged(env):
    g = make(env)
    g.slash("unknown inplace")
    g.slash("status")
    lines = chat_lines(g)
    assert any(line.endswith("unknown origin: inplace") for line in lines)
    assert any("orbs: driver=" in line and "unknown" not in line for line in lines)


def test_test_command_reports_the_variant_only_when_applied(env):
    g = make(env)
    g.stub.plates["target"] = restricted_plate(g)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "isTarget": True})
    g.stub.setTargetFrame(250, 900, True)
    g.slash("test 5 mob")
    assert "est=default" in chat_lines(g)[-1] and "unknown=" not in chat_lines(g)[-1]
    settle(g)
    g.slash("unknown late")
    g.slash("test 5 mob")
    assert chat_lines(g)[-1].endswith("style=mob unknown=late")
    settle(g)
    g.slash("test 5 stream")  # no plate-space copy: the setting does not apply
    assert chat_lines(g)[-1].endswith("style=stream")
    settle(g)
    g.slash("test 5 popstream")
    assert chat_lines(g)[-1].endswith("style=popstream unknown=late")
    assert g.orbs.lastUnknown == "late"


# ---------------------------------------------------------------- off is today's behaviour


def test_off_keeps_the_small_start_disc_and_the_profile_windows(env):
    g = make(env)
    fire(g, "popstream")
    (o,) = live_recs(g)
    assert math.hypot(o.x0 - ORIGIN[0], o.y0 - ORIGIN[1]) <= 6  # START_RADIUS
    assert (o.sx, o.sy, o.s0, o.s1, o.ip) == (0, 0, 0, 0, False)
    settle(g)
    for style, window in (("crossfade", (0.12, 0.30)), ("mob", (0.04, 0.20))):
        fire(g, style)
        (o,) = live_recs(g)
        assert (o.sx, o.sy, o.s0, o.s1, o.ip) == (0, 0, window[0], window[1], False)
        if style == "crossfade":
            assert math.hypot(o.x0 - ORIGIN[0], o.y0 - ORIGIN[1]) == pytest.approx(
                18
            )  # XF_BLOOM_R
        settle(g)


def test_off_crossfade_mid_window_is_equal_power(env):
    g = make(env)
    fire(g, "crossfade")
    Clock(g, "crossfade").at_p(0.21)
    assert a_orbs(g)[0].alpha == pytest.approx(math.sqrt(0.5), abs=0.02)
    assert b_orbs(g)[0].alpha == pytest.approx(math.sqrt(0.5), abs=0.02)


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
    for setting in ("wide", "late", "inplace"):
        assert_same(snapshot(g, style, setting, times, **kw), base)
        assert g.orbs.lastUnknown is None


@pytest.mark.parametrize("setting", ["wide", "late", "inplace"])
def test_kind_other_and_the_plain_stream_ignore_the_setting(env, setting):
    g = make(env)
    times = [0.1, 0.4, 0.8, 1.2]
    for style, kw in (("mob", {"kind": "other"}), ("stream", {})):
        base = snapshot(g, style, "off", times, **kw)
        assert_same(snapshot(g, style, setting, times, **kw), base)
        assert g.orbs.lastUnknown is None


# ---------------------------------------------------------------- wide


@pytest.mark.parametrize("style", PLATE_STYLES)
@pytest.mark.parametrize("setting", ["wide", "late", "inplace"])
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


@pytest.mark.parametrize("style", ["crossfade", "mob"])
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


@pytest.mark.parametrize("style", ["crossfade", "mob"])
def test_wide_keeps_the_crossfade_window(env, style):
    g = make(env)
    fire(g, style, "wide")
    (o,) = live_recs(g)
    assert (o.s0, o.s1) == ({"crossfade": (0.12, 0.30), "mob": (0.04, 0.20)}[style])
    assert o.ip is False


# ---------------------------------------------------------------- late


def test_late_popstream_reveals_the_stream_late_and_leaves_the_pop_alone(env):
    g = make(env)
    base = snapshot(g, "popstream", "off", [0.1, 0.25, 0.34])
    fire(g, "popstream", "late")
    clock = Clock(g, "popstream")
    for t, off in zip([0.1, 0.25, 0.34], base):
        clock.to(t)
        pops = sorted((0, t_.alpha, *pos(t_)) for t_ in a_orbs(g))
        assert [v for row in pops for v in row] == pytest.approx(
            off[: len(pops) * 4], abs=1e-6
        )  # the pop: same
    clock.at_p(FROM - 0.01)
    assert b_orbs(g) == []
    clock.at_p(FROM + 0.075)  # half way: smoothstep is exactly 0.5
    assert b_orbs(g)[0].alpha == pytest.approx(0.5, abs=0.02)
    clock.at_p(TO + 0.01)
    assert b_orbs(g)[0].alpha == pytest.approx(1.0, abs=1e-6)
    settle(g)


@pytest.mark.parametrize("style", ["crossfade", "mob"])
def test_late_moves_the_crossfade_window(env, style):
    g = make(env)
    fire(g, style, "late")
    (o,) = live_recs(g)
    assert (o.s0, o.s1) == (FROM, TO) and o.ip is False
    clock = Clock(g, style)
    clock.at_p(FROM - 0.02)
    assert b_orbs(g) == [] and a_orbs(g)[0].alpha == pytest.approx(1.0, abs=1e-6)
    clock.at_p((FROM + TO) / 2)
    assert a_orbs(g)[0].alpha == pytest.approx(math.sqrt(0.5), abs=0.02)
    assert b_orbs(g)[0].alpha == pytest.approx(math.sqrt(0.5), abs=0.02)
    clock.at_p(TO + 0.02)
    assert a_orbs(g) == [] and b_orbs(g)[0].alpha == pytest.approx(1.0, abs=1e-6)
    settle(g)


# ---------------------------------------------------------------- inplace


@pytest.mark.parametrize("style", ["crossfade", "mob"])
def test_inplace_plate_copy_stays_put_and_fades_out_by_the_reveal(env, style):
    g = make(env)
    fire(g, style, "inplace")
    (o,) = live_recs(g)
    assert o.ip is True and (o.s0, o.s1) == (FROM, TO)
    clock = Clock(g, style)
    clock.to(TIMELINE[style][0] - 0.002)
    (a,) = a_orbs(g)
    rest = pos(a)
    for p in (0.02, 0.08, 0.15, 0.2):
        clock.at_p(p)
        (a,) = a_orbs(g)
        assert pos(a) == pytest.approx(rest, abs=0.05)  # fixed on the plate
        assert a.alpha == pytest.approx(1 - p / FROM, abs=0.03)
        assert b_orbs(g) == []
    clock.at_p(FROM + 0.005)
    assert a_orbs(g) == []  # fully faded by the time the reveal starts
    clock.at_p((FROM + TO) / 2)
    assert a_orbs(g) == []
    assert b_orbs(g)[0].alpha == pytest.approx(0.5, abs=0.02)
    clock.at_p(TO + 0.02)
    assert b_orbs(g)[0].alpha == pytest.approx(1.0, abs=1e-6)
    settle(g)


def test_inplace_popstream_pop_has_no_exit_vector_and_the_stream_is_late(env):
    g = make(env)
    ends = {}
    for setting in ("late", "inplace"):
        fire(g, "popstream", setting, n=4)
        g.stub.tick(0.495)  # pop p = 0.9, well into the exit
        pops = [pos(t_) for t_ in a_orbs(g)]
        ends[setting] = (
            sum(p[0] for p in pops) / len(pops),
            sum(p[1] for p in pops) / len(pops),
        )
        settle(g)
    # late keeps today's drift: 140 px * q^2 (q = 0.818) along the exit vector; inplace has none
    drift = math.hypot(
        ends["late"][0] - ends["inplace"][0], ends["late"][1] - ends["inplace"][1]
    )
    assert drift == pytest.approx(140 * ((0.9 - 0.45) / 0.55) ** 2, abs=1.0)
    fire(g, "popstream", "inplace")
    clock = Clock(g, "popstream")
    clock.at_p(FROM - 0.01)
    assert b_orbs(g) == []
    clock.at_p(TO + 0.01)
    assert b_orbs(g)[0].alpha == pytest.approx(1.0, abs=1e-6)
    settle(g)


# ---------------------------------------------------------------- pools and the driver


@pytest.mark.parametrize("setting", ["wide", "late", "inplace"])
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
    fire(g, "mob", "inplace")
    settle(g)
    fire(g, "popstream", "off")
    (o,) = live_recs(g)
    assert (o.sx, o.sy, o.s0, o.s1, o.ip) == (0, 0, 0, 0, False)
    settle(g)


@pytest.mark.parametrize("style", ["popstream", "mob"])
def test_driver_allocates_nothing_per_frame_in_a_variant_burst(env, style):
    env.lua.execute(LCG)
    g = make(env, fixed_random=False, trail=True)
    g.db.flightTime = 1.5
    g.db.unknownOrigin = "inplace"
    fire(g, style, "inplace", n=20)
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
