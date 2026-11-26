"""tools/bench/report.py: ingest, render and notes on a small fixture SavedVariables."""

import copy
import importlib.util
import json
import struct

import pytest
from conftest import ROOT

_spec = importlib.util.spec_from_file_location(
    "bench_report", ROOT / "tools" / "bench" / "report.py"
)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)

FORBIDDEN = ["SECRET", "WTF", "Account", ":\\", "C:/", "/Users"]


# --------------------------------------------------------------------------- fixture


def lua_literal(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "{" + ",".join(lua_literal(x) for x in v) + "}"
    if isinstance(v, dict):
        return (
            "{"
            + ",".join(f"[{json.dumps(k)}]={lua_literal(x)}" for k, x in v.items())
            + "}"
        )
    raise TypeError(v)


def stats(mean, p99=None, n=100):
    return {
        "n": n,
        "mean": mean,
        "p50": mean,
        "p95": mean * 2,
        "p99": p99 if p99 is not None else mean * 3,
        "max": mean * 4,
        "over1": 0,
        "over5": 1,
        "over10": 0,
        "over16": 0,
    }


def make_run(version, batch, scenario, rep, load, base, **extra):
    run = {
        "schema": 2,
        "id": f"{batch}-{scenario}-{rep}",
        "batch": batch,
        "scenario": scenario,
        "scenarioVersion": 1,
        "rep": rep,
        "reps": 3,
        "seed": 4242,
        "addonVersion": version,
        "build": "1.16.1",
        "buildNumber": "12345",
        "interface": 16001,
        "date": f"{batch[0:4]}-{batch[4:6]}-{batch[6:8]}T10:15:0{rep}Z",
        "screenW": 2560,
        "screenH": 1440,
        "uiScale": 0.71,
        "vsync": "0",
        "maxFPS": "0",
        "useMaxFPS": "0",
        "targetFPS": "0",
        "useTargetFPS": "0",
        "source": "internal",
        "profilerMetric": "RecentAverageTime",
        "settings": {
            "orbShape": "starlight",
            "size": 14,
            "sound": False,
            "evil": "C:\\Users\\x",
        },
        "baseline": {
            "seconds": 10.0,
            "frames": 1000,
            "addonMs": stats(base),
            "profilerMs": stats(base + 0.01),
            "overallMs": stats(5.0),
            "frameMs": stats(10.0),
        },
        "load": {
            "seconds": 10.0,
            "frames": 1000,
            "addonMs": stats(load, p99=load * 5),
            "profilerMs": stats(load + 0.02),
            "overallMs": stats(6.0),
            "frameMs": stats(10.0 + rep),
        },
        "kills": 10 * rep,
        "orbs": 100,
        "peakLive": 50 + rep,
        "peakTextures": 100,
        "burstMs": stats(0.1),
        "memStartKB": 800.0,
        "memEndKB": 800.0 + 2.0 * rep,
        "timeline": {
            "step": 0.5,
            "addonMs": [0.1 * rep, 0.2 * rep, 0.1 * rep],
            "addonMaxMs": [0.3, 0.4, 0.3],
            "frameMs": [10.0, 10.5, 10.0],
            "live": [5, 20, 8],
        },
        "account": "SECRET",
        "extraPath": "D:\\Games\\WoW\\WTF\\Account\\SECRET\\SavedVariables",
    }
    run.update(extra)
    return run


def fixture_runs():
    runs = []
    # noise: an older version and an older batch of the target version
    for rep in (1, 2, 3):
        for scen in ("typical", "aoe", "max"):
            runs.append(make_run("1.4.1", "20261101T090000", scen, rep, 9.0, 1.0))
            runs.append(make_run("1.4.2", "20261120T090000", scen, rep, 8.0, 1.0))
    # a newer batch from the broken schema 1 bench (no schema field, profiler LastTime read 0): never used
    for rep in (1, 2, 3):
        legacy = make_run("1.4.2", "20261205T000000", "typical", rep, 7.0, 0.0)
        del legacy["schema"]
        runs.append(legacy)
    # the real batch
    for rep, load in zip((1, 2, 3), (0.10, 0.14, 0.12)):  # nets 0.08 0.12 0.10
        r = make_run("1.4.2", "20261127T101500", "typical", rep, load, 0.02)
        if rep == 1:
            del r["memStartKB"], r["memEndKB"]  # missing memory in one rep
            del r["baseline"]["overallMs"], r["load"]["overallMs"]
            del (
                r["baseline"]["profilerMs"],
                r["load"]["profilerMs"],
            )  # no profiler cross-check in this rep
        runs.append(r)
    for rep, load in zip((1, 2, 3), (0.30, 0.01, 0.34)):  # nets 0.27, 0 (clamped), 0.31
        runs.append(make_run("1.4.2", "20261127T101500", "aoe", rep, load, 0.03))
    for rep, load in zip((1, 2, 3), (1.0, 1.1, 1.2)):
        r = make_run("1.4.2", "20261127T101500", "max", rep, load, 0.0)
        for k in ("memStartKB", "memEndKB"):
            del r[k]
        del (
            r["baseline"]["profilerMs"],
            r["load"]["profilerMs"],
        )  # max: no cross-check in any rep
        runs.append(r)
    return runs


@pytest.fixture
def sv_file(tmp_path):
    runs = fixture_runs()
    text = (
        "-- fixture\nXPOrbsCharDB = { name = 'Someone' }\n"
        "XPOrbsDB = { bench = { schema = 2, runs = " + lua_literal(runs) + " } }\n"
    )
    p = tmp_path / "XPOrbs.lua"
    p.write_text(text, encoding="utf-8")
    return p


def run_main(*argv):
    return report.main([str(a) for a in argv])


@pytest.fixture
def ingested(tmp_path, sv_file):
    data = tmp_path / "data"
    code = run_main(
        "ingest", "--rig", "Test Rig, 1440p", "--sv", sv_file, "--data-dir", data
    )
    assert code == 0
    return data


# --------------------------------------------------------------------------- pure functions


def test_fps_cost():
    assert report.fps_cost(60, 0) == pytest.approx(0.0)
    assert report.fps_cost(60, 1.0) == pytest.approx(3.40, abs=0.01)
    assert report.fps_cost(60, 1000 / 59 - 1000 / 60) == pytest.approx(1.0)
    assert report.fps_cost(144, 1.0) > report.fps_cost(60, 1.0)  # worse at higher fps


@pytest.mark.parametrize(
    "ms,expected",
    [
        (0.0, "Negligible"),
        (0.2499, "Negligible"),
        (0.25, "Light"),
        (0.7499, "Light"),
        (0.75, "Moderate"),
        (1.999, "Moderate"),
        (2.0, "Heavy"),
        (10, "Heavy"),
    ],
)
def test_verdict(ms, expected):
    assert report.verdict(ms) == expected


def test_semver_sort():
    vs = ["1.10.0", "1.4.2", "1.9.0", "1.4.10", "2.0.0"]
    assert sorted(vs, key=report.semver_key) == [
        "1.4.2",
        "1.4.10",
        "1.9.0",
        "1.10.0",
        "2.0.0",
    ]


def test_change_formatting():
    assert report.format_change(None, 0.5) == "new"
    assert report.format_change(0.5, 0.55) == "+10%"
    assert report.format_change(0.5, 0.25) == "-50%"
    assert report.format_change(0.5, 0.5) == "0%"
    assert report.format_change(0.0, 0.5) == "n/a"


def test_segments_break_on_scenario_version():
    pts = [
        {"idx": 0, "sv": 1},
        {"idx": 1, "sv": 1},
        {"idx": 2, "sv": 2},
        {"idx": 4, "sv": 2},  # gap in versions
    ]
    assert [len(s) for s in report.segments(pts)] == [2, 1, 1]


# --------------------------------------------------------------------------- ingest


def test_ingest_picks_batch_and_medians(ingested):
    d = json.loads((ingested / "1.4.2.json").read_text(encoding="utf-8"))
    assert d["schema"] == 2
    assert d["version"] == "1.4.2"
    assert d["date"] == "2026-11-27"
    assert d["rig"] == "Test Rig, 1440p"
    assert d["build"] == "1.16.1 (12345)"
    assert d["screen"] == "2560x1440"
    assert d["source"] == "internal"
    assert d["limits"] == {
        "vsync": "0", "maxFPS": "0", "useMaxFPS": "0", "targetFPS": "0", "useTargetFPS": "0",
    }  # fmt: skip
    assert set(d["scenarios"]) == {"typical", "aoe", "max"}
    t = d["scenarios"]["typical"]
    assert t["reps"] == 3
    assert t["summary"]["netMeanMs"] == pytest.approx(0.10)  # median of .08 .12 .10
    assert t["summary"]["meanMs"] == pytest.approx(0.12)
    assert t["summary"]["baselineMeanMs"] == pytest.approx(0.02)
    assert t["summary"]["p99Ms"] == pytest.approx(0.6)  # median of .5 .7 .6
    assert t["summary"]["fpsLoad"] == pytest.approx(round(1000 / 12.0, 1), abs=0.1)
    assert t["summary"]["shareOfAppPct"] == pytest.approx(
        0.923, abs=0.001
    )  # median of per-rep shares
    assert t["summary"]["kills"] == 20
    assert "gcKB" not in t["summary"]
    # profiler cross-check: per-rep net (load - baseline, floor 0), median over the reps that have it
    assert t["summary"]["profilerMeanMs"] == pytest.approx(
        0.12
    )  # reps 2 and 3: .13 and .11
    assert len(t["repsDetail"]) == 3
    # timeline is the median rep (rep 3: nets .08 .12 .10 -> the .10 one is rep 3)
    assert t["timeline"]["addonMs"] == pytest.approx([0.3, 0.6, 0.3])
    assert t["timeline"]["step"] == 0.5
    assert t["timeline"]["baselineMs"] == pytest.approx(
        0.02
    )  # that rep's idle baseline
    assert t["settings"] == {"orbShape": "starlight", "size": 14, "sound": False}


def test_ingest_profiler_cross_check_is_null_without_data_and_floored(ingested):
    d = json.loads((ingested / "1.4.2.json").read_text(encoding="utf-8"))
    assert d["scenarios"]["max"]["summary"]["profilerMeanMs"] is None
    # aoe: profiler nets .28, 0 (floored: load below baseline) and .32 -> median .28
    assert d["scenarios"]["aoe"]["summary"]["profilerMeanMs"] == pytest.approx(0.28)


def test_ingest_skips_schema_1_runs_and_says_so(tmp_path, sv_file, capsys):
    data = tmp_path / "d"
    assert run_main("ingest", "--rig", "R", "--sv", sv_file, "--data-dir", data) == 0
    assert "skipped 3 run(s)" in capsys.readouterr().out  # the three legacy runs
    d = json.loads((data / "1.4.2.json").read_text(encoding="utf-8"))
    assert (
        d["scenarios"]["typical"]["summary"]["meanMs"] < 1.0
    )  # not the newer schema 1 batch (7 ms)


def test_ingest_errors_when_every_run_is_schema_1(tmp_path, capsys):
    legacy = make_run("1.4.2", "20261127T101500", "typical", 1, 0.1, 0.0)
    del legacy["schema"]
    p = tmp_path / "XPOrbs.lua"
    p.write_text(
        "XPOrbsDB = { bench = { schema = 1, runs = " + lua_literal([legacy]) + " } }\n",
        encoding="utf-8",
    )
    code = run_main("ingest", "--rig", "R", "--sv", p, "--data-dir", tmp_path / "d")
    assert code == 1
    assert "no schema 2 runs" in capsys.readouterr().err
    assert not (tmp_path / "d").exists()


def test_ingest_clamps_negative_net(ingested):
    d = json.loads((ingested / "1.4.2.json").read_text(encoding="utf-8"))
    a = d["scenarios"]["aoe"]
    assert sorted(r["netMeanMs"] for r in a["repsDetail"]) == [0.0, 0.27, 0.31]
    assert a["summary"]["netMeanMs"] == pytest.approx(0.27)
    assert all(r["netMeanMs"] >= 0 for r in a["repsDetail"])


def test_ingest_null_handling(ingested):
    d = json.loads((ingested / "1.4.2.json").read_text(encoding="utf-8"))
    # typical: memory missing in rep 1 only -> median of the other two reps (4 and 6 KB)
    assert d["scenarios"]["typical"]["summary"]["memDeltaKB"] == pytest.approx(5.0)
    # max: memory missing in every rep -> null
    assert d["scenarios"]["max"]["summary"]["memDeltaKB"] is None


def test_ingest_all_other_batches_ignored(ingested):
    d = json.loads((ingested / "1.4.2.json").read_text(encoding="utf-8"))
    for s in d["scenarios"].values():
        assert s["summary"]["meanMs"] < 2.0  # the 8.0/9.0 noise runs never get in


def test_ingest_explicit_batch(tmp_path, sv_file):
    data = tmp_path / "d"
    code = run_main(
        "ingest",
        "--rig",
        "R",
        "--sv",
        sv_file,
        "--data-dir",
        data,
        "--batch",
        "20261120T090000",
    )
    assert code == 0
    d = json.loads((data / "1.4.2.json").read_text(encoding="utf-8"))
    assert d["date"] == "2026-11-20"
    assert d["scenarios"]["typical"]["summary"]["meanMs"] == pytest.approx(8.0)


def test_ingest_output_does_not_leak(ingested):
    text = (ingested / "1.4.2.json").read_text(encoding="utf-8")
    for bad in FORBIDDEN:
        assert bad not in text, bad
    assert text.endswith("\n")
    d = json.loads(text)
    assert list(d) == sorted(d)  # sorted keys


def test_ingest_refuses_overwrite_without_force(tmp_path, sv_file, ingested, capsys):
    code = run_main("ingest", "--rig", "R2", "--sv", sv_file, "--data-dir", ingested)
    assert code == 1
    assert "--force" in capsys.readouterr().err
    assert (
        json.loads((ingested / "1.4.2.json").read_text("utf-8"))["rig"]
        == "Test Rig, 1440p"
    )
    code = run_main(
        "ingest", "--rig", "R2", "--sv", sv_file, "--data-dir", ingested, "--force"
    )
    assert code == 0
    assert json.loads((ingested / "1.4.2.json").read_text("utf-8"))["rig"] == "R2"


def test_ingest_needs_a_path(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("XPORBS_SV", raising=False)
    assert run_main("ingest", "--rig", "R", "--data-dir", tmp_path) == 1
    assert "XPORBS_SV" in capsys.readouterr().err


def test_ingest_uses_env_var(tmp_path, monkeypatch, sv_file):
    monkeypatch.setenv("XPORBS_SV", str(sv_file))
    assert run_main("ingest", "--rig", "R", "--data-dir", tmp_path / "d") == 0


def test_ingest_unknown_version_errors(tmp_path, sv_file, capsys):
    code = run_main(
        "ingest",
        "--rig",
        "R",
        "--sv",
        sv_file,
        "--data-dir",
        tmp_path,
        "--version",
        "9.9.9",
    )
    assert code == 1
    assert "9.9.9" in capsys.readouterr().err


def test_ingest_version_from_toc(tmp_path, sv_file):
    toc = tmp_path / "x.toc"
    toc.write_text("## Interface: 16001\n## Version: 1.4.2\n", encoding="utf-8")
    code = run_main(
        "ingest",
        "--rig",
        "R",
        "--sv",
        sv_file,
        "--data-dir",
        tmp_path / "d",
        "--toc",
        toc,
    )
    assert code == 0


def test_lua_to_py_arrays_become_lists(tmp_path):
    p = tmp_path / "sv.lua"
    p.write_text(
        "XPOrbsDB = { bench = { runs = { { id = 'a', t = { 1, 2, 3 }, e = {} } } } }",
        encoding="utf-8",
    )
    runs = report.load_runs(p)
    assert runs == [{"id": "a", "t": [1, 2, 3], "e": []}]


# --------------------------------------------------------------------------- render + notes


def make_second_version(data_dir, version, scale, max_scenario_version):
    d = json.loads((data_dir / "1.4.2.json").read_text(encoding="utf-8"))
    d = copy.deepcopy(d)
    d["version"] = version
    d["date"] = "2026-12-01"
    for s in d["scenarios"].values():
        s["summary"]["netMeanMs"] = round(s["summary"]["netMeanMs"] * scale, 3)
    d["scenarios"]["max"]["scenarioVersion"] = max_scenario_version
    (data_dir / f"{version}.json").write_text(json.dumps(d), encoding="utf-8")


def png_size(path):
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", head[16:24])


EXPECTED_PNGS = [
    "trends-overview.png",
    *(f"trend-{s}.png" for s in ("typical", "aoe", "max")),
    *(f"timeline-{s}.png" for s in ("typical", "aoe", "max")),
]


def test_render_two_versions(tmp_path, ingested):
    make_second_version(ingested, "1.10.0", 1.5, max_scenario_version=2)
    out = tmp_path / "out"
    assert run_main("render", "--data-dir", ingested, "--out-dir", out) == 0
    readme = (out / "README.md").read_text(encoding="utf-8")
    for name in EXPECTED_PNGS:
        f = out / "img" / name
        assert f.stat().st_size > 0, name
        assert png_size(f) == (1600, 900)
        assert f"img/{name}" in readme
    # newest version (semver: 1.10.0 > 1.4.2) drives the summary
    assert "**Version 1.10.0**" in readme
    assert "ms per frame" in readme and "16.7 ms" in readme
    assert report.HEADLINE_HEADER in readme
    assert readme.index("| 1.10.0 |") < readme.index("| 1.4.2 |")  # newest row first
    assert "\u2020" in readme  # scenarioVersion change marked in the history table
    assert "Generated by `uv run python tools/bench/report.py render`" in readme
    assert (
        "<details><summary>Inside one run (version 1.10.0): click to show</summary>"
        in readme
    )
    assert "</details>" in readme
    assert "after subtracting the idle baseline" in readme
    assert "under 1 fps at 60 fps" in readme
    assert readme.count("under 1 fps at 60 fps") == 1  # merged into one sentence
    assert "2560x1440" not in readme.split("## How it changes")[0]  # rig has 1440p
    assert "- Screen: 2560x1440" in readme
    for bad in [*FORBIDDEN, str(tmp_path), str(ROOT)]:
        assert bad not in readme, bad


def test_render_single_version(tmp_path, ingested):
    out = tmp_path / "out"
    assert run_main("render", "--data-dir", ingested, "--out-dir", out) == 0
    for name in EXPECTED_PNGS:
        assert (out / "img" / name).stat().st_size > 0


def test_render_rig_filter(tmp_path, ingested):
    make_second_version(ingested, "1.5.0", 1.0, 1)
    p = ingested / "1.5.0.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["rig"] = "Other PC"
    p.write_text(json.dumps(d), encoding="utf-8")
    out = tmp_path / "out"
    assert run_main("render", "--data-dir", ingested, "--out-dir", out) == 0
    assert "Other PC" in (out / "README.md").read_text(encoding="utf-8")
    out2 = tmp_path / "out2"
    assert (
        run_main(
            "render",
            "--data-dir",
            ingested,
            "--out-dir",
            out2,
            "--rig",
            "Test Rig, 1440p",
        )
        == 0
    )
    readme = (out2 / "README.md").read_text(encoding="utf-8")
    assert "**Version 1.4.2**" in readme and "Other PC" not in readme


def test_notes(ingested, capsys):
    make_second_version(ingested, "1.4.3", 1.5, max_scenario_version=2)
    assert run_main("notes", "--data-dir", ingested) == 0
    out = capsys.readouterr().out
    assert report.NOTES_HEADER in out
    assert "Full report: docs/performance/README.md" in out
    assert "XP Orbs 1.4.3" in out
    assert "+50%" in out  # typical: 1.5x the previous version
    max_row = next(line for line in out.splitlines() if line.startswith("| Maximum"))
    assert max_row.rstrip().endswith("| new |")  # scenarioVersion changed
    assert run_main("notes", "--data-dir", ingested, "--version", "1.4.2") == 0
    first = capsys.readouterr().out
    assert "| new |" in first and "XP Orbs 1.4.2" in first


def test_notes_unknown_version(ingested, capsys):
    assert run_main("notes", "--data-dir", ingested, "--version", "7.7.7") == 1
    assert "7.7.7" in capsys.readouterr().err


def readme_for(tmp_path, data_dir, **changes):
    """Render the 1.4.2 data (with top-level fields changed) and return the README text."""
    path = data_dir / "1.4.2.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    d.update(changes)
    path.write_text(json.dumps(d), encoding="utf-8")
    out = tmp_path / "out"
    assert run_main("render", "--data-dir", data_dir, "--out-dir", out) == 0
    return (out / "README.md").read_text(encoding="utf-8")


def test_readme_profiler_column_shows_the_figure_or_na(tmp_path, ingested):
    readme = readme_for(tmp_path, ingested)
    assert "| Game profiler (cross-check) |" in readme
    typical = next(
        ln for ln in readme.splitlines() if ln.startswith("| Typical play |")
    )
    maxrow = next(
        ln for ln in readme.splitlines() if ln.startswith("| Maximum settings")
    )
    assert typical.rstrip().endswith("| 0.12 ms |")
    assert maxrow.rstrip().endswith("| n/a |")
    assert "recent average" in readme and "cross-check" in readme
    assert "XP Orbs' own timers" in readme and "minus an idle baseline" in readme


def test_readme_says_so_when_no_scenario_has_a_profiler_figure(tmp_path, ingested):
    path = ingested / "1.4.2.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    for sc in d["scenarios"].values():
        sc["summary"]["profilerMeanMs"] = None
    path.write_text(json.dumps(d), encoding="utf-8")
    readme = readme_for(tmp_path, ingested)
    assert "no cross-check figure" in readme
    assert all(
        ln.rstrip().endswith("| n/a |")
        for ln in readme.splitlines()
        if ln.startswith(("| Typical play |", "| AoE farming |", "| Maximum settings"))
    )


def test_notes_carry_the_profiler_column(ingested, capsys):
    assert run_main("notes", "--data-dir", ingested) == 0
    out = capsys.readouterr().out
    typical = next(ln for ln in out.splitlines() if ln.startswith("| Typical play"))
    assert "| 0.12 ms |" in typical and "| Game profiler (cross-check) |" in out
    assert "| n/a |" in next(
        ln for ln in out.splitlines() if ln.startswith("| Maximum")
    )


def test_screen_comes_from_the_physical_size_and_is_left_out_when_unknown(
    tmp_path, ingested
):
    # the rig label has no resolution: the sentence names the physical one
    readme = readme_for(tmp_path, ingested, rig="Plain Rig")
    head = readme.split("###")[0]
    assert "(game build 1.16.1 (12345), 2560x1440 screen)." in head
    assert "- Screen: 2560x1440" in readme
    # no screen recorded: no screen part anywhere, and never the word unknown
    readme = readme_for(tmp_path, ingested, rig="Plain Rig", screen=None)
    assert (
        "screen)" not in readme
        and "- Screen:" not in readme
        and "unknown" not in readme
    )
    assert "(game build 1.16.1 (12345))." in readme


def low_cost_set(**nets):
    return {
        "version": "1.0.0",
        "rig": "Rig",
        "build": "1.16.1",
        "screen": None,
        "scenarios": {s: {"summary": {"netMeanMs": ms}} for s, ms in nets.items()},
    }


def test_scenario_names_are_lower_case_inside_a_sentence():
    text = report.summary_paragraph(low_cost_set(typical=0.05, aoe=0.1, max=0.2))
    assert (
        "Typical play, AoE farming and the maximum-settings stress test "
        "(a worst case nobody plays in) each cost under 1 fps at 60 fps "
        "(0.05, 0.10 and 0.20 ms per frame)." in text
    )
    assert "and The " not in text and ", Typical" not in text
    # a heavy max scenario starts its own sentence: capitalised there
    text = report.summary_paragraph(low_cost_set(typical=0.05, aoe=0.1, max=1.5))
    assert "Typical play and AoE farming each cost under 1 fps" in text
    assert (
        ". The maximum-settings stress test (a worst case nobody plays in) costs about"
        in text
    )
    text = report.summary_paragraph(low_cost_set(aoe=0.1))
    assert text.endswith("AoE farming costs under 1 fps at 60 fps (0.10 ms per frame).")


def test_active_limiters():
    on = report.active_limiters
    zero = {
        "vsync": "0",
        "maxFPS": "0",
        "useMaxFPS": "0",
        "targetFPS": "0",
        "useTargetFPS": "0",
    }
    assert on(zero) == [] and on(None) == [] and on({}) == []
    assert on({**zero, "targetFPS": "90", "useTargetFPS": "1"}) == ["Target FPS (90)"]
    assert (
        on({**zero, "targetFPS": "90"}) == []
    )  # a value with the switch off is no limiter
    assert on({**zero, "maxFPS": "144", "useMaxFPS": "1"}) == ["Max FPS (144)"]
    assert on({"maxFPS": "144", "useMaxFPS": None}) == [
        "Max FPS (144)"
    ]  # no switch cvar: the value counts
    both = {
        **zero,
        "maxFPS": "60",
        "useMaxFPS": "1",
        "vsync": "1",
        "targetFPS": "90",
        "useTargetFPS": "1",
    }
    assert on(both) == ["Max FPS (60)", "Target FPS (90)", "vsync"]


def test_the_limiter_line_appears_only_when_a_limiter_was_on(tmp_path, ingested):
    assert "limited by" not in readme_for(tmp_path, ingested)
    limits = {
        "vsync": "0",
        "maxFPS": "0",
        "useMaxFPS": "0",
        "targetFPS": "90",
        "useTargetFPS": "1",
    }
    readme = readme_for(tmp_path, ingested, limits=limits)
    assert (
        "Frame rate was limited by Target FPS (90) during this run, which affects the "
        "fps figures but not the ms cost." in readme
    )
    limits["vsync"] = "1"
    assert "limited by Target FPS (90) and vsync during" in readme_for(
        tmp_path, ingested, limits=limits
    )


def test_load_data_skips_a_schema_1_data_file(tmp_path, ingested, capsys):
    old = json.loads((ingested / "1.4.2.json").read_text(encoding="utf-8"))
    old["schema"], old["version"] = 1, "1.4.0"
    (ingested / "1.4.0.json").write_text(json.dumps(old), encoding="utf-8")
    assert run_main("render", "--data-dir", ingested, "--out-dir", tmp_path / "o") == 0
    assert "skipping 1.4.0.json (not schema 2)" in capsys.readouterr().err


def test_reference_label_text():
    assert f"{report.one_fps_ms():.2f}" == "0.28"


def test_timeline_is_net_of_baseline_and_tolerates_old_files(tmp_path, ingested):
    tl = {
        "step": 0.5,
        "addonMs": [0.05, 0.3, 0.1],
        "baselineMs": 0.1,
        "live": [1, 2, 3],
    }
    assert report.net_timeline(tl) == pytest.approx([0.0, 0.2, 0.0])  # clamped at 0
    del tl["baselineMs"]  # older data files have no baseline: treated as 0
    assert report.net_timeline(tl) == pytest.approx([0.05, 0.3, 0.1])
    d = json.loads((ingested / "1.4.2.json").read_text(encoding="utf-8"))
    for s in d["scenarios"].values():
        del s["timeline"]["baselineMs"]
    (ingested / "1.4.2.json").write_text(json.dumps(d), encoding="utf-8")
    assert run_main("render", "--data-dir", ingested, "--out-dir", tmp_path / "o") == 0


def test_profiler_reading_zero_against_real_load_is_no_cross_check():
    # in game the profiler can answer 0 for XP Orbs while our own timers see real cost: that is no cross-check
    dead = make_run("1.4.2", "B", "max", 1, 1.6, 0.0)
    dead["load"]["profilerMs"], dead["baseline"]["profilerMs"] = (
        stats(0.0004),
        stats(0.0),
    )
    assert report.rep_values(dead)["profilerMeanMs"] is None
    live = make_run("1.4.2", "B", "max", 1, 1.6, 0.0)
    live["load"]["profilerMs"], live["baseline"]["profilerMs"] = stats(1.2), stats(0.1)
    assert report.rep_values(live)["profilerMeanMs"] == pytest.approx(1.1)
    idle = make_run("1.4.2", "B", "typical", 1, 0.0002, 0.0)
    idle["load"]["profilerMs"], idle["baseline"]["profilerMs"] = (
        stats(0.0001),
        stats(0.0),
    )
    assert report.rep_values(idle)["profilerMeanMs"] == pytest.approx(0.0001)
