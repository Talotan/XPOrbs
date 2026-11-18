"""1.0.2 fix release: saved-variable sanitising, driver safety, AoE starvation, matcher/XP-cache fixes, picker and
test-command safety, perf tooling."""

import re

import pytest
from conftest import lua_list
from test_m5 import build
from test_m6 import make as make_full
from test_plates_stub import CHAT, Game
from test_v09 import burst, make, restricted_plate, set_level, textures


def ident(env, a, b):
    return env.lua.eval("rawequal")(a, b)


def load_db(env, db):
    env.G.XPOrbsDB = env.lua.table_from(db, recursive=True)
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    return env.G.XPOrbsDB


def rgb(c):
    return (c[1], c[2], c[3])


def log_lines(g):
    return [str(x) for x in lua_list(g.db.log)] if g.db.log else []


def count_log(g, needle):
    return sum(needle in line for line in log_lines(g))


def raise_in(env, table, key, msg="boom"):
    """Replace table[key] with a function that raises; returns the original."""
    orig = table[key]
    table[key] = env.lua.eval(f"function() error('{msg}') end")
    return orig


# ---------------------------------------------------------------- 1. saved-variable sanitising


def test_ranges_table_is_shared_with_options(env):
    env.load_addon()
    r = env.ns.ranges
    assert (r.cap[1], r.cap[2], r.cap[3]) == (5, 80, 1)
    assert (r.flightTime[1], r.flightTime[2], r.flightTime[3]) == (0.4, 1.5, 0.05)
    assert (r.glowIntensity[1], r.glowIntensity[2]) == (25, 200)
    from conftest import ROOT

    src = (ROOT / "Options.lua").read_text(encoding="utf-8")
    assert (
        "5, 80, 1" not in src
        and "0.4, 1.5, 0.05" not in src
        and "25, 400, 25" not in src
    )


def test_bad_numbers_load_to_sane_values(env):
    db = load_db(
        env,
        {
            "version": 4,
            "flightTime": -0.5,
            "cap": "lots",
            "size": 10000,
            "density": 0,
            "glowOffsetX": 1e9,
            "glowIntensity": "x",
        },
    )
    assert db.flightTime == 0.4  # clamped to the slider minimum
    assert db.cap == 40  # not a number: the default
    assert db.size == 32 and db.density == 25
    assert db.glowOffsetX == 100 and db.glowIntensity == 100


def test_cap_over_range_is_clamped(env):
    assert load_db(env, {"version": 4, "cap": 5000}).cap == 80


def test_good_values_survive_and_are_snapped(env):
    db = load_db(
        env,
        {
            "version": 5,  # a schema-4 save would have its old-default 0.75 reset to 1.0
            "cap": 25,
            "flightTime": 0.75,
            "density": 150,
            "glowIntensity": 107,
        },
    )
    assert (db.cap, db.flightTime, db.density, db.glowIntensity) == (25, 0.75, 150, 105)


def test_bad_enums_and_booleans_reset(env):
    db = load_db(
        env,
        {
            "version": 4,
            "style": "bogus",
            "glowShape": "square",
            "trail": "yes",
            "enabled": 0,
            "debug": {},
            "classColor": "x",
        },
    )
    assert db.style == "popstream" and db.glowShape == "bar"
    assert (
        db.trail is True
        and db.enabled is True
        and db.debug is False
        and db.classColor is False
    )


def test_bad_colours_reset_and_good_ones_clamp(env):
    db = load_db(env, {"version": 4, "color": "red", "restedColor": [2, -1, 0.5]})
    assert rgb(db.color) == (0.72, 0.28, 1.00)  # a string: the default
    assert rgb(db.restedColor) == (1, 0, 0.5)  # clamped to 0..1


def test_colour_with_non_numbers_resets(env):
    db = load_db(env, {"version": 4, "color": [0.1, "x", 0.3]})
    assert rgb(db.color) == (0.72, 0.28, 1.00)


def test_future_schema_version_is_left_alone(env):
    assert load_db(env, {"version": 9, "cap": 20}).version == 9


def test_current_and_old_versions_stamp_to_schema(env):
    assert load_db(env, {"version": 2}).version == 5


def test_reset_command_sanitises_and_restores_defaults(env):
    load_db(env, {"version": 4})
    db = env.G.XPOrbsDB
    db.cap = -5
    env.G.SlashCmdList.XPORBS("reset")
    assert db.cap == 40 and db.flightTime == 1.0 and db.version == 5


def test_burst_with_bad_saved_flight_time_finishes(env):
    env.lua.execute(
        "XPOrbsDB = { version = 4, flightTime = -0.5, cap = 'x', style = 'bogus', color = 'red' }"
    )
    g = make(env)
    assert g.db.flightTime == 0.4 and g.db.cap == 40
    burst(g, n=10, x=500, y=500, kind="kill")
    g.tick(0.05, 80)
    assert g.orbs.driver.scripts.OnUpdate is None and g.orbs.Info(g.orbs)[1] == 0


def test_burst_clamps_a_bad_duration_after_load(env):
    g = make(env)
    g.db.flightTime = -0.5  # bypasses the loader: Burst itself must not strand the orbs
    burst(g, n=6, x=500, y=500, kind="kill")
    g.tick(0.05, 120)
    assert g.orbs.driver.scripts.OnUpdate is None and g.orbs.Info(g.orbs)[1] == 0


# ---------------------------------------------------------------- 2. the driver never gets stuck


def test_driver_error_releases_everything_and_logs_once(env):
    g = make(env)
    plate = restricted_plate(g)
    burst(g, plate=plate, n=8, x=500, y=500, kind="kill")
    g.tick(0.05, 2)
    assert g.orbs.Info(g.orbs)[1] > 0
    orig = raise_in(env, g.ns.Target, "GetDestination")
    g.tick(0.05)  # must not raise
    active, in_use, _, _ = g.orbs.Info(g.orbs)
    assert not active and in_use == 0 and g.orbs.driver.scripts.OnUpdate is None
    free, created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert free == created and alive == 0 and xf == 0
    assert g.stub.shownTextures() == 0
    assert count_log(g, "DRIVER_ERR") == 1
    # the driver works again afterwards, and a second failure is not logged again
    g.ns.Target["GetDestination"] = orig
    burst(g, n=5, x=500, y=500, kind="kill")
    g.tick(0.05, 3)
    assert g.orbs.Info(g.orbs)[1] > 0
    raise_in(env, g.ns.Target, "GetDestination")
    g.tick(0.05)
    assert g.orbs.Info(g.orbs)[1] == 0 and count_log(g, "DRIVER_ERR") == 1


def test_driver_error_releases_crossfade_frames(env):
    g = make(env)
    g.db.style = "crossfade"
    plate = restricted_plate(g)
    assert burst(g, plate=plate, n=6, x=500, y=500, kind="kill") == "crossfade"
    g.tick(0.05)
    raise_in(env, g.ns.Target, "GetDestination")
    g.tick(0.05)
    free, created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert free == created and alive == 0 and xf == 0 and g.orbs.Info(g.orbs)[1] == 0


@pytest.mark.parametrize("style", ["popstream", "crossfade"])
def test_burst_error_after_a_pop_started_releases_the_frame(env, style):
    g = make(env)
    g.db.style = style
    plate = restricted_plate(g)
    raise_in(env, g.ns.OrbMath, "PopControl")
    with pytest.raises(Exception):
        burst(g, plate=plate, n=5, x=500, y=500, kind="kill")
    free, created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert created == 1 and free == 1 and alive == 0 and xf == 0
    assert g.orbs.Info(g.orbs)[1] == 0  # no texture left in use
    g.tick(0.05, 5)
    assert g.orbs.driver.scripts.OnUpdate is None


# ---------------------------------------------------------------- 3. AoE starvation


def test_ceiling_holds_two_full_bursts(env):
    g = make(env)
    burst(g, n=1, x=1, y=1, kind="kill")
    assert g.orbs.Info(g.orbs)[3] == 40 * 5 * 2 + 8
    g.db.cap = 10
    assert g.orbs.Info(g.orbs)[3] == 10 * 5 * 2 + 8


def test_ten_aoe_bursts_all_get_orbs(env):
    g = make(env, trail=True)
    for _ in range(10):
        before = g.orbs.Info(g.orbs)[1]
        burst(g, n=8, x=500, y=500, kind="kill")
        got = g.orbs.Info(g.orbs)[1] - before
        assert got >= 3 * 3  # at least 3 orbs (3 textures each, trail or not)
        _, in_use, created, ceiling = g.orbs.Info(g.orbs)
        assert in_use <= ceiling and created <= ceiling
        g.tick(0.05)
    g.tick(0.05, 100)
    active, in_use, created, ceiling = g.orbs.Info(g.orbs)
    assert not active and in_use == 0 and created <= ceiling
    assert g.orbs.driver.scripts.OnUpdate is None


def test_overfull_pool_drops_trails_then_trims_but_keeps_three_orbs(env):
    g = make(env, trail=True)
    seen = []
    for _ in range(14):  # 14 x 40 orbs is far more than the ceiling holds
        _, before, _, ceiling = g.orbs.Info(g.orbs)
        free = ceiling - 1 - before
        burst(g, n=40, x=500, y=500, kind="kill")
        got = g.orbs.Info(g.orbs)[1] - before
        if free >= 9:
            assert got >= 9, (free, got)
        assert g.orbs.Info(g.orbs)[1] <= ceiling
        seen.append(got)
        g.tick(0.02)
    assert seen[0] == 40 * 5  # the first burst is drawn in full, with trails
    assert any(
        x == 0 or x % 3 == 0 and x < 40 * 5 for x in seen[2:]
    )  # later ones were trimmed or lost trails
    g.tick(0.05, 200)
    assert g.orbs.Info(g.orbs)[1] == 0 and not g.orbs.Info(g.orbs)[0]


# ---------------------------------------------------------------- 4. findDeath


class Rig:
    def __init__(self, env):
        env.load_addon()
        self.env, self.t = env, 0.0
        self.m = env.ns.KillMatcher.New(env.lua.table_from({"now": lambda: self.t}))

    def death(self, tag, name=None):
        d = {"guid": tag, "tier": 1}
        if name:
            d["name"] = name
        self.m.AddDeath(self.m, self.env.lua.table_from(d))

    def chat(self, amount, mob=None):
        k = {"amount": amount}
        if mob:
            k["mob"] = mob
        self.m.AddKillXP(self.m, self.env.lua.table_from(k))

    def poll(self):
        return lua_list(self.m.Poll(self.m))


def test_find_death_prefers_same_name_over_older_nameless(env):
    r = Rig(env)
    r.death("nameless")
    r.death("boar", name="Boar")
    r.chat(10, mob="Boar")
    (b,) = r.poll()
    assert b.guid == "boar"


def test_find_death_falls_back_to_oldest_nameless(env):
    r = Rig(env)
    r.death("wolf", name="Wolf")
    r.death("n1")
    r.death("n2")
    r.chat(10, mob="Boar")
    (b,) = r.poll()
    assert b.guid == "n1"


def test_find_death_never_takes_a_differently_named_death(env):
    r = Rig(env)
    r.death("wolf", name="Wolf")
    r.chat(10, mob="Boar")
    assert r.poll() == []
    r.t = 0.5
    (b,) = r.poll()
    assert b.tier == 4 and b.guid is None  # the kill goes on without a position ...
    r.t = 1.6
    r.poll()
    assert (
        r.m.Stats(r.m).dropped == 1
    )  # ... and the wolf death was left alone until it expired


def test_find_death_without_a_mob_name_keeps_the_oldest(env):
    r = Rig(env)
    r.death("wolf", name="Wolf")
    r.death("boar", name="Boar")
    r.chat(10)
    (b,) = r.poll()
    assert b.guid == "wolf"


# ---------------------------------------------------------------- 5. tier 3 is gone


def test_tier3_counter_and_stat_are_gone(env):
    r = Rig(env)
    s = r.m.Stats(r.m)
    assert s.tier3 is None and s.tier1 == 0 and s.tier2 == 0 and s.tier4 == 0
    assert r.m.stats["tier3"] is None
    r.m.AddDeath(r.m, env.lua.table_from({"x": 5, "y": 6, "tier": 1}))
    r.chat(10)
    (b,) = r.poll()
    assert b.x is None and b.y is None  # deaths no longer carry a position


def test_stats_log_line_and_status_drop_tier3(env):
    g = Game(env)
    g.plate(guid="G1", name="Boar")
    g.tick(0.05)
    env.ns.fire("UNIT_DIED", "G1")
    g.chat()
    g.tick(0.1)
    assert g.has_log("STATS tier1=1 tier2=0 tier4=0 dropped=0 other=0")
    assert not g.has_log("tier3")
    g.env.G.SlashCmdList.XPORBS("status")
    said = " ".join(str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1))
    assert "kills: tier1=1 tier2=0 tier4=0" in said and "tier3" not in said


# ---------------------------------------------------------------- 6. stale XP cache


def test_unreadable_xp_updates_reprime_instead_of_merging_a_delta(env):
    g = Game(env)
    g.plate(guid="G1", name="Boar")
    g.tick(0.05)
    env.ns.fire("UNIT_DIED", "G1")
    g.chat()
    g.tick(0.1)
    assert len(g.bursts()) == 1
    for _ in range(3):
        g.stub.setXP(g.stub.SECRET)
    g.stub.setXP(
        150
    )  # 100 more XP arrived while unreadable: not one merged "other" burst
    g.tick(1.0, 3)
    assert g.stats()["other"] == 0 and len(g.bursts()) == 1
    assert g.has_log("XPUPDATE stale; cache primed")
    g.stub.setXP(200)  # normal tracking resumes
    g.tick(1.0)
    assert g.stats()["other"] == 1


def test_stale_flag_clears_on_world_entry(env):
    g = Game(env)
    g.stub.setXP(g.stub.SECRET)
    g.stub.xp = 300
    env.ns.fire("PLAYER_ENTERING_WORLD")
    g.stub.setXP(350)
    g.tick(1.0)
    assert g.stats()["other"] == 1 and not g.has_log("stale; cache primed")


# ---------------------------------------------------------------- 7. level-up is detected from the numbers


def test_xpdelta_wraps_on_a_changed_max(env):
    env.load_addon()
    om = env.ns.OrbMath
    assert om.XPDelta(900, 1000, 950, 1100) == 1050
    assert om.XPDelta(950, 1100, 1000, 1100) == 50
    assert om.XPDelta(900, 1000, 50, 1000) == 150  # same max, xp went down
    assert om.XPDelta(100, 1000, 100, 1000) == 0
    # a new max with unchanged XP (the second half of a split level-up update) is not another level-up
    assert om.XPDelta(950, 1000, 950, 1100) == 0


def test_level_up_event_order_does_not_matter(env):
    g = Game(env)
    g.stub.xp, g.stub.xpMax = 900, 1000
    env.ns.fire("PLAYER_ENTERING_WORLD")
    g.stub.setXP(950, 1100)  # PLAYER_LEVEL_UP has not fired yet
    assert g.has_log("XPUPDATE delta=1050 leveled=true")
    env.ns.fire("PLAYER_LEVEL_UP")  # late: only logs
    g.stub.setXP(1000)
    assert g.has_log("XPUPDATE delta=50 leveled=false")
    assert g.has_log("PLAYER_LEVEL_UP")


# ---------------------------------------------------------------- 8. no max-level gate


def test_at_max_level_helper(env):
    env.load_addon()
    set_level_env = lambda lvl, mx: env.lua.execute(  # noqa: E731
        f"UnitLevel = function() return {lvl} end; GetMaxPlayerLevel = function() return {mx} end"
    )
    assert env.ns.AtMaxLevel() is False  # no APIs
    set_level_env(70, 70)
    assert env.ns.AtMaxLevel() is True
    set_level_env(60, 70)
    assert env.ns.AtMaxLevel() is False
    env.lua.execute("UnitLevel = function() error('x') end")
    assert env.ns.AtMaxLevel() is False


def test_gain_that_reaches_max_level_bursts_with_show_at_max_off(env):
    g = make(env)
    g.fake_orbs_on()
    g.db.showAtMax = False
    set_level(
        g, 70, 70
    )  # PLAYER_LEVEL_UP already ran: the player is at the cap when the burst is emitted
    g.plate(guid="G1", name="Boar", cx=1, cy=1)
    g.tick(0.05)
    g.ns.fire("UNIT_DIED", "G1")
    g.chat()
    g.tick(0.1)
    assert len(g.bursts()) == 1
    assert g.db.showAtMax is False  # the setting itself is untouched


# ---------------------------------------------------------------- 9. pop on the wrong mob


def test_reused_plate_gives_no_pop(env):
    g = Game(env)
    plate_a = g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.tick(0.05)
    env.ns.fire("UNIT_DIED", "G1")
    g.stub.removePlate("nameplate1", True)
    # a new mob appears on the SAME plate frame under another unit token
    g.stub.plates["nameplate2"] = plate_a
    g.stub.units["nameplate2"] = env.lua.table_from(
        {"guid": "G2", "name": "Wolf", "canAttack": True}
    )
    env.ns.fire("NAME_PLATE_UNIT_ADDED", "nameplate2")
    g.chat()
    g.tick(0.1)
    (b,) = g.bursts()
    assert b["plate"] is None and g.has_log("plate=no")


def test_reused_plate_under_the_same_token_gives_no_pop(env):
    g = Game(env)
    plate_a = g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.tick(0.05)
    env.ns.fire("UNIT_DIED", "G1")
    g.stub.removePlate("nameplate1", True)
    g.stub.units["nameplate1"] = env.lua.table_from(
        {"guid": "G2", "name": "Wolf", "canAttack": True}
    )
    env.ns.fire(
        "NAME_PLATE_UNIT_ADDED", "nameplate1"
    )  # same token, same frame, different mob
    assert ident(env, g.stub.plates["nameplate1"], plate_a)
    g.chat()
    g.tick(0.1)
    (b,) = g.bursts()
    assert b["plate"] is None


def test_own_plate_still_pops(env):
    g = Game(env)
    plate = g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.tick(0.05)
    env.ns.fire(
        "UNIT_DIED", "G1"
    )  # the entry is still live (UNIT_DIED before removal): itself is not "another"
    g.chat()
    g.tick(0.1)
    (b,) = g.bursts()
    assert ident(env, b["plate"], plate)


def test_living_target_plate_is_not_used_as_a_fallback(env):
    g = Game(env)
    plate = g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200, isTarget=True)
    g.stub.plates["target"] = plate
    g.stub.units["target"] = env.lua.table_from({"dead": False})
    g.chat()  # a kill with no death entry at all
    g.tick(0.6)
    (b,) = g.bursts()
    assert b["plate"] is None


def test_dead_target_plate_is_the_fallback(env):
    g = Game(env)
    plate = g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200, isTarget=True)
    g.stub.plates["target"] = plate
    g.stub.units["target"] = env.lua.table_from({"dead": True})
    g.chat()
    g.tick(0.6)
    (b,) = g.bursts()
    assert ident(env, b["plate"], plate)


# ---------------------------------------------------------------- 10. secret XP at the destination


def test_secret_xp_keeps_the_last_readable_fill_edge(env):
    g = make(env)
    g.stub.xp, g.stub.xpMax = 500, 1000
    x, y, ok = g.ns.Target.GetDestination(g.ns.Target)
    assert (x, y, ok) == (800, 25, True)  # 400 + 800 * 0.5
    g.stub.xp = g.stub.SECRET
    x, y, ok = g.ns.Target.GetDestination(g.ns.Target)
    assert (x, y, ok) == (
        800,
        25,
        True,
    )  # still the bar, not the bottom-centre fallback
    g.stub.xp, g.stub.xpMax = 250, 1000
    assert g.ns.Target.GetDestination(g.ns.Target)[0] == 600
    g.stub.xpMax = g.stub.SECRET
    assert g.ns.Target.GetDestination(g.ns.Target)[0] == 600


def test_secret_xp_with_no_history_aims_at_the_frame_centre(env):
    g = make(env)
    g.stub.xp = g.stub.SECRET
    x, y, ok = g.ns.Target.GetDestination(g.ns.Target)
    assert (x, y, ok) == (
        800,
        25,
        True,
    )  # frame centre, on the bar (an empty bar would give x = 400)


# ---------------------------------------------------------------- 11. the picker never picks a nameplate


def named(env, name, parent=None):
    return env.lua.eval("function(n, p) return CreateFrame('Frame', n, p) end")(
        name, parent
    )


def test_picker_rejects_plates_and_their_children(env):
    e = build(env)
    pick = e.ns.Target.PickName
    plate = e.stub.addPlate("nameplate1", e.lua.table_from({"guid": "G1"}))
    child = named(e, "UnitFrame", plate)
    grandchild = named(e, None, child)
    assert pick(child) is None  # parent is a live plate frame
    assert pick(grandchild) is None
    assert pick(plate) is None  # unnamed plate, but in GetNamePlates()
    named_plate = named(e, "NamePlate7")
    assert pick(named_plate) is None  # by name alone
    assert pick(named(e, "Inner", named_plate)) is None
    ok = named(e, "MainStatusTrackingBarContainer")
    assert tuple(pick(ok))[0] == "MainStatusTrackingBarContainer"


# ---------------------------------------------------------------- 12. /xporbs test safety


def test_test_command_with_unreadable_xp_and_cursor_does_not_use_them(env):
    e = make_full(env)
    e.stub.cursor.x, e.stub.cursor.y = 321, 123
    e.stub.secretAll = True  # every read is "secret"
    e.slash("test 5 stream")  # must not raise
    e.stub.secretAll = False
    said = " ".join(e.say())
    assert "stream=cursor" not in said and "stream=centre" in said


def test_test_command_normal_cursor_origin_still_works(env):
    e = make_full(env)
    e.stub.cursor.x, e.stub.cursor.y = 321, 123
    e.slash("test 5 stream")
    assert "stream=cursor" in " ".join(e.say())


# ---------------------------------------------------------------- 13. small cleanups


def test_log_ring_is_chronological_and_bounded(env):
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    env.G.XPOrbsDB.debug = True
    for i in range(1000):
        env.ns.Log(env.ns, "entry %d", i)
    log = [str(x) for x in lua_list(env.G.XPOrbsDB.log)]
    assert 500 <= len(log) <= 600
    nums = [int(line.rsplit(" ", 1)[1]) for line in log]
    assert nums == list(
        range(1000 - len(log), 1000)
    )  # contiguous, oldest first, newest last
    env.G.SlashCmdList.XPORBS("status")  # reads #log
    assert any("log entries: " in str(v) for v in env.ns.stub.chat.values())


def test_xp_queues_are_pruned_without_kills(env):
    g = Game(env)
    for i in range(40):
        g.stub.setXP(10 * (i + 1))
        g.tick(1.0)
    entries, awaiting = g.ns.Kills.XPQueueSizes(g.ns.Kills)
    assert entries <= 3 and awaiting == 0


def test_retry_rereads_a_missing_name(env):
    g = Game(env)
    g.plate("nameplate1", cx=300, cy=200)  # neither guid nor name readable yet
    entry = g.ns.Plates.entries["nameplate1"]
    assert entry.name is None and entry.guid is None
    g.stub.units["nameplate1"]["name"] = "Boar"
    g.tick(0.3)
    assert entry.name == "Boar" and entry.guid is None


def test_other_xp_origin_defaults_to_65_percent_and_honours_x_y(env):
    g = make(env)
    # no origin given: centre, 65% height
    burst(g, n=1, kind="other")
    g.tick(0.09)
    t = [
        t
        for t in textures(g)
        if t.shown and len(t.points) > 0 and ident(env, t.parentFrame, g.orbs.overlay)
    ]
    assert t, "no orb drawn"
    px, py = t[0].points[1][4], t[0].points[1][5]
    assert abs(px - 960) < 40 and abs(py - 1080 * 0.65) < 40
    g.tick(0.05, 80)
    # an explicit origin is used as given
    burst(g, n=1, x=500, y=400, kind="other")
    g.tick(0.09)
    t = [
        t
        for t in textures(g)
        if t.shown and len(t.points) > 0 and ident(env, t.parentFrame, g.orbs.overlay)
    ]
    px, py = t[0].points[1][4], t[0].points[1][5]
    assert abs(px - 500) < 40 and abs(py - 400) < 40


def test_kills_passes_the_65_percent_origin_for_non_kill_xp(env):
    g = Game(env)
    g.stub.setXP(100, 1000)
    g.tick(0.6)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (960, pytest.approx(1080 * 0.65)) and g.has_log(
        "origin=centre plate=no"
    )


# ---------------------------------------------------------------- perf tooling


def test_perf_command_reports_all_counters(env):
    e = make_full(env)
    e.slash("perf")
    out = " ".join(e.say())
    assert "memory 123.4 KB" in out and "frames=0" in out
    assert e.stub.memUpdates == 1
    e.slash("test 5")
    e.run(1.5)
    n0 = len(e.say())
    e.slash("perf")
    lines = e.say()[n0:]
    text = "\n".join(lines)
    m = re.search(r"frames=(\d+) avg=([\d.]+) ms max=([\d.]+) ms", text)
    assert m and int(m.group(1)) > 10
    assert float(m.group(2)) == pytest.approx(0.25) and float(
        m.group(3)
    ) == pytest.approx(0.25)
    assert re.search(r"textures created=\d+ in use=0 ceiling=408", text)
    assert re.search(r"pop frames created=\d+", text) and "live orbs=0" in text


def test_perf_reset_zeroes_the_counters(env):
    e = make_full(env)
    e.slash("test 5")
    e.run(0.5)
    e.slash("perf reset")
    n0 = len(e.say())
    e.slash("perf")
    assert "frames=0 avg=0.000 ms max=0.000 ms" in "\n".join(e.say()[n0:])


def test_perf_without_the_memory_api_says_n_a(env):
    e = make_full(env)
    e.G.GetAddOnMemoryUsage = None
    e.slash("perf")
    assert "memory n/a" in " ".join(e.say())
    e.G.UpdateAddOnMemoryUsage = None
    e.G.debugprofilestop = None
    e.slash("test 5")
    e.run(0.3)  # the driver runs fine without a profiler
    e.slash("perf")


def test_help_lists_perf_and_stress(env):
    e = make_full(env)
    e.slash("help")
    out = " ".join(e.say())
    assert "/xporbs perf" in out and "stress" in out


def count_bursts(e):
    e.lua.execute(
        """stress_n, stress_min, stress_max = 0, math.huge, 0
        local orig = XPOrbsNS.Orbs.Burst
        XPOrbsNS.Orbs.Burst = function(self, p)
            stress_n = stress_n + 1
            stress_min = math.min(stress_min, p.n)
            stress_max = math.max(stress_max, p.n)
            return orig(self, p)
        end"""
    )


@pytest.mark.parametrize(
    "arg,expected",
    [("stress 10", 10), ("stress", 20), ("stress 500", 100), ("stress 0", 1)],
)
def test_stress_schedules_bursts_and_removes_its_frame(env, arg, expected):
    e = make_full(env)
    e.G.XPOrbsNS = e.ns
    count_bursts(e)
    e.slash("test " + arg)
    frame = e.ns.Orbs.stressFrame
    assert frame.scripts.OnUpdate is not None
    e.run(2.6)
    assert e.G.stress_n == expected
    assert 8 <= e.G.stress_min and e.G.stress_max <= 22  # 1..15 % of a level
    assert frame.scripts.OnUpdate is None
    e.run(5.0)
    assert e.stub.updaters() == 0
    _, in_use, created, ceiling = e.orbs.Info(e.orbs)
    assert in_use == 0 and created <= ceiling


def test_stress_is_spread_over_about_two_seconds(env):
    e = make_full(env)
    e.G.XPOrbsNS = e.ns
    count_bursts(e)
    e.slash("test stress 20")
    e.run(0.5)
    assert 3 <= e.G.stress_n <= 8
    e.run(0.6)
    assert 8 <= e.G.stress_n <= 14
    e.run(1.2)
    assert e.G.stress_n == 20


# ---------------------------------------------------------------- perf harness


def test_200_bursts_drain_cleanly_within_the_ceiling(env):
    g = make(env, fixed_random=False, trail=True)
    plates = [
        restricted_plate(g, f"nameplate{i + 1}", guid=f"G{i + 1}") for i in range(5)
    ]
    for i in range(200):
        style = ("popstream", "crossfade", "stream")[i % 3]
        burst(
            g,
            n=5 + (i * 7) % 36,
            x=300 + i,
            y=500,
            kind="kill",
            style=style,
            plate=plates[i % 5],
        )
        g.tick(0.016, 2)
        _, in_use, created, ceiling = g.orbs.Info(g.orbs)
        assert in_use <= ceiling and created <= ceiling
    g.tick(0.05, 300)
    active, in_use, created, ceiling = g.orbs.Info(g.orbs)
    assert in_use == 0 and not active and created <= ceiling
    assert g.stub.updaters() == 0
    free, pop_created, alive, xf = g.orbs.PoolInfo(g.orbs)
    assert free == pop_created and alive == 0 and xf == 0
    assert g.stub.restrictedHits == 0


def test_driver_allocates_nothing_per_frame_in_steady_state(env):
    g = make(env, fixed_random=False, trail=True)
    g.db.flightTime = 1.5
    plate = restricted_plate(g)
    burst(g, plate=plate, n=20, x=400, y=300, kind="kill", style="popstream")
    burst(g, n=20, x=600, y=300, kind="kill", style="stream")
    g.tick(0.016, 3)  # warm up: lazily created tables and textures exist now
    assert g.orbs.Info(g.orbs)[1] > 20
    grown = g.env.lua.eval(
        """function(driver, frames, dt)
            -- The stub's own bookkeeping (SetPoint, ClearAllPoints, SetRotation ...) allocates a table per call, so
            -- it is replaced by no-ops: what remains is whatever the addon itself allocates per frame.
            local fm = getmetatable(UIParent).__index
            local noop = function() end
            for _, n in ipairs({ "SetPoint", "ClearAllPoints", "SetSize", "SetRotation", "SetVertexColor", "SetTexture",
                "SetBlendMode", "SetDrawLayer" }) do
                fm[n] = noop
            end
            local fn = driver.scripts.OnUpdate
            fn(driver, dt) -- one more warm-up frame now that the stub methods are swapped
            collectgarbage("collect")
            collectgarbage("stop") -- no collection during the run, so every allocation shows up in the count
            local c0 = collectgarbage("count")
            for _ = 1, frames do
                fn(driver, dt)
            end
            local c1 = collectgarbage("count")
            collectgarbage("restart")
            return c1 - c0, fn ~= nil
        end"""
    )(g.orbs.driver, 300, 0.002)
    # Measured: a clean driver shows 0-2 KB of noise here (the measuring loop itself), regardless of the frame count.
    # The old per-call closure in ApplyOffset alone added 13+ KB over these 300 frames, and anything allocated per orb
    # per frame (40 orbs x 300 frames) would be far above that, so 4 KB separates "allocates nothing" from "allocates".
    assert g.orbs.Info(g.orbs)[1] > 0  # orbs were still alive the whole time
    assert grown[0] < 4.0, grown
