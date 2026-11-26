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
        "source": "profiler",
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
            "overallMs": stats(5.0),
            "frameMs": stats(10.0),
        },
        "load": {
            "seconds": 10.0,
            "frames": 1000,
            "addonMs": stats(load, p99=load * 5),
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
        "gcKB": 3.0,
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
    # the real batch
    for rep, load in zip((1, 2, 3), (0.10, 0.14, 0.12)):  # nets 0.08 0.12 0.10
        r = make_run("1.4.2", "20261127T101500", "typical", rep, load, 0.02)
        if rep == 1:
            del r["memStartKB"], r["memEndKB"]  # missing memory in one rep
            del r["baseline"]["overallMs"], r["load"]["overallMs"]
        runs.append(r)
    for rep, load in zip((1, 2, 3), (0.30, 0.01, 0.34)):  # nets 0.27, 0 (clamped), 0.31
        runs.append(make_run("1.4.2", "20261127T101500", "aoe", rep, load, 0.03))
    for rep, load in zip((1, 2, 3), (1.0, 1.1, 1.2)):
        r = make_run("1.4.2", "20261127T101500", "max", rep, load, 0.0)
        for k in ("memStartKB", "memEndKB"):
            del r[k]
        runs.append(r)
    return runs


@pytest.fixture
def sv_file(tmp_path):
    runs = fixture_runs()
    text = (
        "-- fixture\nXPOrbsCharDB = { name = 'Someone' }\n"
        "XPOrbsDB = { bench = { schema = 1, runs = " + lua_literal(runs) + " } }\n"
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
    assert d["schema"] == 1
    assert d["version"] == "1.4.2"
    assert d["date"] == "2026-11-27"
    assert d["rig"] == "Test Rig, 1440p"
    assert d["build"] == "1.16.1 (12345)"
    assert d["screen"] == "2560x1440"
    assert d["source"] == "profiler"
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
    assert len(t["repsDetail"]) == 3
    # timeline is the median rep (rep 3: nets .08 .12 .10 -> the .10 one is rep 3)
    assert t["timeline"]["addonMs"] == pytest.approx([0.3, 0.6, 0.3])
    assert t["timeline"]["step"] == 0.5
    assert t["settings"] == {"orbShape": "starlight", "size": 14, "sound": False}


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
