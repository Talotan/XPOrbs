# Benchmark data format (schema 2)

The in-game bench (`dev/Bench.lua`, never packaged) writes runs to `XPOrbsDB.bench`. `tools/bench/report.py ingest`
reads them from the SavedVariables file and writes one JSON file per release to `docs/performance/data/`.
`report.py render` turns every JSON file into `docs/performance/README.md` and its charts.

Schema 2 replaced schema 1, whose "profiler" source read `C_AddOnProfiler` `LastTime`, a metric that returns 0 every
frame on this client. Runs without `schema = 2` are skipped by `ingest`.

## In game: `XPOrbsDB.bench`

```lua
XPOrbsDB.bench = {
    schema = 2,
    restore = nil,  -- while a bench runs: a deep copy of the player's settings (every db key except `bench`);
                    -- restored and cleared on finish, stop, error, combat, or the next load after a /reload
    runs = {        -- newest last; at most 30 (oldest dropped). Aborted runs are never saved.
        {
            schema = 2,                     -- per run (the store's own `schema` is bumped as soon as any run is added)
            id = "20261127T101500-aoe-2",   -- date("!%Y%m%dT%H%M%S") of the batch start, scenario, rep
            batch = "20261127T101500",      -- shared by every run of one /xporbs bench command
            scenario = "aoe",               -- "max" | "aoe" | "typical"
            scenarioVersion = 1,            -- bump when a scenario's script or settings change
            rep = 2, reps = 3,
            seed = 4242,
            addonVersion = "1.4.2",         -- the toc ## Version
            build = "1.16.1", buildNumber = "12345", interface = 16001,   -- GetBuildInfo()
            date = "2026-11-27T10:15:00Z",
            screenW = 2560, screenH = 1440, -- physical pixels: GetPhysicalScreenSize(), else the cvar
                                            -- gxFullscreenResolution / gxWindowedResolution ("2560x1440");
                                            -- both omitted (nil) when neither answers
            uiScale = 0.71,                 -- UIParent effective scale
            vsync = "0",                    -- the fps limiters, GetCVar strings (each nil when unreadable):
            maxFPS = "0", useMaxFPS = "0",  --   foreground cap and its on/off switch
            targetFPS = "0", useTargetFPS = "0", -- "Target FPS" and its switch
            source = "internal",            -- always: XP Orbs' own timers (driver timer + Burst timer)
            profilerMetric = "RecentAverageTime", -- the game profiler metric sampled as a cross-check;
                                            -- nil when C_AddOnProfiler is off or missing
            settings = {                    -- the scenario preset as applied (summary for the report)
                orbShape = "starlight", size = 14, density = 100, cap = 40, flightPath = "smooth",
                style = "popstream", popMode = "nameplate", flightMode = "time", flightTime = 1.0,
                trail = true, glowIntensity = 100, sound = false,
            },
            baseline = Phase,               -- idle phase before the load (bench running, no bursts)
            load = Phase,                   -- the scripted kills, then the drain until no orb/pop is left (cap +8 s)
            kills = 37, orbs = 412,         -- bursts fired, orbs requested (sum of n)
            peakLive = 96, peakTextures = 410,
            burstMs = Stats,                -- time inside each Orbs:Burst call (debugprofilestop), n = kills
            driverMs = 0.81,                -- Orbs' own driver timer over the load phase: total ms / frames
            memStartKB = 812.4, memEndKB = 815.0,  -- GetAddOnMemoryUsage after UpdateAddOnMemoryUsage
            timeline = {                    -- load phase in 0.5 s buckets (index i covers [(i-1)*step, i*step))
                step = 0.5,
                addonMs = {},               -- mean XPOrbs ms per frame in the bucket
                addonMaxMs = {},            -- worst frame in the bucket
                frameMs = {},               -- mean frame time (ms) in the bucket
                live = {},                  -- live orbs at the bucket's last frame
            },
        },
    },
}
```

Changes from schema 1: every run carries `schema`; `source` is always `"internal"` (the `C_AddOnProfiler` `LastTime`
path is gone); added `profilerMetric`, `useMaxFPS`, `targetFPS`, `useTargetFPS` and the phase field `profilerMs`;
`vsync` now reads the cvar `vsync` (it was `gxVSync`, which this client does not have); `screenW`/`screenH` are
physical pixels (they were UI units times scale, which was wrong); `gcKB` is removed (the Lua heap rise over all
addons was noise).

`Phase`:

```lua
{
    seconds = 10.0, frames = 1004,
    addonMs = Stats,     -- XP Orbs time per frame: the driver timer's delta plus the previous frame's Burst ms.
                         -- This is the measurement; the net cost is the load mean minus the baseline mean.
    profilerMs = Stats,  -- cross-check: C_AddOnProfiler.GetAddOnMetric("XPOrbs", RecentAverageTime) sampled every
                         -- frame (a rolling average, so it lags); nil when the profiler is unavailable
    overallMs = Stats,   -- all addons: GetOverallMetric(RecentAverageTime) every frame; nil with `profilerMs`
    frameMs = Stats,     -- whole frame time from OnUpdate elapsed
}
```

`Stats` (all in ms): `{ n, mean, p50, p95, p99, max, over1, over5, over10, over16 }`. `overX` = how many samples
were above X ms (`over16` means above 16.67 ms, one 60 fps frame).
Percentiles: nearest-rank on the sorted samples (`p = s[max(1, ceil(q * n))]`).

## Published: `docs/performance/data/<version>.json`

```json
{
  "schema": 2,
  "version": "1.4.2",
  "date": "2026-11-27",
  "rig": "Ryzen 7 7800X3D, RTX 4070, 1440p",
  "build": "1.16.1 (12345)",
  "screen": "2560x1440",
  "source": "internal",
  "limits": { "vsync": "0", "maxFPS": "0", "useMaxFPS": "0", "targetFPS": "0", "useTargetFPS": "0" },
  "scenarios": {
    "max": {
      "scenarioVersion": 1,
      "settings": {},
      "reps": 3,
      "summary": {
        "netMeanMs": 0.98, "meanMs": 1.01, "baselineMeanMs": 0.03, "profilerMeanMs": 0.95,
        "p95Ms": 1.6, "p99Ms": 2.1, "maxMs": 2.7,
        "over5": 0, "over16": 0,
        "frameMsBaseline": 9.9, "frameMsLoad": 10.9, "fpsBaseline": 101.0, "fpsLoad": 91.7,
        "burstMeanMs": 0.12, "burstMaxMs": 0.4,
        "peakLive": 160, "peakTextures": 810, "kills": 120, "orbs": 9600,
        "memDeltaKB": 2.6,
        "shareOfAppPct": 9.3
      },
      "repsDetail": [{ "netMeanMs": 0.97, "p99Ms": 2.0, "fpsLoad": 92.1 }],
      "timeline": { "step": 0.5, "addonMs": [], "addonMaxMs": [], "frameMs": [], "live": [] }
    }
  }
}
```

- Summary values are the **median across reps** of each rep's value. `netMeanMs` = load `addonMs.mean` minus baseline
  `addonMs.mean` (never below 0). `profilerMeanMs` = the same net figure from `profilerMs` (never below 0), `null`
  when no rep recorded it; the report shows it as the "Game profiler (cross-check)" column, or "n/a".
  `fps*` = 1000 / `frameMs.mean`. `shareOfAppPct` = 100 * load addon mean / load frame mean. `timeline` is the rep
  whose `netMeanMs` is the median.
- `screen` is the physical resolution from the newest run, or `null` when the runs did not record one (the report
  then leaves the screen out). `source` is always `"internal"`.
- `limits` are the fps-limiter cvars of the batch's first run (strings or `null`). The report adds a line when one
  was on (`useMaxFPS` on with `maxFPS` > 0, or `maxFPS` > 0 with no switch recorded; `useTargetFPS` on with
  `targetFPS` > 0; `vsync` on): the limiter affects the fps figures, not the ms cost.
- `gcKB` no longer exists in either format.
- **Never** written: account names, character names, realm, file paths, the SavedVariables location.
- Comparisons across releases only use files with the same `rig` and, per scenario, the same `scenarioVersion`.
