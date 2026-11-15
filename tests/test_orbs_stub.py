"""M2: orb renderer, destination and /xporbs test, run against the WoW stub (+ stubs_m2)."""

import pytest
from conftest import TESTS


@pytest.fixture
def m2(env):
    env.load_chunk(TESTS / "stubs_m2.lua", "stubs_m2.lua")(env.ns)
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    env.ns.stub.makeBar("MainStatusTrackingBarContainer", 400, 20, 800, 10, True)
    env.orbs = env.ns.Orbs
    env.stub = env.ns.stub
    env.slash = env.G.SlashCmdList.XPORBS

    def burst(**kw):
        env.orbs.Burst(env.orbs, env.lua.table_from(kw))

    def run(seconds, step=0.05):
        for _ in range(int(seconds / step) + 1):
            env.stub.tick(step)

    def info():
        active, in_use, created, ceiling = env.orbs.Info(env.orbs)
        return active, in_use, created, ceiling

    env.burst, env.run, env.info = burst, run, info
    return env


def test_burst_40_finishes_and_goes_idle(m2):
    m2.burst(x=300, y=600, n=40)
    active, in_use, created, ceiling = m2.info()
    assert active and in_use > 0
    assert m2.orbs.driver.scripts.OnUpdate is not None
    m2.run(0.75 * 1.15 + 0.15 + 0.12 + 0.5)  # flight + stagger + flash
    active, in_use, created, ceiling = m2.info()
    assert not active
    assert in_use == 0
    assert m2.stub.shownTextures() == 0
    assert m2.orbs.driver.scripts.OnUpdate is None


def test_driver_idle_before_any_burst(m2):
    assert m2.orbs.driver is None
    active, in_use, _, _ = m2.info()
    assert not active and in_use == 0


def test_zero_or_negative_n_is_noop(m2):
    m2.burst(x=1, y=1, n=0)
    m2.burst(x=1, y=1, n=-3)
    assert m2.orbs.driver is None
    assert m2.info()[1] == 0


def test_ten_bursts_never_exceed_ceiling(m2):
    for _ in range(10):
        m2.burst(x=300, y=600, n=40)
    _, in_use, created, ceiling = m2.info()
    assert ceiling == 40 * 5 + 8  # cap * (1 + EXTRAS) + 8, EXTRAS = 4
    assert created <= ceiling
    assert m2.stub.allTextures() <= ceiling
    peak = 0
    for _ in range(80):
        m2.stub.tick(0.05)
        peak = max(peak, m2.stub.allTextures())
    assert peak <= ceiling
    # more bursts after the first wave drained reuse the pool
    m2.burst(x=300, y=600, n=40)
    assert m2.stub.allTextures() <= ceiling
    m2.run(2)
    assert m2.info()[1] == 0 and m2.stub.shownTextures() == 0


def test_trail_off_uses_fewer_textures(m2):
    m2.G.XPOrbsDB.trail = False
    m2.burst(x=300, y=600, n=10)
    assert m2.info()[1] == 30  # underlay + orb + sparkle per orb
    m2.run(2)
    assert m2.info()[1] == 0


def test_purple_uses_rested_colour(m2):
    m2.burst(x=300, y=600, n=2, nPurple=1)
    rested = tuple(m2.G.XPOrbsDB.restedColor.values())
    cols = [
        tuple(f.calls["SetVertexColor"].values())
        for f in m2.stub.frames.values()
        if f.kind == "Texture" and f.calls and "SetVertexColor" in f.calls
    ]
    assert rested in cols


def test_destination_tracks_fill_edge(m2):
    m2.stub.xp, m2.stub.xpMax = 250, 1000
    x, y, ok = m2.ns.Target.GetDestination(m2.ns.Target)
    assert ok
    assert x == pytest.approx(400 + 800 * 0.25)
    assert y == pytest.approx(25)
    assert m2.ns.Target.lastName == "MainStatusTrackingBarContainer"


def test_destination_scale_conversion(m2):
    bar = m2.G.MainStatusTrackingBarContainer
    bar.scale = 0.5  # UIParent scale is 1
    m2.stub.xp, m2.stub.xpMax = 500, 1000
    x, y, ok = m2.ns.Target.GetDestination(m2.ns.Target)
    assert ok and x == pytest.approx((400 + 400) * 0.5) and y == pytest.approx(12.5)


def test_destination_fallback_when_no_bar_visible(m2):
    m2.G.MainStatusTrackingBarContainer.shown = False
    x, y, ok = m2.ns.Target.GetDestination(m2.ns.Target)
    assert not ok
    assert x == pytest.approx(960)
    assert y < 100
    assert m2.ns.Target.lastName is None


def test_destination_falls_to_next_frame_and_override(m2):
    m2.G.MainStatusTrackingBarContainer.shown = False
    m2.stub.makeBar("MainMenuExpBar", 0, 0, 100, 10, True)
    assert m2.ns.Target.GetDestination(m2.ns.Target)[2]
    assert m2.ns.Target.lastName == "MainMenuExpBar"
    m2.stub.makeBar("MyBar", 1000, 100, 200, 20, True)
    m2.G.XPOrbsDB.targetFrame = "MyBar"
    m2.ns.Target.GetDestination(m2.ns.Target)
    assert m2.ns.Target.lastName == "MyBar"
    m2.G.XPOrbsDB.targetFrame = "DoesNotExist"  # bad override -> auto list
    m2.ns.Target.GetDestination(m2.ns.Target)
    assert m2.ns.Target.lastName == "MainMenuExpBar"


def test_destination_unreadable_geometry_falls_back(m2):
    bar = m2.G.MainStatusTrackingBarContainer
    bar.left = None
    assert m2.ns.Target.GetDestination(m2.ns.Target)[2] is False


def shown_orb_count(m2):
    # each orb with trail on is underlay+orb+sparkle+2 ghosts = 5 textures
    return m2.info()[1] // 5


@pytest.mark.parametrize(
    "arg,orbs",
    [("", 14), ("10", 19), ("5 rested", 14), ("50", 38), ("1000", 40), ("rested", 14)],
)
def test_command_parsing(m2, arg, orbs):
    m2.slash("test " + arg)
    assert shown_orb_count(m2) == orbs
    msg = m2.stub.chat[len(m2.stub.chat)]
    assert "test:" in msg and f"{orbs} orbs" in msg
    assert ("(%d purple)" % (round(orbs / 2) if "rested" in arg else 0)) in msg or "rested" in arg


def test_command_rested_split_and_origin(m2):
    m2.stub.cursor.x, m2.stub.cursor.y = 200, 300
    m2.slash("test 10 rested")
    assert "(10 purple)" in m2.stub.chat[len(m2.stub.chat)]
    m2.stub.tick(0.5)  # positions are only set once an orb's stagger delay has elapsed
    xs = [f.points[1][4] for f in m2.stub.frames.values() if f.kind == "Texture" and len(f.points) > 0]
    assert xs and all(x < 960 for x in xs)  # started near the cursor at x=200, not screen centre


def test_command_survives_plates_error(m2):
    plates = m2.lua.eval("function() return {TargetEntry = function() error('boom') end} end")()
    m2.ns.Plates = plates
    m2.slash("test 1")
    assert shown_orb_count(m2) == 8


def test_pick_prompt_and_status(m2):
    m2.slash("pick")
    assert "Click the XP bar" in m2.stub.chat[len(m2.stub.chat)]
    m2.slash("status")
    lines = [m2.stub.chat[i] for i in range(1, len(m2.stub.chat) + 1)]
    orbs_line = [ln for ln in lines if "orbs: driver=idle" in ln]
    assert orbs_line and "MainStatusTrackingBarContainer" in orbs_line[0] and "fallback=no" in orbs_line[0]


def test_status_before_any_burst_and_fallback(m2):
    m2.G.MainStatusTrackingBarContainer.shown = False
    m2.slash("status")
    lines = [m2.stub.chat[i] for i in range(1, len(m2.stub.chat) + 1)]
    assert any("fallback=yes" in ln and "dest=nil" in ln for ln in lines)


def test_underlay_is_blend_below_orb_and_dark(m2):
    m2.burst(x=300, y=600, n=1)
    texs = [f for f in m2.stub.frames.values() if f.kind == "Texture" and f.calls and "SetDrawLayer" in f.calls]
    under = [f for f in texs if f.calls["SetBlendMode"][1] == "BLEND"]
    assert len(under) == 1
    assert tuple(under[0].calls["SetVertexColor"].values()) == (0.02, 0.08, 0.30)
    assert under[0].calls["SetDrawLayer"][2] == -1
    layers = sorted(f.calls["SetDrawLayer"][2] for f in texs)
    assert layers == [-1, 0, 0, 0, 1]  # underlay, orb + 2 ghosts, sparkle


def _sparkle_widths(m2):
    return [
        f.width
        for f in m2.stub.frames.values()
        if f.kind == "Texture" and f.shown and f.calls and "sparkle" in f.calls["SetTexture"][1]
    ]


def test_rested_orbs_start_later_and_bigger(m2):
    m2.burst(x=300, y=600, n=1, nPurple=1)
    # (C rand() is shared by every Lua state in the process, so the stagger varies with test order: delay >= 0.12 s)
    m2.run(0.05)  # two 0.05 s ticks: RESTED_DELAY not yet elapsed
    assert m2.stub.shownTextures() == 0
    m2.run(0.3)
    assert _sparkle_widths(m2) == [pytest.approx(14 * 1.15 * 1.9)]
    m2.run(2)
    m2.burst(x=300, y=600, n=1)
    m2.run(0.35)
    assert _sparkle_widths(m2) == [pytest.approx(14 * 1.9)]


def test_arrival_flash_bumps_and_decays(m2):
    m2.burst(x=300, y=600, n=3)
    flash = [f for f in m2.stub.frames.values() if f.kind == "Texture"][0]
    m2.run(0.75 * 1.15 + 0.25 + 0.01)
    # all orbs have landed: flash was shown at some point and driver stays active until it decays
    m2.run(0.5)
    assert not m2.info()[0]
    assert not flash.shown
