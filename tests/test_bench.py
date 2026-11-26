"""The dev-only in-game benchmark (dev/Bench.lua): scripts, statistics, the saved run, and that settings always return."""

import itertools

from conftest import ROOT, TESTS, lua_list, lupa_rt
from test_m5 import build

SCALE = 0.1  # ns.Bench.durationScale: shrinks settle, baseline and the script, so a run is a few hundred ticks
STEP = 0.05


def to_py(value):
    """A Lua table as nested dicts / lists (a table keyed 1..n is a list)."""
    if lupa_rt.lua_type(value) != "table":
        return value
    keys = list(value.keys())
    if keys and sorted(keys) == list(range(1, len(keys) + 1)):
        return [to_py(value[i]) for i in range(1, len(keys) + 1)]
    return {k: to_py(value[k]) for k in keys}


def load_bench(e):
    e.load_chunk(ROOT / "dev" / "Bench.lua", "dev/Bench.lua")("XPOrbs", e.ns)
    e.ns.Bench.durationScale = SCALE


def make(env):
    env = build(env)
    env.load_chunk(TESTS / "stubs_bench.lua", "stubs_bench.lua")(env.ns)
    before = set(env.G.keys())
    load_bench(env)
    env.new_globals = set(env.G.keys()) - before
    env.db.size, env.db.density, env.db.orbShape = (
        20,
        150,
        "starlight",
    )  # not the presets: a restore must show
    env.db.shapeLook.starlight.size = 20
    env.db.glowOffsetX = 12
    return env


def settings(e):
    """The player's settings: the whole db but the bench's own key."""
    out = to_py(e.db)
    out.pop("bench", None)
    return out


def bench(e, arg):
    e.slash("bench " + arg)


def running(e):
    return e.ns.Bench.IsRunning()


def tick(e, n):
    for _ in range(n):
        e.stub.tick(STEP)


def finish(e, limit=4000):
    for _ in range(limit):
        if not running(e):
            return
        e.stub.tick(STEP)
    raise AssertionError("the bench did not finish")


def runs(e):
    store = e.db.bench
    return lua_list(store.runs) if store is not None else []


def updaters(e):
    return [f for f in lua_list(e.stub.frames) if f.scripts.OnUpdate is not None]


def chat(e):
    return e.say()


# ---------------------------------------------------------------- statistics


def test_stats_nearest_rank_on_a_known_array(env):
    e = make(env)
    stats = to_py(
        e.ns.Bench.Stats(e.lua.table_from(list(range(1, 11)) + [999]), 10)
    )  # the 999 is past n
    assert stats == {
        "n": 10, "mean": 5.5, "p50": 5, "p95": 10, "p99": 10, "max": 10,
        "over1": 9, "over5": 5, "over10": 0, "over16": 0,
    }  # fmt: skip
    stats = to_py(
        e.ns.Bench.Stats(e.lua.table_from(list(range(100, 0, -1))), 100)
    )  # unsorted input
    assert (stats["p50"], stats["p95"], stats["p99"], stats["max"]) == (50, 95, 99, 100)
    assert (stats["over5"], stats["over10"], stats["over16"]) == (
        95,
        90,
        84,
    )  # 16.67 ms: 17 and up


def test_stats_of_nothing_is_zeros(env):
    e = make(env)
    stats = to_py(e.ns.Bench.Stats(e.lua.table(), 0))
    assert stats["n"] == 0 and all(v == 0 for v in stats.values())


# ---------------------------------------------------------------- scenario scripts


def schedule(e, scenario):
    return [to_py(ev) for ev in lua_list(e.ns.Bench.Schedule(scenario))]


def groups(events):
    out = {}
    for ev in events:
        out.setdefault(ev["group"], []).append(ev)
    return list(out.values())


def test_schedule_is_deterministic_and_unknown_is_nil(env):
    e = make(env)
    for name in ("max", "aoe", "typical"):
        assert schedule(e, name) == schedule(e, name)
    assert e.ns.Bench.Schedule("nope") is None


def test_schedule_max(env):
    e = make(env)
    events = schedule(e, "max")
    assert len(events) == 120
    for i, ev in enumerate(events):
        assert ev["t"] == i * 0.25 and ev["slot"] == i % 8 + 1 and ev["pct"] == 30
        assert ev["rested"] == ((i + 1) % 3 == 0)


def test_schedule_aoe_waves(env):
    e = make(env)
    events = schedule(e, "aoe")
    assert [ev["t"] for ev in events] == sorted(ev["t"] for ev in events)
    assert 0 <= events[0]["t"] and events[-1]["t"] < 60
    waves = groups(events)
    assert 12 <= len(waves) <= 30  # 60 s of waves 2-4 s apart
    starts = [w[0]["t"] for w in waves]
    assert all(2.0 <= b - a <= 4.0 for a, b in itertools.pairwise(starts))
    for wave in waves:
        assert (2 if wave is not waves[-1] else 1) <= len(wave) <= 4  # the last wave may be cut at 60 s
        slots = [ev["slot"] for ev in wave]
        assert len(set(slots)) == len(slots) and all(
            1 <= s <= 8 for s in slots
        )  # never a repeat inside a wave
        assert all(0.1 <= b["t"] - a["t"] <= 0.6 for a, b in itertools.pairwise(wave))
    assert all(0.4 <= ev["pct"] <= 1.2 for ev in events)
    assert any(ev["rested"] for ev in events) and not all(ev["rested"] for ev in events)


def test_schedule_typical_pulls(env):
    e = make(env)
    events = schedule(e, "typical")
    assert [ev["t"] for ev in events] == sorted(ev["t"] for ev in events)
    assert events[-1]["t"] < 60
    pulls = groups(events)
    assert 4 <= len(pulls) <= 7
    starts = [p[0]["t"] for p in pulls]
    assert 8 <= starts[0] <= 12 and all(
        8.0 <= b - a <= 12.0 for a, b in itertools.pairwise(starts)
    )
    for pull in pulls:
        assert 1 <= len(pull) <= 3
        assert len({ev["slot"] for ev in pull}) == len(pull)
        assert all(0.0 <= b["t"] - a["t"] <= 1.5 for a, b in itertools.pairwise(pull))
    assert all(0.8 <= ev["pct"] <= 2.5 for ev in events)


# ---------------------------------------------------------------- a full run


def check_stats(stats):
    keys = (
        "n",
        "mean",
        "p50",
        "p95",
        "p99",
        "max",
        "over1",
        "over5",
        "over10",
        "over16",
    )
    assert set(stats) == set(keys)
    assert all(isinstance(stats[k], (int, float)) for k in keys)
    assert stats["p50"] <= stats["p95"] <= stats["p99"] <= stats["max"]


def check_phase(phase, overall):
    assert set(phase) == (
        {"seconds", "frames", "addonMs", "frameMs"}
        | ({"overallMs"} if overall else set())
    )
    assert phase["seconds"] > 0 and phase["frames"] > 0
    for key in ("addonMs", "frameMs", *(["overallMs"] if overall else [])):
        check_stats(phase[key])
        assert phase[key]["n"] == phase["frames"]


def check_run(run, scenario, rep, reps, source="internal"):
    """Every SCHEMA.md field of a saved run, present and typed."""
    num = (int, float)
    for key, kind in {
        "id": str, "batch": str, "scenario": str, "date": str, "addonVersion": str, "build": str,
        "buildNumber": str, "source": str, "scenarioVersion": num, "rep": num, "reps": num, "seed": num,
        "interface": num, "screenW": num, "screenH": num, "uiScale": num, "kills": num, "orbs": num,
        "peakLive": num, "peakTextures": num, "driverMs": num, "memStartKB": num, "memEndKB": num, "gcKB": num,
        "maxFPS": str, "vsync": str, "settings": dict, "baseline": dict, "load": dict, "burstMs": dict,
        "timeline": dict,
    }.items():  # fmt: skip
        assert isinstance(run[key], kind), key
    assert run["id"] == f"{run['batch']}-{scenario}-{rep}"
    assert (run["scenario"], run["rep"], run["reps"], run["scenarioVersion"]) == (
        scenario,
        rep,
        reps,
        1,
    )
    assert run["source"] == source
    assert (
        run["addonVersion"],
        run["build"],
        run["buildNumber"],
        run["interface"],
    ) == ("9.9.9", "1.16.1", "12345", 16001)
    assert run["date"].endswith("Z") and "T" in run["date"] and len(run["date"]) == 20
    assert run["screenW"] == 1920 and run["screenH"] == 1080 and run["uiScale"] == 1
    assert (run["maxFPS"], run["vsync"]) == ("0", "0")
    assert set(run["settings"]) == {
        "orbShape", "size", "density", "cap", "flightPath", "style", "popMode", "flightMode", "flightTime",
        "trail", "glowIntensity", "sound",
    }  # fmt: skip
    assert run["settings"]["sound"] is False
    overall = source == "profiler"
    check_phase(run["baseline"], overall)
    check_phase(run["load"], overall)
    check_stats(run["burstMs"])
    assert run["burstMs"]["n"] == run["kills"] > 0
    assert (
        run["load"]["frames"] > 0
        and run["orbs"] >= run["kills"]
        and run["peakLive"] > 0
    )
    tl = run["timeline"]
    assert (
        set(tl) == {"step", "addonMs", "addonMaxMs", "frameMs", "live"}
        and tl["step"] == 0.5
    )
    assert (
        len(tl["addonMs"])
        == len(tl["addonMaxMs"])
        == len(tl["frameMs"])
        == len(tl["live"])
        > 0
    )
    assert all(
        isinstance(v, (int, float))
        for k in ("addonMs", "addonMaxMs", "frameMs", "live")
        for v in tl[k]
    )


def test_bench_typical_one_rep_saves_a_complete_run(env):
    e = make(env)
    assert e.new_globals == set()  # the bench writes nothing global
    bench(e, "typical 1")
    assert running(e)
    finish(e)
    (saved,) = runs(e)
    run = to_py(saved)
    check_run(run, "typical", 1, 1)
    assert run["kills"] == len(schedule(e, "typical"))  # the whole script ran
    assert run["memStartKB"] == 123.4
    lines = chat(e)
    assert any("1 run(s)" in line and "Stand still" in line for line in lines)
    assert any("done, settings restored" in line for line in lines)
    assert any("typical x1:" in line for line in lines)
    assert e.db.bench.restore is None and e.db.bench.schema == 1


def test_bench_with_the_profiler_records_its_source_and_overall(env):
    e = make(env)
    e.stub.profiler(True)
    bench(e, "typical 1")
    finish(e)
    run = to_py(runs(e)[0])
    check_run(run, "typical", 1, 1, source="profiler")
    assert (
        run["load"]["addonMs"]["mean"] == 0.5 and run["load"]["overallMs"]["mean"] == 2
    )


def test_the_preset_is_applied_while_running_and_gone_after(env):
    e = make(env)
    before = settings(e)
    bench(e, "max 1")
    tick(e, 3)
    assert running(e)
    db = e.db
    assert (
        db.orbShape,
        db.size,
        db.density,
        db.cap,
        db.flightPath,
        db.glowIntensity,
    ) == (
        "starlight",
        32,
        300,
        80,
        "chaos",
        200,
    )
    assert db.sound is False and db.enabled is True and db.flightTime == 1.5
    look = db.shapeLook.starlight  # the shape's own entry agrees with the active values
    assert (
        look.size,
        look.density,
        look.opacity,
        look.blend,
        look.pulse,
        look.sparkle,
    ) == (32, 300, 100, "natural", False, True)
    assert look.crackleSpeed == db.crackleSpeed
    assert db.glowOffsetX == 12  # destination keys stay
    finish(e)
    assert settings(e) == before


def test_aoe_and_typical_use_the_defaults_but_keep_the_destination(env):
    e = make(env)
    e.db.cap, e.db.flightPath, e.db.trail, e.db.zoomA = 60, "helix", False, 7
    bench(e, "aoe 1")
    tick(e, 3)
    db, defaults = e.db, e.ns.defaults
    assert (db.cap, db.flightPath, db.trail, db.size, db.density) == (
        defaults.cap,
        defaults.flightPath,
        defaults.trail,
        defaults.size,
        defaults.density,
    )
    assert db.zoomA == 7 and db.glowOffsetX == 12  # kept
    assert db.sound is False
    bench(e, "stop")


# ---------------------------------------------------------------- settings always come back


def test_stop_mid_run_discards_the_run_and_restores(env):
    e = make(env)
    before = settings(e)
    bench(e, "max 1")
    tick(e, 60)  # past settle and baseline, into the load
    assert running(e) and e.db.density == 300 and e.db.bench.restore is not None
    bench(e, "stop")
    assert not running(e)
    assert settings(e) == before
    assert e.db.bench.restore is None and runs(e) == []
    assert any("aborted (stopped)" in line for line in chat(e))
    assert e.ns.Bench.frame.scripts.OnUpdate is None
    bench(e, "stop")
    assert any("nothing is running" in line for line in chat(e))


def test_an_error_in_the_sampler_aborts_once_and_restores(env):
    e = make(env)
    before = settings(e)
    bench(e, "typical 1")
    tick(e, 2)
    e.lua.eval("function(o) o.BenchProbe = function() error('boom') end end")(e.orbs)
    tick(e, 20)  # settle ends and the baseline probes the orbs
    assert not running(e)
    assert settings(e) == before and e.db.bench.restore is None and runs(e) == []
    errors = [line for line in chat(e) if "aborted (error:" in line]
    assert len(errors) == 1 and "boom" in errors[0]
    assert e.ns.Bench.frame.scripts.OnUpdate is None


def test_entering_combat_aborts_and_restores(env):
    e = make(env)
    before = settings(e)
    bench(e, "typical 1")
    tick(e, 10)
    e.ns.fire("PLAYER_REGEN_DISABLED")
    assert not running(e) and settings(e) == before
    assert any("you entered combat" in line for line in chat(e))
    assert e.ns.Bench.frame.scripts.OnUpdate is None


def test_a_reload_mid_run_restores_at_the_next_load(env):
    e = make(env)
    before = settings(e)
    bench(e, "max 1")
    tick(e, 60)
    assert e.db.density == 300 and e.db.bench.restore is not None
    # the reload: the old Lua state is gone (its scripts stop), the saved variables survive
    e.ns.Bench.frame.scripts.OnUpdate = None
    e.ns.Bench.eventFrame.scripts.OnEvent = None
    assert settings(e) != before
    load_bench(e)  # the addon loads again, fresh
    assert not running(e)
    e.ns.fire("ADDON_LOADED", "XPOrbs")
    assert settings(e) == before and e.db.bench.restore is None
    assert any(
        "restored your settings after an interrupted run" in line for line in chat(e)
    )
    e.ns.fire("ADDON_LOADED", "XPOrbs")  # nothing left to restore: silent
    assert sum("interrupted run" in line for line in chat(e)) == 1


def test_a_restore_keeps_the_minimap_table_identity(env):
    e = make(env)
    minimap = e.db.minimap
    bench(e, "aoe 1")
    tick(e, 3)
    bench(e, "stop")
    assert e.lua.eval("rawequal")(e.db.minimap, minimap)  # LibDBIcon holds this table


# ---------------------------------------------------------------- finishing, trimming, idling, refusing


def test_nothing_keeps_an_onupdate_after_a_run_and_runs_are_trimmed_to_30(env):
    e = make(env)
    e.db.bench = e.lua.table_from(
        {
            "schema": 1,
            "runs": e.lua.table_from([{"id": f"old{i}"} for i in range(1, 31)]),
        }
    )
    bench(e, "typical 1")
    finish(e)
    ids = [r["id"] for r in runs(e)]
    assert (
        len(ids) == 30
        and "old1" not in ids
        and ids[0] == "old2"
        and ids[-1].endswith("-typical-1")
    )
    assert e.ns.Bench.frame.scripts.OnUpdate is None
    e.run(6.0)  # let any orb or pop still flying finish
    assert updaters(e) == []


def test_list_prints_the_last_saved_runs(env):
    e = make(env)
    bench(e, "list")
    assert any("no saved runs" in line for line in chat(e))
    bench(e, "typical 1")
    finish(e)
    bench(e, "list")
    assert any(
        "typical 1/1 v9.9.9 net" in line
        for line in chat(e)
    )
    assert any("p99" in line and "fps" in line for line in chat(e))


def test_refuses_while_running_or_in_combat_and_clamps_reps(env):
    e = make(env)
    e.stub.inCombat = True
    bench(e, "max 1")
    assert (
        not running(e)
        and any("combat" in line for line in chat(e))
        and e.db.bench is None
    )
    e.stub.inCombat = False
    bench(e, "all")
    assert running(e) and any(
        "9 run(s)" in line for line in chat(e)
    )  # 3 scenarios x 3 reps
    bench(e, "max 1")
    assert any("already running" in line for line in chat(e))
    bench(e, "stop")
    bench(e, "typical 99")
    assert any("10 run(s)" in line for line in chat(e))
    bench(e, "stop")
    bench(e, "typical 0")
    assert any(
        "bench: 1 run(s)" in line
        for line in chat(e)
    )
    bench(e, "stop")


def test_usage_and_cap_warning(env):
    e = make(env)
    bench(e, "")
    bench(e, "help")
    bench(e, "bogus")
    assert sum("usage:" in line for line in chat(e)) == 3
    e.stub.cvars.maxFPS = "144"
    bench(e, "typical 1")
    assert any("fps cap/vsync hides the real cost" in line for line in chat(e))
    bench(e, "stop")
    e.stub.cvars.maxFPS, e.stub.cvars.gxVSync = "0", "1"
    bench(e, "typical 1")
    assert sum("fps cap/vsync" in line for line in chat(e)) == 2
    bench(e, "stop")
