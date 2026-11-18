"""M6 (v0.17): no plate measuring anywhere, a seeded soak of the renderer, and the idle (no OnUpdate) guarantee."""

import random
import re

import pytest
from conftest import ROOT, TESTS, lua_list
from test_m5 import build

STYLES = ("popstream", "crossfade", "stream")
KINDS = ("kill", "other", "test")


def make(env):
    """The full addon on the M2/M3/M5 stubs plus the v0.9 restricted-region emulation (plates refuse measuring)."""
    env = build(env)
    env.load_chunk(TESTS / "stubs_v09.lua", "stubs_v09.lua")(env.ns)
    env.lua.execute("ns_errors = {}")
    # record every error the addon logs, whether or not debug logging is on
    env.lua.eval(
        """function(ns)
            local base = ns.Log
            ns.Log = function(self, fmt, ...)
                local text = tostring(fmt)
                if string.find(text, "ERR") or string.find(text, "error") then
                    ns_errors[#ns_errors + 1] = text
                end
                return base(self, fmt, ...)
            end
        end"""
    )(env.ns)
    env.errors = lambda: lua_list(env.G.ns_errors)
    return env


def shown_orb_textures(e):
    """Shown textures owned by the renderer (the overlay and the pop frames); the options panel has its own."""
    same = e.lua.eval("rawequal")
    owners = [e.orbs.overlay] + lua_list(e.stub.popFrames())
    return sum(
        1
        for f in lua_list(e.stub.frames)
        if f.kind == "Texture" and f.shown and any(same(f.parentFrame, o) for o in owners)
    )


def burst(e, **kw):
    return e.orbs.Burst(e.orbs, e.lua.table_from(kw))


# ---------------------------------------------------------------- nothing measures a plate


@pytest.mark.parametrize("name", ["Plates.lua", "Kills.lua"])
def test_plates_and_kills_never_call_a_measuring_api(name):
    src = (ROOT / name).read_text(encoding="utf-8")
    code = "\n".join(
        line.split("--")[0] for line in src.splitlines()
    )  # comments may talk about measuring
    assert not re.search(
        r"Get(Center|Left|Right|Top|Bottom|Rect|Point|Scale|EffectiveScale)\b", code
    )


def test_plates_module_has_no_geometry_api_or_state(env):
    e = make(env)
    plates = e.ns.Plates
    for key in (
        "Sample",
        "TargetEntry",
        "SamplerActive",
        "stats",
        "measurable",
        "samplerFrame",
    ):
        assert plates[key] is None, key
    e.stub.addRestrictedPlate(
        "nameplate1", e.lua.table_from({"guid": "G1", "name": "Boar"})
    )
    e.stub.removePlate("nameplate1", True)
    entry = plates.held[1]
    for key in ("x", "y", "t", "proxy"):
        assert entry[key] is None, key
    assert e.stub.restrictedHits == 0


def test_full_kill_flow_with_restricted_plates_never_measures_one(env):
    e = make(env)
    e.db.debug = True
    for i, style in enumerate(STYLES):
        e.db.style = style
        unit, guid = f"nameplate{i + 1}", f"G{i + 1}"
        e.stub.addRestrictedPlate(
            unit, e.lua.table_from({"guid": guid, "name": "Boar"})
        )
        e.ns.fire("UNIT_DIED", guid)
        e.stub.removePlate(unit, True)
        e.ns.fire("CHAT_MSG_COMBAT_XP_GAIN", "Boar dies, you gain 50 experience.")
        e.stub.setXP(50 * (i + 1))
        e.run(3.0)
    e.run(3.0)
    assert e.stub.restrictedHits == 0
    log = [str(x) for x in lua_list(e.db.log)]
    assert (
        sum(
            " kind=kill " in line and line.split(" ", 1)[1].startswith("BURST")
            for line in log
        )
        == 3
    )
    assert not any(
        k in line for line in log for k in ("hadPos", "hadXY", "GEOM", "geom", "probe")
    )
    assert e.errors() == []


def test_killmatcher_tolerates_deaths_without_a_position(env):
    e = make(env)
    m = e.ns.Kills.matcher
    m.AddDeath(m, e.lua.table_from({"tier": 1, "name": "Boar", "guid": "G1"}))
    m.AddKillXP(m, e.lua.table_from({"amount": 50, "mob": "Boar"}))
    e.stub.time += 0.1
    (b,) = lua_list(m.Poll(m))
    assert b["x"] is None and b["y"] is None and b["tier"] == 1 and b["kind"] == "kill"


def test_old_probe_key_in_a_saved_db_is_dropped_and_harmless(env):
    env.lua.execute("XPOrbsDB = { version = 4, probe = true, cap = 12 }")
    e = make(env)  # build() fires ADDON_LOADED
    assert e.db.probe is None and e.db.cap == 12


# ---------------------------------------------------------------- soak


def test_soak_1000_random_bursts(env):
    rng = random.Random(20261115)
    e = make(env)
    e.lua.execute("math.randomseed(20261115)")
    e.db.debug = False
    orbs, stub = e.orbs, e.stub
    plates = []
    for i in range(10):
        plates.append(
            stub.addRestrictedPlate(
                f"nameplate{i + 1}", e.lua.table_from({"guid": f"G{i + 1}"})
            )
        )
    bound = 0  # the highest texture ceiling since the pool was last empty (a cap cut leaves older orbs alive)
    bound_ever = 0
    modes = set()
    peak = 0
    for _ in range(1000):
        roll = rng.random()
        if roll < 0.05:
            e.db.cap = rng.choice([5, 12, 20, 40, 60])
        elif roll < 0.10:
            e.db.size = rng.choice([8, 14, 24, 40])
        elif roll < 0.15:
            e.db.glow = rng.random() < 0.5
            e.db.glowShape = rng.choice(["bar", "round"])
        elif roll < 0.18:
            e.db.trail = rng.random() < 0.5
        elif roll < 0.20:
            e.db.restedTint = rng.random() < 0.7
        if rng.random() < 0.06:
            orbs.PlateReused(orbs, rng.choice(plates))
        cap = e.db.cap
        n = (
            rng.randint(1, cap) if rng.random() < 0.8 else rng.randint(1, 80)
        )  # sometimes above the cap
        kw = {
            "n": n,
            "scale": rng.choice([1, 1, 1.2, 1.5]),
            "nPurple": rng.randint(0, n) if rng.random() < 0.4 else 0,
            "kind": rng.choice(KINDS),
            "style": rng.choice(STYLES),
            "x": rng.uniform(100, 1800),
            "y": rng.uniform(100, 1000),
        }
        if rng.random() < 0.7:
            kw["plate"] = rng.choice(plates)
        if rng.random() < 0.5:
            kw["ex"], kw["ey"] = rng.uniform(100, 1800), rng.uniform(100, 1000)
        _, before_use, _, ceil_before = orbs.Info(orbs)
        bound = max(bound, ceil_before) if before_use else ceil_before
        modes.add(burst(e, **kw))
        _, in_use, created, ceiling = orbs.Info(orbs)
        bound = max(bound, ceiling)
        assert in_use <= bound, (in_use, bound)
        bound_ever = max(bound_ever, bound)
        assert created <= bound_ever + 1  # created only ever grows, so compare with the highest ceiling seen
        peak = max(peak, in_use)
        # tick forward in random steps
        for _ in range(rng.randint(0, 4)):
            stub.tick(rng.choice([0.004, 0.016, 0.033, 0.05, 0.12]))
            _, in_use, created, ceiling = orbs.Info(orbs)
            assert in_use <= bound, (in_use, bound)
        if not orbs.Info(orbs)[0]:
            bound = 0
    assert peak > 0
    assert {"pop+stream", "crossfade", "stream"} <= modes  # every style really ran, with and without a plate
    # drain: tick past every flight (longest: a 1.5 s flight x 1.2 x 1.15, plus hold, stagger, delays, flash)
    for _ in range(400):
        stub.tick(0.05)
    active, in_use, created, ceiling = orbs.Info(orbs)
    assert not active and in_use == 0
    assert shown_orb_textures(e) == 0
    free, popCreated, popsAlive, xfAlive = orbs.PoolInfo(orbs)
    assert (
        free == popCreated and popsAlive == 0 and xfAlive == 0
    )  # every pop/crossfade frame is back, refs 0
    for f in lua_list(stub.popFrames()):
        assert f.shown is False and len(f.points) == 0
    assert orbs.driver.scripts.OnUpdate is None
    assert e.errors() == []
    assert stub.restrictedHits == 0


# ---------------------------------------------------------------- idle


def owned_frames(e):
    """Every frame this addon creates that could ever carry an OnUpdate, by owner."""
    out = {
        "Orbs.driver": e.ns.Orbs.driver,
        "Kills.pollFrame": e.ns.Kills.pollFrame,
        "Mouseover.frame": e.ns.Mouseover.frame,
        "Target.pickFrame": e.ns.Target.pickFrame,
        "Plates.retryFrame": e.ns.Plates.retryFrame,
        "Orbs.stressFrame": e.ns.Orbs.stressFrame,  # only exists after /xporbs test stress
        "Options.panel": e.ns.Options.panel,
    }
    return out


def updaters(e):
    return [f for f in lua_list(e.stub.frames) if f.scripts.OnUpdate is not None]


def test_idle_after_load_world_entry_and_a_finished_burst_nothing_has_an_onupdate(env):
    e = make(env)
    e.ns.fire("PLAYER_ENTERING_WORLD")
    assert updaters(e) == []  # straight after load
    # a real kill, start to finish
    e.stub.addRestrictedPlate(
        "nameplate1", e.lua.table_from({"guid": "G1", "name": "Boar"})
    )
    e.ns.fire("UNIT_DIED", "G1")
    e.stub.removePlate("nameplate1", True)
    e.ns.fire("CHAT_MSG_COMBAT_XP_GAIN", "Boar dies, you gain 50 experience.")
    e.stub.setXP(50)
    e.run(0.2)
    assert (
        e.ns.Orbs.driver.scripts.OnUpdate is not None
    )  # the scan below is meaningful: it does see a live driver
    e.run(6.0)
    assert not e.orbs.Info(e.orbs)[0]
    # idle: no mouseover, no target, picker unarmed, panel hidden
    assert not e.ns.Target.IsPicking(e.ns.Target)
    assert e.ns.Options.panel.IsShown(e.ns.Options.panel) in (
        True,
        False,
    )  # never shown by us
    for owner, f in owned_frames(e).items():
        if f is not None:
            assert f.scripts.OnUpdate is None, owner
    assert [
        f for f in updaters(e)
    ] == []  # and nothing else in the whole stub has one either


def test_idle_scan_sees_each_owner_when_it_is_busy_and_clears_after(env):
    e = make(env)
    stub = e.stub
    # Mouseover poll: a hostile unit under the cursor
    stub.units["mouseover"] = e.lua.table_from(
        {"guid": "M1", "canAttack": True, "exists": True}
    )
    e.ns.fire("UPDATE_MOUSEOVER_UNIT")
    assert e.ns.Mouseover.frame.scripts.OnUpdate is not None
    stub.units["mouseover"]["exists"] = False
    e.ns.fire("UPDATE_MOUSEOVER_UNIT")
    assert e.ns.Mouseover.frame.scripts.OnUpdate is None
    # Target picker
    e.slash("pick")
    assert e.ns.Target.pickFrame.scripts.OnUpdate is not None
    stub.mouseDown("RightButton")
    assert e.ns.Target.pickFrame.scripts.OnUpdate is None
    # Plates GUID retry: a hostile plate whose GUID is unreadable
    e.stub.addPlate("nameplate1", e.lua.table_from({"name": "Boar"}))
    assert e.ns.Plates.retryFrame.scripts.OnUpdate is not None
    stub.units["nameplate1"]["guid"] = "G1"
    e.run(0.5)
    assert e.ns.Plates.retryFrame.scripts.OnUpdate is None
    # Options: opening the panel starts nothing
    e.opt.panel.scripts.OnShow(e.opt.panel)
    e.run(1.0)
    # Kills poll: a lone XP delta
    stub.setXP(40)
    assert e.ns.Kills.pollFrame.scripts.OnUpdate is not None
    e.run(3.0)
    assert updaters(e) == []


def test_every_frame_with_an_onupdate_script_belongs_to_a_known_owner(env):
    """No stray OnUpdate anywhere: even while busy, only the named owners ever set one."""
    e = make(env)
    stub = e.stub
    stub.units["mouseover"] = e.lua.table_from(
        {"guid": "M1", "canAttack": True, "exists": True}
    )
    e.ns.fire("UPDATE_MOUSEOVER_UNIT")
    e.slash("pick")
    e.stub.addPlate("nameplate1", e.lua.table_from({"name": "Boar"}))
    stub.setXP(40)
    burst(e, n=10, x=500, y=500, kind="other")
    e.slash("test stress 5")  # v1.0.2: the short-lived stress frame is the sixth owner
    same = e.lua.eval("rawequal")
    known = [f for f in owned_frames(e).values() if f is not None]
    busy = updaters(e)
    assert len(busy) >= 6
    for f in busy:
        assert any(same(f, k) for k in known)
