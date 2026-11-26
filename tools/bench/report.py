"""Turn in-game XP Orbs benchmark runs into a public performance report.

Commands (see tools/bench/SCHEMA.md for the data formats):

    uv run python tools/bench/report.py ingest --rig "<label>" [--sv PATH] [--version X.Y.Z]
                                                [--batch ID] [--force]
    uv run python tools/bench/report.py render [--rig LABEL]
    uv run python tools/bench/report.py notes [--version X.Y.Z] [--rig LABEL]

Dev tooling only: never packaged. Standard library + matplotlib + lupa.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import itertools

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator

try:
    import lupa.lua51 as lupa_rt
except ImportError:  # pragma: no cover
    import lupa.luajit21 as lupa_rt

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "docs" / "performance"
DEFAULT_DATA_DIR = DEFAULT_OUT_DIR / "data"
DEFAULT_TOC = ROOT / "XPOrbs.toc"
README_REL = "docs/performance/README.md"
SCHEMA = 2
SV_ENV = "XPORBS_SV"
PROFILER_DEAD_MS = 0.005  # a profiler mean under this, against real measured load, is treated as missing

SCENARIOS = ("typical", "aoe", "max")
SCENARIO_LABEL = {
    "typical": "Typical play",
    "aoe": "AoE farming",
    "max": "Maximum settings stress test",
}
SCENARIO_SHORT = {
    "typical": "Typical play",
    "aoe": "AoE farming",
    "max": "Max stress test",
}
SCENARIO_COLOUR = {"typical": "#2a9d8f", "aoe": "#c99a06", "max": "#e76f51"}
SCENARIO_TEXT = {"typical": "#21867a", "aoe": "#8a6a00", "max": "#c4502f"}  # text
FS_TICK = 14
FS_LABEL = 14
FS_TITLE = 17
FS_NOTE = 12
FS_DIRECT = 13
YLABEL = "ms per frame\n(lower is better)"
TEXT = "#222222"
GRID = "#e5e5e5"

SETTINGS_KEYS = (
    "orbShape",
    "size",
    "density",
    "cap",
    "flightPath",
    "style",
    "popMode",
    "flightMode",
    "flightTime",
    "trail",
    "glowIntensity",
    "sound",
)
TIMELINE_KEYS = ("addonMs", "addonMaxMs", "frameMs", "live")
SAFE_TEXT = re.compile(r"^[\w .\-()]{1,40}$")
LIMIT_KEYS = ("vsync", "maxFPS", "useMaxFPS", "targetFPS", "useTargetFPS")
SAFE_CVAR = re.compile(r"^[\w.\-]{1,16}$")
HEADLINE_HEADER = (
    "| Scenario | Average cost per frame | Worst 1% of frames | fps cost at 60 fps "
    "| fps cost at 144 fps | Verdict | Game profiler (cross-check) |"
)
NOTES_HEADER = (
    "| Scenario | Average cost | Worst 1% | fps cost at 60 fps | Verdict "
    "| Game profiler (cross-check) | Change vs previous |"
)


class BenchError(Exception):
    """A user-facing error: printed without a traceback."""


# --------------------------------------------------------------------------- pure maths


def fps_cost(fps: float, ms: float) -> float:
    """fps lost when `ms` of extra work is added to every frame at `fps` fps."""
    return fps - 1000.0 / (1000.0 / fps + ms)


def verdict(net_mean_ms: float) -> str:
    if net_mean_ms < 0.25:
        return "Negligible"
    if net_mean_ms < 0.75:
        return "Light"
    if net_mean_ms < 2.0:
        return "Moderate"
    return "Heavy"


def semver_key(version: str) -> tuple[int, ...]:
    """Numeric sort key: '1.10.0' sorts after '1.9.0'."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


def one_fps_ms() -> float:
    """Extra ms per frame that costs exactly 1 fps at 60 fps."""
    return 1000.0 / 59.0 - 1000.0 / 60.0


def change_pct(prev: float | None, cur: float) -> float | None:
    """Percent change of cur against prev; None when there is no usable baseline."""
    if prev is None or prev <= 0:
        return None
    return (cur - prev) / prev * 100.0


def format_change(prev: float | None, cur: float) -> str:
    pct = change_pct(prev, cur)
    if pct is None:
        return "new" if prev is None else "n/a"
    if abs(pct) < 0.5:
        return "0%"
    return f"{pct:+.0f}%"


def median(values):
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def _round(v, digits=3):
    if v is None:
        return None
    return round(float(v), digits)


def _round_count(v):
    """Counts stay integers when whole (median of two ints can be x.5)."""
    if v is None:
        return None
    v = float(v)
    return int(v) if v == int(v) else round(v, 1)


def fmt_ms(ms: float) -> str:
    if ms < 0.01:
        return f"{ms:.3f} ms"
    return f"{ms:.2f} ms"


def fmt_fps(x: float) -> str:
    return f"{x:.1f} fps"


# --------------------------------------------------------------------------- SavedVariables


def lua_to_py(obj):
    """Lua value -> Python. Array-like tables (keys 1..n) become lists, others dicts."""
    kind = lupa_rt.lua_type(obj)
    if kind == "table":
        keys = list(obj.keys())
        if keys and all(
            isinstance(k, (int, float)) and float(k) == int(k) for k in keys
        ):
            ints = sorted(int(k) for k in keys)
            if ints == list(range(1, len(ints) + 1)):
                return [lua_to_py(obj[i]) for i in ints]
        if not keys:
            return []
        return {str(k): lua_to_py(obj[k]) for k in keys}
    if kind in ("function", "thread", "userdata"):
        return None
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int, float, str)):
        return obj
    return str(obj)


def load_runs(sv_path: Path) -> list[dict]:
    """Execute a SavedVariables file and return XPOrbsDB.bench.runs as Python dicts."""
    try:
        text = sv_path.read_text(encoding="utf-8-sig")
    except OSError:
        raise BenchError("could not read the SavedVariables file") from None
    lua = lupa_rt.LuaRuntime(unpack_returned_tuples=True)
    # The file is plain data; do not let it touch the machine.
    lua.execute("os, io, package, require, dofile, loadfile = nil")
    try:
        lua.execute(text)
    except (lupa_rt.LuaError, lupa_rt.LuaSyntaxError) as exc:
        raise BenchError(
            f"SavedVariables file is not valid Lua ({type(exc).__name__})"
        ) from None
    db = lua.globals().XPOrbsDB
    if db is None or lupa_rt.lua_type(db) != "table":
        raise BenchError("no XPOrbsDB table in the SavedVariables file")
    bench = db["bench"]
    if bench is None or lupa_rt.lua_type(bench) != "table":
        raise BenchError("XPOrbsDB.bench not found: run /xporbs bench in game first")
    runs = bench["runs"]
    if runs is None or lupa_rt.lua_type(runs) != "table":
        raise BenchError("XPOrbsDB.bench.runs not found: no benchmark runs saved")
    converted = lua_to_py(runs)
    if isinstance(converted, dict):  # sparse/odd table: keep the dict values
        converted = list(converted.values())
    return [r for r in converted if isinstance(r, dict)]


def toc_version(toc: Path) -> str:
    try:
        for line in toc.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"##\s*Version:\s*(\S+)", line)
            if m:
                return m.group(1)
    except OSError:
        pass
    raise BenchError("could not read '## Version:' from the .toc; pass --version")


# --------------------------------------------------------------------------- ingest


def _get(d, *path):
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def rep_values(run: dict) -> dict:
    """Per-rep numbers (unrounded; None where the run did not record them)."""
    load_mean = _num(_get(run, "load", "addonMs", "mean"))
    base_mean = _num(_get(run, "baseline", "addonMs", "mean"))
    if load_mean is None or base_mean is None:
        raise BenchError(f"run {_safe_id(run)} has no addonMs mean for load/baseline")
    frame_load = _num(_get(run, "load", "frameMs", "mean"))
    frame_base = _num(_get(run, "baseline", "frameMs", "mean"))
    mem_start = _num(run.get("memStartKB"))
    mem_end = _num(run.get("memEndKB"))
    prof_load = _num(_get(run, "load", "profilerMs", "mean"))
    prof_base = _num(_get(run, "baseline", "profilerMs", "mean"))
    if (
        prof_load is not None
        and prof_load < PROFILER_DEAD_MS
        and load_mean >= PROFILER_DEAD_MS * 4
    ):
        # the profiler answered but never saw XP Orbs work (reads ~0 while our timers see real cost): no cross-check
        prof_load = prof_base = None
    return {
        "netMeanMs": max(0.0, load_mean - base_mean),
        "profilerMeanMs": max(0.0, prof_load - prof_base)
        if prof_load is not None and prof_base is not None
        else None,
        "meanMs": load_mean,
        "baselineMeanMs": base_mean,
        "p95Ms": _num(_get(run, "load", "addonMs", "p95")),
        "p99Ms": _num(_get(run, "load", "addonMs", "p99")),
        "maxMs": _num(_get(run, "load", "addonMs", "max")),
        "over5": _num(_get(run, "load", "addonMs", "over5")),
        "over16": _num(_get(run, "load", "addonMs", "over16")),
        "frameMsBaseline": frame_base,
        "frameMsLoad": frame_load,
        "fpsBaseline": 1000.0 / frame_base if frame_base else None,
        "fpsLoad": 1000.0 / frame_load if frame_load else None,
        "burstMeanMs": _num(_get(run, "burstMs", "mean")),
        "burstMaxMs": _num(_get(run, "burstMs", "max")),
        "peakLive": _num(run.get("peakLive")),
        "peakTextures": _num(run.get("peakTextures")),
        "kills": _num(run.get("kills")),
        "orbs": _num(run.get("orbs")),
        "memDeltaKB": mem_end - mem_start
        if mem_start is not None and mem_end is not None
        else None,
        "shareOfAppPct": 100.0 * load_mean / frame_load if frame_load else None,
    }


COUNT_FIELDS = {"over5", "over16", "peakLive", "peakTextures", "kills", "orbs"}
FPS_FIELDS = {"fpsBaseline", "fpsLoad"}


def summarise(reps: list[dict]) -> dict:
    out = {}
    for key in reps[0]:
        m = median(r[key] for r in reps)
        if key in COUNT_FIELDS:
            out[key] = _round_count(m)
        elif key in FPS_FIELDS:
            out[key] = _round(m, 1)
        else:
            out[key] = _round(m, 3)
    return out


def _safe_id(run: dict) -> str:
    rid = run.get("id")
    return rid if isinstance(rid, str) and SAFE_TEXT.match(rid) else "?"


def _clean_text(v, default):
    return v if isinstance(v, str) and SAFE_TEXT.match(v) else default


def _clean_settings(settings) -> dict:
    out = {}
    if not isinstance(settings, dict):
        return out
    for key in SETTINGS_KEYS:
        v = settings.get(key)
        if (
            isinstance(v, (bool, int, float))
            or isinstance(v, str)
            and SAFE_TEXT.match(v)
        ):
            out[key] = v
    return out


def _clean_timeline(tl) -> dict | None:
    if not isinstance(tl, dict):
        return None
    out = {"step": _round(_num(tl.get("step")) or 0.5, 3)}
    for key in TIMELINE_KEYS:
        arr = tl.get(key)
        arr = arr if isinstance(arr, list) else []
        out[key] = [_round(_num(x), 3) for x in arr]
    return out


def build_scenario(runs: list[dict]) -> dict:
    """One scenario's published block from its reps (already one batch)."""
    runs = sorted(runs, key=lambda r: _num(r.get("rep")) or 0)
    reps = [rep_values(r) for r in runs]
    summary = summarise(reps)
    # timeline comes from the rep whose netMeanMs is the median
    target = summary["netMeanMs"]
    pick = min(range(len(reps)), key=lambda i: abs(reps[i]["netMeanMs"] - target))
    first = runs[0]
    timeline = _clean_timeline(runs[pick].get("timeline")) or {
        "step": 0.5,
        "addonMs": [],
        "addonMaxMs": [],
        "frameMs": [],
        "live": [],
    }
    # the timeline rep's idle baseline, so charts can show net cost like the table
    timeline["baselineMs"] = _round(reps[pick]["baselineMeanMs"])
    return {
        "scenarioVersion": int(_num(first.get("scenarioVersion")) or 1),
        "settings": _clean_settings(first.get("settings")),
        "reps": len(runs),
        "summary": summary,
        "repsDetail": [
            {
                "netMeanMs": _round(r["netMeanMs"]),
                "p99Ms": _round(r["p99Ms"]),
                "fpsLoad": _round(r["fpsLoad"], 1),
            }
            for r in reps
        ],
        "timeline": timeline,
    }


def check_rig(rig: str) -> str:
    rig = (rig or "").strip()
    if not rig or len(rig) > 80 or "\n" in rig:
        raise BenchError("--rig must be a short label (1-80 characters)")
    if "\\" in rig or re.search(r"[A-Za-z]:[\\/]", rig):
        raise BenchError("--rig looks like a path; use a hardware label")
    return rig


def current_schema_runs(runs: list[dict]) -> tuple[list[dict], int]:
    """(runs recorded with the current bench schema, how many older ones were left out).

    A run without a schema field predates schema 2 (schema 1 timed XP Orbs through a
    profiler call that read 0 on this client)."""
    keep = [r for r in runs if r.get("schema") == SCHEMA]
    return keep, len(runs) - len(keep)


def select_runs(
    runs: list[dict], version: str, batch: str | None
) -> tuple[str, list[dict]]:
    mine = [r for r in runs if r.get("addonVersion") == version]
    if not mine:
        raise BenchError(f"no runs for addon version {version} in the SavedVariables")
    batches = {r.get("batch") for r in mine if isinstance(r.get("batch"), str)}
    if batch is not None:
        if batch not in batches:
            raise BenchError(f"batch {batch} has no runs for version {version}")
        chosen = batch
    elif batches:
        chosen = max(batches)
    else:
        raise BenchError(f"runs for version {version} have no batch id")
    return chosen, [r for r in mine if r.get("batch") == chosen]


def _clean_limits(run: dict) -> dict:
    """The fps-limiter cvars of a run (short plain strings, else null)."""
    out = {}
    for key in LIMIT_KEYS:
        v = run.get(key)
        out[key] = v if isinstance(v, str) and SAFE_CVAR.match(v) else None
    return out


def build_dataset(runs: list[dict], version: str, rig: str) -> dict:
    by_scen: dict[str, list[dict]] = {}
    for r in runs:
        name = r.get("scenario")
        if name in SCENARIOS:
            by_scen.setdefault(name, []).append(r)
    if not by_scen:
        raise BenchError("no runs with a known scenario (typical, aoe, max)")
    newest = max(runs, key=lambda r: str(r.get("date", "")))
    build = _clean_text(newest.get("build"), "unknown")
    build_no = _clean_text(
        str(newest["buildNumber"]) if newest.get("buildNumber") is not None else None,
        None,
    )
    sw, sh = _num(newest.get("screenW")), _num(newest.get("screenH"))
    date = str(newest.get("date", ""))[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        b = str(newest.get("batch", ""))
        date = f"{b[0:4]}-{b[4:6]}-{b[6:8]}" if len(b) >= 8 else "unknown"
    scenarios = {}
    for name in SCENARIOS:
        if name in by_scen:
            group = by_scen[name]
            sv = _num(group[-1].get("scenarioVersion"))
            group = [r for r in group if _num(r.get("scenarioVersion")) == sv]
            scenarios[name] = build_scenario(group)
    return {
        "schema": SCHEMA,
        "version": version,
        "date": date,
        "rig": rig,
        "build": f"{build} ({build_no})" if build_no else build,
        "screen": f"{int(sw)}x{int(sh)}" if sw and sh else None,
        "source": "internal",
        "limits": _clean_limits(runs[0]),
        "scenarios": scenarios,
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def show(path: Path) -> str:
    """Path for console output: repo-relative when possible, else just the name."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def cmd_ingest(args) -> int:
    sv = args.sv or os.environ.get(SV_ENV)
    if not sv:
        raise BenchError(
            f"no SavedVariables file: pass --sv PATH or set the {SV_ENV} environment variable"
        )
    rig = check_rig(args.rig)
    version = args.version or toc_version(Path(args.toc))
    if not re.match(r"^\d+(\.\d+)*$", version):
        raise BenchError("--version must look like 1.4.2")
    out = Path(args.data_dir) / f"{version}.json"
    if out.exists() and not args.force:
        raise BenchError(f"{show(out)} already exists; use --force to overwrite")
    runs = load_runs(Path(sv))
    runs, skipped = current_schema_runs(runs)
    if skipped:
        print(
            f"skipped {skipped} run(s) from an older bench schema (their timing "
            "was unreliable)"
        )
    if not runs:
        raise BenchError(
            f"no schema {SCHEMA} runs in the SavedVariables: run /xporbs bench in "
            "game with this version of the bench"
        )
    batch, chosen = select_runs(runs, version, args.batch)
    data = build_dataset(chosen, version, rig)
    write_json(out, data)
    print(f"wrote {show(out)} (version {version}, batch {batch}, {len(chosen)} runs)")
    return 0


# --------------------------------------------------------------------------- loading data


def load_data(data_dir: Path) -> list[dict]:
    sets = []
    for path in sorted(Path(data_dir).glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"warning: skipping unreadable {path.name}", file=sys.stderr)
            continue
        if (
            isinstance(d, dict)
            and d.get("schema") == SCHEMA
            and isinstance(d.get("version"), str)
            and isinstance(d.get("scenarios"), dict)
        ):
            sets.append(d)
        else:
            print(
                f"warning: skipping {path.name} (not schema {SCHEMA})", file=sys.stderr
            )
    if not sets:
        raise BenchError("no data files found; run the ingest command first")
    return sets


def pick_rig(sets: list[dict], rig: str | None) -> str:
    rigs = {d.get("rig") for d in sets}
    if rig:
        if rig not in rigs:
            raise BenchError(f"no data for rig '{rig}'")
        return rig
    newest = max(sets, key=lambda d: semver_key(d["version"]))
    return newest["rig"]


def rig_sets(sets: list[dict], rig: str) -> list[dict]:
    return sorted(
        (d for d in sets if d.get("rig") == rig), key=lambda d: semver_key(d["version"])
    )


def scenario_points(sets: list[dict], scen: str) -> list[dict]:
    """Points for one scenario over the version-ordered sets: idx = x position."""
    pts = []
    for idx, d in enumerate(sets):
        s = d["scenarios"].get(scen)
        if not s:
            continue
        sm = s["summary"]
        pts.append(
            {
                "idx": idx,
                "version": d["version"],
                "sv": s.get("scenarioVersion", 1),
                "net": sm["netMeanMs"],
                "p99": sm.get("p99Ms"),
            }
        )
    return pts


def segments(points: list[dict]) -> list[list[dict]]:
    """Split into runs of adjacent versions sharing a scenarioVersion."""
    segs: list[list[dict]] = []
    for p in points:
        if (
            segs
            and segs[-1][-1]["idx"] + 1 == p["idx"]
            and segs[-1][-1]["sv"] == p["sv"]
        ):
            segs[-1].append(p)
        else:
            segs.append([p])
    return segs


def previous_comparable(points: list[dict], i: int) -> float | None:
    """netMeanMs of the previous point if it shares the scenarioVersion, else None."""
    if i == 0 or points[i - 1]["sv"] != points[i]["sv"]:
        return None
    return points[i - 1]["net"]


# --------------------------------------------------------------------------- charts


def _style():
    return plt.rc_context(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "text.color": TEXT,
            "axes.labelcolor": TEXT,
            "xtick.color": TEXT,
            "ytick.color": TEXT,
            "axes.edgecolor": "#bbbbbb",
            "font.size": FS_TICK,
            "xtick.labelsize": FS_TICK,
            "ytick.labelsize": FS_TICK,
        }
    )


def _new_axes():
    fig = plt.figure(figsize=(8, 4.5), dpi=200, layout="constrained")
    ax = fig.add_subplot(111)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_locator(MaxNLocator(5))
    return fig, ax


def _title(prefix: str, label: str, suffix: str = "") -> str:
    """One line when it fits at 17 pt, else the scenario name on a second line."""
    one = f"{prefix}: {label}{suffix}"
    return one if len(one) <= 46 else f"{prefix}:\n{label}{suffix}"


def _finish(fig, ax, path: Path, title: str, ylabel: str = YLABEL):
    pad = 34 if ax.get_legend() else 12  # room for the reference-line key
    ax.set_title(title, loc="left", fontsize=FS_TITLE, color=TEXT, pad=pad)
    ax.set_ylabel(ylabel, fontsize=FS_LABEL)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def spread(ys: list[float], gap: float, heights: list[float] | None = None):
    """Nudge label positions upward so neighbours do not overlap.

    `gap` is the separation needed between two one-line labels (data units);
    `heights` scales it per label (2 for a two-line label)."""
    heights = heights or [1.0] * len(ys)
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    for a, b in itertools.pairwise(order):
        need = gap * (heights[a] + heights[b]) / 2
        if out[b] - out[a] < need:
            out[b] = out[a] + need
    return out


def label_room(n: int, inches: float, axes_in: float = 6.0) -> float:
    """Extra x range (category units) so a right-hand label of `inches` fits."""
    span = max(n - 1, 1) + 0.6
    frac = inches / axes_in
    return span * frac / (1 - frac)


def _categorical_x(ax, versions: list[str], room: float):
    n = len(versions)
    ax.set_xticks(range(n), versions)
    ax.set_xlim(-0.5, n - 1 + 0.15 + room)
    ax.tick_params(axis="x", length=0)
    ax.set_xlabel("XP Orbs release", fontsize=FS_LABEL)
    if n > 6:
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(45)
            lbl.set_ha("right")


def _ref_line(ax, top: float) -> float:
    """Dashed '1 fps at 60 fps' line when it fits within ~3x the data; returns new top.

    Labelled through a small key just above the plot (under the title)."""
    ref = one_fps_ms()
    if ref > 3 * top:
        return top
    ax.axhline(ref, color="#777777", linestyle="--", linewidth=1.2, zorder=1)
    handle = Line2D([], [], color="#777777", linestyle="--", linewidth=1.2)
    ax.legend(
        [handle],
        [f"costs 1 fps at 60 fps ({ref:.2f} ms)"],
        loc="lower left",
        bbox_to_anchor=(0.0, 1.0),
        frameon=False,
        fontsize=FS_NOTE,
        labelcolor="#555555",
        borderaxespad=0.2,
        handlelength=2.2,
    )
    return max(top, ref)


def _change_points(points: list[dict]) -> list[tuple[float, str]]:
    """(x between the two points, version where the new test starts) per break."""
    out = []
    for i in range(1, len(points)):
        if points[i]["sv"] != points[i - 1]["sv"]:
            x = (points[i]["idx"] + points[i - 1]["idx"]) / 2
            out.append((x, points[i]["version"]))
    return out


def _mark_changes(ax, xs: list[float]):
    for x in sorted(set(xs)):
        ax.axvline(x, color="#999999", linestyle=":", linewidth=1.2)
        ax.text(
            x,
            0.97,
            " scenario changed",
            transform=ax.get_xaxis_transform(),
            fontsize=FS_NOTE,
            color="#555555",
            va="top",
        )


def _first_release_note(ax):
    ax.text(
        0.99,
        0.97,
        "first measured release",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=FS_NOTE,
        color="#555555",
    )


def chart_trend(path: Path, scen: str, versions: list[str], points: list[dict]):
    colour = SCENARIO_COLOUR[scen]
    dark = SCENARIO_TEXT[scen]
    n = len(versions)
    with _style():
        fig, ax = _new_axes()
        for seg in segments(points):
            xs = [p["idx"] for p in seg]
            ax.plot(
                xs,
                [p["p99"] if p["p99"] is not None else p["net"] for p in seg],
                color=colour,
                alpha=0.4,
                linewidth=1.4,
                marker="o",
                markersize=4,
                zorder=2,
            )
            ax.plot(
                xs,
                [p["net"] for p in seg],
                color=colour,
                linewidth=2.6,
                marker="o",
                markersize=8,
                zorder=3,
            )
        _mark_changes(ax, [x for x, _ in _change_points(points)])
        top = max((p["p99"] or p["net"]) for p in points)
        top = max(top, max(p["net"] for p in points), 0.05)
        top = _ref_line(ax, top)
        ylim = top * 1.18
        ax.set_ylim(0, ylim)
        _categorical_x(ax, versions, label_room(n, 1.3))
        last = points[-1]
        ys = [last["net"], last["p99"] if last["p99"] is not None else last["net"]]
        ly = spread(ys, ylim * 0.065)
        ax.text(
            last["idx"] + 0.15,
            ly[0],
            "Average",
            color=dark,
            fontsize=FS_DIRECT,
            fontweight="bold",
            va="center",
        )
        if last["p99"] is not None:
            ax.text(
                last["idx"] + 0.15,
                ly[1],
                "Worst 1%",
                color=dark,
                fontsize=FS_DIRECT,
                va="center",
            )
        if len(points) == 1:
            _first_release_note(ax)
        title = _title("Cost per frame across releases", SCENARIO_LABEL[scen])
        _finish(fig, ax, path, title)


def chart_overview(path: Path, versions: list[str], series: dict[str, list[dict]]):
    n = len(versions)
    with _style():
        fig, ax = _new_axes()
        top = 0.05
        notes: dict[str, str] = {}
        change_x: list[float] = []
        for scen, pts in series.items():
            colour = SCENARIO_COLOUR[scen]
            for seg in segments(pts):
                ax.plot(
                    [p["idx"] for p in seg],
                    [p["net"] for p in seg],
                    color=colour,
                    linewidth=2.6,
                    marker="o",
                    markersize=8,
                    zorder=3,
                )
            top = max(top, max(p["net"] for p in pts))
            changes = _change_points(pts)
            change_x += [x for x, _ in changes]
            if changes:
                notes[scen] = changes[-1][1]
        _mark_changes(ax, change_x)
        top = _ref_line(ax, top)
        ylim = top * 1.2
        ax.set_ylim(0, ylim)
        _categorical_x(ax, versions, label_room(n, 1.8 if notes else 1.4))
        names = list(series)
        ys = [series[s][-1]["net"] for s in names]
        heights = [2.1 if s in notes else 1.0 for s in names]
        ly = spread(ys, ylim * 0.065, heights)
        for scen, y1 in zip(names, ly):
            last = series[scen][-1]
            label = SCENARIO_SHORT[scen]
            if scen in notes:
                label += f"\n(new test from {notes[scen]})"
            ax.text(
                last["idx"] + 0.15,
                y1,
                label,
                color=SCENARIO_TEXT[scen],
                fontsize=FS_DIRECT,
                fontweight="bold",
                va="center",
                linespacing=1.15,
            )
        if n == 1:
            _first_release_note(ax)
        _finish(fig, ax, path, "Average cost per frame across releases")


def net_timeline(tl: dict) -> list[float]:
    """Bucket addonMs minus the timeline rep's idle baseline, clamped at 0."""
    base = tl.get("baselineMs") or 0.0
    return [
        max(0.0, (v if v is not None else 0.0) - base) for v in tl.get("addonMs", [])
    ]


def _peak_ha(x: float, xmax: float) -> str:
    return "left" if x < xmax * 0.2 else "right" if x > xmax * 0.8 else "center"


def chart_timeline(path: Path, scen: str, version: str, tl: dict):
    colour = SCENARIO_COLOUR[scen]
    dark = SCENARIO_TEXT[scen]
    ms = net_timeline(tl)
    live = [v if v is not None else 0.0 for v in tl.get("live", [])]
    n = len(ms)
    step = tl.get("step") or 0.5
    xs = [i * step for i in range(n)]
    xmax = max(xs[-1], step) if xs else 1
    with _style():
        fig, ax = _new_axes()
        ax2 = ax.twinx()
        ax.set_zorder(ax2.get_zorder() + 1)
        ax.patch.set_visible(False)
        for side in ("top", "right"):
            ax2.spines[side].set_visible(False)
        ax2.grid(False)
        ax2.yaxis.set_major_locator(MaxNLocator(5))
        ax2.set_ylabel("orbs on screen", fontsize=FS_LABEL)
        ax.set_xlim(0, xmax)
        ax.set_xlabel("seconds into the run", fontsize=FS_LABEL)
        ax.plot(xs, ms, color=colour, linewidth=2.4)
        top = max(max(ms, default=0.0), 0.05)
        top = _ref_line(ax, top)
        ax.set_ylim(0, top * 1.35)
        if ms:  # direct label on the cost line, at its peak
            ipk = max(range(n), key=lambda i: ms[i])
            ax.text(
                xs[ipk],
                ms[ipk] + top * 0.04,
                "XP Orbs cost",
                color=dark,
                fontsize=FS_DIRECT,
                fontweight="bold",
                ha=_peak_ha(xs[ipk], xmax),
                va="bottom",
            )
        if live:
            m = min(n, len(live))
            ax2.fill_between(xs[:m], live[:m], color="#d9d9d9", alpha=0.8, linewidth=0)
            ylim2 = max(max(live), 1) * 1.3
            ax2.set_ylim(0, ylim2)
            ipk = max(range(m), key=lambda i: live[i])
            ax2.text(
                xs[ipk],
                ylim2 * 0.03,
                "orbs on screen",
                color="#555555",
                fontsize=FS_DIRECT,
                fontweight="bold",
                ha=_peak_ha(xs[ipk], xmax),
                va="bottom",
            )
        title = _title(
            "What happens during one run", SCENARIO_LABEL[scen], f" (version {version})"
        )
        _finish(fig, ax, path, title)


# --------------------------------------------------------------------------- README


def profiler_cell(summary: dict) -> str:
    """The game profiler's cross-check figure, or n/a when the run had none."""
    ms = summary.get("profilerMeanMs")
    return fmt_ms(ms) if ms is not None else "n/a"


def _screen(ds: dict) -> str | None:
    screen = ds.get("screen")
    return (
        screen if isinstance(screen, str) and re.match(r"^\d+x\d+$", screen) else None
    )


def _num_or_none(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def active_limiters(limits) -> list[str]:
    """Names of the fps limiters that were on, e.g. ['Target FPS (90)', 'vsync']."""
    if not isinstance(limits, dict):
        return []
    on = ("1", "true")
    out = []
    max_fps = _num_or_none(limits.get("maxFPS"))
    use_max = limits.get("useMaxFPS")
    if max_fps and max_fps > 0 and (use_max is None or use_max in on):
        out.append(f"Max FPS ({max_fps:g})")
    target = _num_or_none(limits.get("targetFPS"))
    if target and target > 0 and limits.get("useTargetFPS") in on:
        out.append(f"Target FPS ({target:g})")
    if limits.get("vsync") in on:
        out.append("vsync")
    return out


def headline_rows(ds: dict) -> list[str]:
    rows = []
    for scen in SCENARIOS:
        s = ds["scenarios"].get(scen)
        if not s:
            continue
        sm = s["summary"]
        net = sm["netMeanMs"]
        p99 = sm.get("p99Ms")
        rows.append(
            f"| {SCENARIO_LABEL[scen]} | {fmt_ms(net)} "
            f"| {fmt_ms(p99) if p99 is not None else 'n/a'} "
            f"| {fmt_fps(fps_cost(60, net))} | {fmt_fps(fps_cost(144, net))} "
            f"| {verdict(net)} | {profiler_cell(sm)} |"
        )
    return rows


def _names(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


def summary_paragraph(ds: dict) -> str:
    sc = ds["scenarios"]
    screen = _screen(ds)
    rig_has_screen = screen is None or (
        screen in ds["rig"] or screen.split("x")[-1] in ds["rig"]
    )
    head = f"**Version {ds['version']}**, measured on {ds['rig']} (game build {ds['build']}"
    head += ")." if rig_has_screen else f", {screen} screen)."
    # lower-case: they are used mid-sentence; a sentence that starts with one capitalises it
    sentence_names = {
        "typical": "typical play",
        "aoe": "AoE farming",
        "max": "the maximum-settings stress test (a worst case nobody plays in)",
    }
    nets = {s: sc[s]["summary"]["netMeanMs"] for s in SCENARIOS if s in sc}
    low = [s for s in nets if fps_cost(60, nets[s]) < 1]
    parts = []
    if low:
        ms = _names([f"{nets[s]:.2f}" for s in low])
        names = _capitalise(_names([sentence_names[s] for s in low]))
        verb = "each cost" if len(low) > 1 else "costs"
        parts.append(f"{names} {verb} under 1 fps at 60 fps ({ms} ms per frame).")
    for s, net in nets.items():
        if s not in low:
            parts.append(
                f"{_capitalise(sentence_names[s])} costs about {fps_cost(60, net):.1f} fps at 60 fps "
                f"({net:.2f} ms per frame)."
            )
    return head + " " + " ".join(parts)


def history_table(sets: list[dict], series: dict[str, list[dict]]) -> list[str]:
    scens = [s for s in SCENARIOS if series.get(s)]
    lines = [
        "| Version | " + " | ".join(SCENARIO_LABEL[s] for s in scens) + " |",
        "|---|" + "---|" * len(scens),
    ]
    by_idx = {s: {p["idx"]: (i, p) for i, p in enumerate(series[s])} for s in scens}
    marked = False
    for idx in range(len(sets) - 1, -1, -1):
        cells = []
        for s in scens:
            hit = by_idx[s].get(idx)
            if not hit:
                cells.append("-")
                continue
            i, p = hit
            cell = fmt_ms(p["net"])
            if i > 0 and series[s][i - 1]["sv"] != p["sv"]:
                cell += " †"
                marked = True
            else:
                prev = previous_comparable(series[s], i)
                if prev is not None:
                    cell += f" ({format_change(prev, p['net'])})"
            cells.append(cell)
        lines.append(f"| {sets[idx]['version']} | " + " | ".join(cells) + " |")
    if marked:
        lines += [
            "",
            (
                "† The test scenario changed in this release, so it can't be compared "
                "with the row below it; the charts start a new line here."
            ),
        ]
    return lines


def build_readme(sets: list[dict], img_scens: dict) -> str:
    """Markdown for the report. img_scens: {'trend': [scen...], 'timeline': [scen...]}."""
    newest = sets[-1]
    series = {s: scenario_points(sets, s) for s in SCENARIOS}
    series = {s: p for s, p in series.items() if p}
    L = [
        "# XP Orbs performance",
        "",
        (
            "Every frame the game draws has a time budget. At 60 frames per second (fps) "
            "the game has 16.7 ms (milliseconds) to draw each frame. "
            '"ms per frame" below is how much of that budget XP Orbs itself uses on the '
            "CPU, so 0.5 ms per frame is about 3% of a 60 fps frame. "
            "Lower is better."
        ),
        "",
        summary_paragraph(newest),
        "",
        f"### Version {newest['version']} at a glance",
        "",
        HEADLINE_HEADER,
        "|---|---|---|---|---|---|---|",
        *headline_rows(newest),
        "",
        (
            "*Average cost* is what XP Orbs adds to a typical frame. *Worst 1%* is the cost "
            "of the slowest one frame in a hundred, which is what you'd feel as a hitch. "
            "*fps cost* converts the average into frames per second lost at 60 and 144 fps. "
            "*Game profiler (cross-check)* is the same average as the game's own addon "
            "profiler reports it."
        ),
        "",
        "![Average cost per frame across releases](img/trends-overview.png)",
        "",
        "## How it changes between releases",
        "",
    ]
    for scen in img_scens["trend"]:
        L += [
            (
                f"![Cost per frame across releases: {SCENARIO_LABEL[scen]}]"
                f"(img/trend-{scen}.png)"
            ),
            "",
        ]
    L += history_table(sets, series)
    L += ["", f"## Inside one run (version {newest['version']})", ""]
    L += [
        (
            "XP Orbs' cost per frame (coloured line) over the length of a test run, "
            "against how many orbs are on screen (grey area). The cost shown is after "
            "subtracting the idle baseline, the same way as in the table above."
        ),
        "",
        (
            f"<details><summary>Inside one run (version {newest['version']}): "
            "click to show</summary>"
        ),
        "",
    ]
    for scen in img_scens["timeline"]:
        L += [
            (
                f"![What happens during one run: {SCENARIO_LABEL[scen]}]"
                f"(img/timeline-{scen}.png)"
            ),
            "",
        ]
    L += ["</details>", ""]
    L += [
        "## How this is measured",
        "",
        (
            "Each test is a scripted fight run inside the game with the addon's benchmark "
            "tool, using fixed random seeds so every release faces the same test:"
        ),
        "",
        "- **Typical play:** a few mobs at a time, up to 3 dying together.",
        "- **AoE farming:** many mobs dying in overlapping waves every few seconds.",
        (
            "- **Maximum settings stress test:** every setting at its maximum and the "
            "screen kept full of orbs, a worst case nobody plays in."
        ),
        "",
        (
            "Typical play and AoE farming use the default settings. Sound is off in all "
            "tests."
        ),
        "",
    ]
    has_profiler = any(
        sc["summary"].get("profilerMeanMs") is not None
        for sc in newest["scenarios"].values()
    )
    L += [
        (
            "The cost is measured by XP Orbs' own timers around its per-frame update and "
            "every burst of orbs it creates, minus an idle baseline measured just before "
            "the test, so only the work XP Orbs causes is counted."
        ),
        "",
    ]
    if has_profiler:
        L += [
            (
                "The game's own addon profiler (its recent average, the figure addon "
                "profilers like Numy's show) is listed alongside as a cross-check."
            ),
            "",
        ]
    else:
        L += [
            (
                "The game's own addon profiler was not available or did not report XP "
                "Orbs' time for this run, so there is no cross-check figure."
            ),
            "",
        ]
    limiters = active_limiters(newest.get("limits"))
    if limiters:
        L += [
            (
                f"Frame rate was limited by {_names(limiters)} during this run, which "
                "affects the fps figures but not the ms cost."
            ),
            "",
        ]
    L += [
        "Each test is repeated 3 times and the median of the repeats is shown.",
        "",
        f"- Rig: {newest['rig']}",
        f"- Game build: {newest['build']}",
        *([f"- Screen: {_screen(newest)}"] if _screen(newest) else []),
        f"- Measured: {newest['date']}",
        "",
        "**Things to keep in mind**",
        "",
        (
            "- CPU time is exact. GPU cost is not part of the cost columns; it only shows "
            "up indirectly as lower frame rates, and those readings are noisy."
        ),
        (
            "- All numbers come from one PC. Compare releases with each other, not "
            "with other people's PCs."
        ),
        "",
        "---",
        "",
        (
            "Generated by `uv run python tools/bench/report.py render` from the files in "
            "`docs/performance/data/`."
        ),
        "",
    ]
    return "\n".join(L)


def render(data_dir: Path, out_dir: Path, rig: str | None) -> list[Path]:
    sets_all = load_data(data_dir)
    rig = pick_rig(sets_all, rig)
    sets = rig_sets(sets_all, rig)
    versions = [d["version"] for d in sets]
    series = {s: scenario_points(sets, s) for s in SCENARIOS}
    series = {s: p for s, p in series.items() if p}
    img = Path(out_dir) / "img"
    img.mkdir(parents=True, exist_ok=True)
    written = []
    trend_scens = []
    for scen, pts in series.items():
        p = img / f"trend-{scen}.png"
        chart_trend(p, scen, versions, pts)
        written.append(p)
        trend_scens.append(scen)
    p = img / "trends-overview.png"
    chart_overview(p, versions, series)
    written.append(p)
    newest = sets[-1]
    timeline_scens = []
    for scen in SCENARIOS:
        s = newest["scenarios"].get(scen)
        tl = s.get("timeline") if s else None
        if tl and tl.get("addonMs"):
            p = img / f"timeline-{scen}.png"
            chart_timeline(p, scen, newest["version"], tl)
            written.append(p)
            timeline_scens.append(scen)
    readme = Path(out_dir) / "README.md"
    readme.write_text(
        build_readme(sets, {"trend": trend_scens, "timeline": timeline_scens}),
        encoding="utf-8",
        newline="\n",
    )
    return [readme, *written]


def cmd_render(args) -> int:
    files = render(Path(args.data_dir), Path(args.out_dir), args.rig)
    print(f"wrote {len(files)} files ({show(files[0])} and charts in img/)")
    return 0


# --------------------------------------------------------------------------- notes


def notes_text(sets_all: list[dict], rig: str | None, version: str | None) -> str:
    rig = pick_rig(sets_all, rig)
    sets = rig_sets(sets_all, rig)
    if version is None:
        idx = len(sets) - 1
    else:
        idx = next((i for i, d in enumerate(sets) if d["version"] == version), None)
        if idx is None:
            raise BenchError(f"no data for version {version} on rig '{rig}'")
    ds = sets[idx]
    rows = []
    for scen in SCENARIOS:
        s = ds["scenarios"].get(scen)
        if not s:
            continue
        sm = s["summary"]
        net = sm["netMeanMs"]
        prev = None
        if idx > 0:
            ps = sets[idx - 1]["scenarios"].get(scen)
            if ps and ps.get("scenarioVersion", 1) == s.get("scenarioVersion", 1):
                prev = ps["summary"]["netMeanMs"]
        p99 = sm.get("p99Ms")
        rows.append(
            f"| {SCENARIO_LABEL[scen]} | {fmt_ms(net)} "
            f"| {fmt_ms(p99) if p99 is not None else 'n/a'} "
            f"| {fmt_fps(fps_cost(60, net))} | {verdict(net)} "
            f"| {profiler_cell(sm)} | {format_change(prev, net)} |"
        )
    return "\n".join(
        [
            (
                f"Performance of XP Orbs {ds['version']} (CPU cost per frame, lower is "
                f"better), measured in game on {ds['rig']}."
            ),
            "",
            NOTES_HEADER,
            "|---|---|---|---|---|---|---|",
            *rows,
            "",
            f"Full report: {README_REL}",
            "",
        ]
    )


def cmd_notes(args) -> int:
    sys.stdout.write(notes_text(load_data(Path(args.data_dir)), args.rig, args.version))
    return 0


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    common.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    common.add_argument("--toc", default=str(DEFAULT_TOC))
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", parents=[common], help="SavedVariables -> data JSON")
    ing.add_argument(
        "--rig", required=True, help='hardware label, e.g. "Ryzen 7, RTX 4070, 1440p"'
    )
    ing.add_argument("--sv", help=f"SavedVariables file (else env {SV_ENV})")
    ing.add_argument("--version", help="addon version (default: from the .toc)")
    ing.add_argument("--batch", help="batch id (default: newest for the version)")
    ing.add_argument("--force", action="store_true", help="overwrite existing data")
    ing.set_defaults(func=cmd_ingest)

    ren = sub.add_parser(
        "render", parents=[common], help="data JSON -> README + charts"
    )
    ren.add_argument("--rig", help="rig label (default: rig of the newest version)")
    ren.set_defaults(func=cmd_render)

    nts = sub.add_parser("notes", parents=[common], help="release-notes markdown block")
    nts.add_argument("--version", help="default: newest version")
    nts.add_argument("--rig", help="rig label (default: rig of the newest version)")
    nts.set_defaults(func=cmd_notes)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
