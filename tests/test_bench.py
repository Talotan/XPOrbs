"""The dev-only in-game benchmark (dev/Bench.lua): scripts, statistics, the saved run, and that settings always return."""

import itertools
import re

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


def check_phase(phase, profiler):
    assert set(phase) == (
        {"seconds", "frames", "addonMs", "frameMs"}
        | ({"profilerMs", "overallMs"} if profiler else set())
    )
    assert phase["seconds"] > 0 and phase["frames"] > 0
    for key in ("addonMs", "frameMs", *(["profilerMs", "overallMs"] if profiler else [])):
        check_stats(phase[key])
        assert phase[key]["n"] == phase["frames"]


def check_run(run, scenario, rep, reps, profiler=False):
    """Every SCHEMA.md field of a saved run, present and typed."""
    num = (int, float)
    for key, kind in {
        "id": str, "batch": str, "scenario": str, "date": str, "addonVersion": str, "build": str,
        "buildNumber": str, "source": str, "schema": num, "scenarioVersion": num, "rep": num, "reps": num,
        "seed": num, "interface": num, "screenW": num, "screenH": num, "uiScale": num, "kills": num,
        "orbs": num, "peakLive": num, "peakTextures": num, "driverMs": num, "memStartKB": num, "memEndKB": num,
        "vsync": str, "maxFPS": str, "useMaxFPS": str, "targetFPS": str, "useTargetFPS": str,
        "settings": dict, "baseline": dict, "load": dict, "burstMs": dict, "timeline": dict,
    }.items():  # fmt: skip
        assert isinstance(run[key], kind), key
    assert run["schema"] == 2 and "gcKB" not in run
    assert run["id"] == f"{run['batch']}-{scenario}-{rep}"
    assert (run["scenario"], run["rep"], run["reps"], run["scenarioVersion"]) == (
        scenario,
        rep,
        reps,
        1,
    )
    assert run["source"] == "internal"  # always XP Orbs' own timers
    assert run.get("profilerMetric") == ("RecentAverageTime" if profiler else None)
    assert (
        run["addonVersion"],
        run["build"],
        run["buildNumber"],
        run["interface"],
    ) == ("9.9.9", "1.16.1", "12345", 16001)
    assert run["date"].endswith("Z") and "T" in run["date"] and len(run["date"]) == 20
    assert run["screenW"] == 2560 and run["screenH"] == 1440 and run["uiScale"] == 1  # physical pixels
    assert [run[k] for k in ("vsync", "maxFPS", "useMaxFPS", "targetFPS", "useTargetFPS")] == ["0"] * 5
    assert set(run["settings"]) == {
        "orbShape", "size", "density", "cap", "flightPath", "style", "popMode", "flightMode", "flightTime",
        "trail", "glowIntensity", "sound",
    }  # fmt: skip
    assert run["settings"]["sound"] is False
    check_phase(run["baseline"], profiler)
    check_phase(run["load"], profiler)
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
    assert e.db.bench.restore is None and e.db.bench.schema == 2


def test_bench_with_the_profiler_adds_a_cross_check_but_never_replaces_the_timers(env):
    e = make(env)
    e.stub.profiler(True)
    bench(e, "typical 1")
    finish(e)
    run = to_py(runs(e)[0])
    check_run(run, "typical", 1, 1, profiler=True)
    load = run["load"]
    assert load["profilerMs"]["mean"] == 0.5 and load["overallMs"]["mean"] == 2  # RecentAverageTime, not LastTime (0)
    assert load["addonMs"]["mean"] != 0.5 and load["addonMs"]["mean"] > 0  # the internal timers
    assert any("cross-check on" in line for line in chat(e))


def test_a_profiler_that_cannot_answer_is_left_out(env):
    e = make(env)
    e.stub.profiler(True)
    e.lua.execute("Enum.AddOnProfilerMetric.RecentAverageTime = nil")
    bench(e, "typical 1")
    finish(e)
    check_run(to_py(runs(e)[0]), "typical", 1, 1)
    assert any("cross-check off" in line for line in chat(e))
    assert any("no cross-check figure" in line for line in chat(e))


def test_screen_falls_back_to_the_resolution_cvars_then_to_nothing(env):
    e = make(env)
    e.stub.physical = None  # GetPhysicalScreenSize gives nothing: the resolution cvars
    e.stub.cvars.gxFullscreenResolution = "1920x1080"
    bench(e, "typical 1")
    finish(e)
    e.stub.cvars.gxFullscreenResolution = None
    e.stub.cvars.gxWindowedResolution = "1600x900"
    bench(e, "typical 1")
    finish(e)
    e.stub.cvars.gxWindowedResolution = None  # nothing at all: omitted, never a wrong number
    bench(e, "typical 1")
    finish(e)
    first, second, third = (to_py(r) for r in runs(e))
    assert (first["screenW"], first["screenH"]) == (1920, 1080)
    assert (second["screenW"], second["screenH"]) == (1600, 900)
    assert "screenW" not in third and "screenH" not in third and third["uiScale"] == 1


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


def test_usage(env):
    e = make(env)
    bench(e, "")
    bench(e, "help")
    bench(e, "bogus")
    assert sum("usage:" in line for line in chat(e)) == 3


def warnings_for(e, **cvars):
    """The warning lines one start prints with these cvars set (the bench is stopped again)."""
    for k, v in cvars.items():
        setattr(e.stub.cvars, k, v)
    before = len(chat(e))
    bench(e, "typical 1")
    bench(e, "stop")
    return [line for line in chat(e)[before:] if "warning:" in line]


def test_each_fps_limiter_is_named_in_a_warning(env):
    e = make(env)
    assert warnings_for(e) == []
    (line,) = warnings_for(e, maxFPS="144", useMaxFPS="1")
    assert "Max FPS is on (144)" in line
    assert warnings_for(e, useMaxFPS="0") == []  # a cap value with the switch off is no limiter
    (line,) = warnings_for(e, useMaxFPS=None)  # no switch cvar at all: the old rule, a value above 0 counts
    assert "Max FPS is on (144)" in line
    e.stub.cvars.maxFPS = "0"
    (line,) = warnings_for(e, targetFPS="90", useTargetFPS="1")
    assert "Target FPS is on (90)" in line
    assert warnings_for(e, useTargetFPS="0") == []
    (line,) = warnings_for(e, vsync="1")
    assert "vsync is on" in line
    assert len(warnings_for(e, maxFPS="60", useMaxFPS="1", targetFPS="90", useTargetFPS="1")) == 3


def test_the_limiter_cvars_are_recorded_on_the_run(env):
    e = make(env)
    e.stub.cvars.targetFPS, e.stub.cvars.useTargetFPS, e.stub.cvars.vsync = "90", "1", None
    bench(e, "typical 1")
    finish(e)
    run = to_py(runs(e)[0])
    assert (run["targetFPS"], run["useTargetFPS"], run["maxFPS"], run["useMaxFPS"]) == ("90", "1", "0", "0")
    assert "vsync" not in run  # an unreadable cvar is left out


# ---------------------------------------------------------------- the progress panel


def panel(e):
    return e.ns.Bench.panel


def stage(e):
    """The stage label without its numbers: Settling / Idle baseline / Load / Draining."""
    return re.match(r"[A-Za-z ]+?(?=  |$)", str(panel(e).stageLine.text)).group(0)


def stages_seen(e, limit=4000):
    """Run to the end, noting each stage label the panel showed, in order."""
    seen = []
    for _ in range(limit):
        if not running(e):
            return seen
        e.stub.tick(STEP)
        if running(e) and (not seen or seen[-1] != stage(e)):
            seen.append(stage(e))
    raise AssertionError("the bench did not finish")


def test_the_panel_appears_on_start_with_its_widgets(env):
    e = make(env)
    assert e.ns.Bench.panel is None  # lazily built
    bench(e, "typical 2")
    p = panel(e)
    assert p.frame.shown is True and p.frame.calls.SetFrameStrata[1] == "DIALOG"
    assert (p.frame.width, p.frame.height) == (280, 96)
    assert p.frame.calls.RegisterForDrag[1] == "LeftButton" and p.frame.calls.SetMovable[1] is True
    assert p.frame.scripts.OnDragStart is not None and p.frame.scripts.OnDragStop is not None
    assert p.stageBar.kind == "StatusBar" and p.totalBar.kind == "StatusBar"
    assert p.totalBar.calls.SetHeight[1] < p.stageBar.calls.SetHeight[1]  # the overall bar is the thinner one
    tick(e, 1)
    assert p.runLine.text == "Run 1/2  typical  (rep 1/2)"
    assert str(p.stageLine.text).startswith("Settling  ") and " / " in str(p.stageLine.text)
    assert str(p.totalText.text).startswith("Total  0:0") and " / ~" in str(p.totalText.text)
    bench(e, "stop")


def test_the_panel_follows_settle_baseline_load_and_drain(env):
    e = make(env)
    bench(e, "max 1")  # 3 s of bursts at flight time 1.5: orbs are still flying when the script ends
    seen = stages_seen(e)
    assert seen == ["Settling", "Idle baseline", "Load", "Draining"]


def test_the_panel_shows_kills_and_progress_in_the_load_stage(env):
    e = make(env)
    bench(e, "max 1")  # 120 scripted kills over a 3.0 s load at this test's time scale
    p = panel(e)
    kills = 0
    for _ in range(4000):
        e.stub.tick(STEP)
        found = re.match(r"Load  [\d.]+ / 3\.0 s  \(kills (\d+)/120\)$", str(p.stageLine.text))
        if found and int(found.group(1)) >= 50:
            kills = int(found.group(1))
            break
    assert 50 <= kills < 120
    assert 0.3 < p.stageBar.value < 0.7 and 0 < p.totalBar.value < 1
    assert " / ~" in str(p.totalText.text)
    bench(e, "stop")


def test_the_panel_refreshes_at_most_four_times_a_second(env):
    e = make(env)
    bench(e, "typical 1")
    tick(e, 3)
    texts = set()
    for _ in range(20):  # one second of 20 fps frames
        e.stub.tick(STEP)
        texts.add(str(panel(e).stageLine.text))
    assert 1 <= len(texts) <= 5
    bench(e, "stop")


def test_the_panel_hides_on_finish_stop_error_and_combat(env):
    e = make(env)
    bench(e, "typical 1")
    tick(e, 2)
    assert panel(e).frame.shown is True
    finish(e)
    assert panel(e).frame.shown is False
    bench(e, "typical 1")
    tick(e, 2)
    assert panel(e).frame.shown is True
    bench(e, "stop")
    assert panel(e).frame.shown is False
    bench(e, "typical 1")
    tick(e, 2)
    e.ns.fire("PLAYER_REGEN_DISABLED")
    assert panel(e).frame.shown is False
    bench(e, "typical 1")
    tick(e, 2)
    e.lua.eval("function(o) o.BenchProbe = function() error('boom') end end")(e.orbs)
    tick(e, 20)
    assert not running(e) and panel(e).frame.shown is False


def test_a_broken_panel_never_stops_the_bench(env):
    e = make(env)
    e.lua.execute(
        "local base = CreateFrame; CreateFrame = function(kind, ...) "
        "if kind == 'StatusBar' then error('no bars') end return base(kind, ...) end"
    )
    bench(e, "typical 1")
    assert running(e)
    finish(e)
    check_run(to_py(runs(e)[0]), "typical", 1, 1)
    assert any("progress panel disabled" in line and "no bars" in line for line in chat(e))
    assert e.ns.Bench.panel is None
